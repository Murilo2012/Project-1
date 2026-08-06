"""Cérebro local via Ollama. Sem nuvem, sem conta, sem custo por comando.

Este é o caminho que a maioria dos projetos de "Jarvis caseiro" segue:
faster-whisper pros ouvidos, Piper pra boca, Ollama pro cérebro. Os dois
primeiros o APEX já usava; este arquivo fecha o trio.

A interface é idêntica à do cérebro da Claude (`ask`, `reset`, `.gate`,
`.last_usage`), então o resto do sistema não sabe qual está rodando.

TRÊS COISAS QUE MUDAM DE VERDADE COM MODELO LOCAL

1. Ele escolhe ferramenta pior. Um modelo de 8B erra mais na hora de decidir
   *qual* ferramenta usar, e erra mais ainda quando tem 28 pra escolher. Por
   isso existe uma lista branca: em modo local, menos ferramentas e melhores
   resultados. Está em `ollama.tools` na config.

2. Ele precisa de instrução mais prescritiva, não menos. É o inverso do que
   vale pros modelos de fronteira, onde prompt muito mandão atrapalha.

3. Ele não enxerga, a menos que você use um modelo de visão. `look_at_screen`
   devolve imagem; sem `vision_model` configurado, essa ferramenta é retirada
   da lista em vez de falhar silenciosamente no meio de uma tarefa.

Sem dependência nova: fala com o Ollama por HTTP com a biblioteca padrão.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Callable

from apex import persona
from apex.brain import Turn
from apex.safety import Risk, SafetyGate
from apex.tools import REGISTRY, ToolContext, execute

MAX_TOOL_ITERATIONS = 12   # menor que na Claude: modelo local entra em laço mais fácil
HISTORY_TURNS = 8          # e também aguenta menos contexto

# Ferramentas que valem a pena expor a um modelo pequeno. As de fora não somem
# do APEX — só não entram no prompt do cérebro local, onde cada schema a mais
# piora a escolha.
DEFAULT_LOCAL_TOOLS = [
    "open_app",
    "run_shell",
    "system_status",
    "list_processes",
    "read_file",
    "write_file",
    "list_dir",
    "search_files",
    "set_volume",
    "media_control",
    "vault_search",
    "vault_write",
    "vault_capture",
    "focus_window",
    "list_windows",
]

# Reforço para modelos pequenos. Prescritivo de propósito — é o oposto do que
# se faz com modelo de fronteira, onde esse tom atrapalha.
LOCAL_SUFFIX = """

# Regras rígidas (siga à risca)
- Responda SEMPRE em português do Brasil.
- Máximo de DUAS frases. Suas respostas são faladas em voz alta.
- Nunca use markdown, lista, bullet, emoji ou bloco de código.
- Para abrir um programa, use a ferramenta open_app. Não descreva como fazer.
- Para saber o estado do PC, use system_status. Não invente números.
- Chame no máximo UMA ferramenta por vez, e espere o resultado antes da próxima.
- Depois que a ferramenta responder, diga o resultado em uma frase e PARE.
- Se não souber, diga "não sei". Não invente.
"""


class OllamaError(RuntimeError):
    pass


def _post(host: str, path: str, payload: dict, timeout: float) -> dict:
    request = urllib.request.Request(
        f"{host.rstrip('/')}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - host local
        return json.loads(response.read().decode("utf-8"))


def check_server(host: str, model: str) -> tuple[bool, str]:
    """Confere se o Ollama está de pé e se o modelo foi baixado."""
    try:
        with urllib.request.urlopen(f"{host.rstrip('/')}/api/tags", timeout=5) as response:  # noqa: S310
            tags = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        return False, (
            f"Não consegui falar com o Ollama em {host} ({exc.reason}). "
            "Instale em ollama.com e confira se está rodando."
        )
    except Exception as exc:  # noqa: BLE001
        return False, f"Erro ao consultar o Ollama: {exc}"

    available = [m.get("name", "") for m in tags.get("models", [])]
    base = model.split(":")[0]
    if not any(name == model or name.startswith(base + ":") for name in available):
        listing = ", ".join(available[:8]) or "nenhum"
        return False, (
            f"O modelo '{model}' não está baixado. Rode: ollama pull {model}\n"
            f"Baixados atualmente: {listing}"
        )
    return True, f"Ollama respondendo em {host}, modelo '{model}' pronto."


def _to_ollama_schema(tool: dict) -> dict:
    """Converte o schema do formato Anthropic pro formato do Ollama."""
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["input_schema"],
        },
    }


class OllamaBrain:
    def __init__(
        self,
        config,
        vault,
        on_status: Callable[[str], None] | None = None,
        on_confirm: Callable[[str], bool] | None = None,
    ):
        self.config = config
        self.vault = vault
        self.host = config.get("ollama.host", "http://localhost:11434")
        self.model = config.get("ollama.model", "qwen3:8b")
        self.vision_model = config.get("ollama.vision_model") or ""
        self.timeout = float(config.get("ollama.timeout", 180))
        self.think = bool(config.get("ollama.think", False))
        self.options = {
            "temperature": float(config.get("ollama.temperature", 0.4)),
            "num_ctx": int(config.get("ollama.num_ctx", 8192)),
        }

        self.gate = SafetyGate(config.get("safety", {}))
        self.on_status = on_status or (lambda _msg: None)
        self.on_confirm = on_confirm or (lambda _reason: False)

        self.ctx = ToolContext(
            config=config,
            vault=vault,
            workspace=config.workspace,
            skills_dir=config.skills_dir,
        )
        self.tools = self._build_tool_list()
        self.system = (
            persona.build_system_prompt(config.name, config.workspace, vault.root)
            + LOCAL_SUFFIX
        )
        self.messages: list[dict] = []
        self.last_usage: dict[str, int] = {}

    def _build_tool_list(self) -> list[dict]:
        allowed = self.config.get("ollama.tools") or DEFAULT_LOCAL_TOOLS
        names = [n for n in allowed if n in REGISTRY]

        # Sem modelo de visão, esconder a ferramenta é melhor que deixá-la
        # falhar no meio de uma tarefa.
        if not self.vision_model and "look_at_screen" in names:
            names.remove("look_at_screen")

        return [_to_ollama_schema(REGISTRY[n].to_api()) for n in sorted(names)]

    # -- histórico --------------------------------------------------------

    def reset(self) -> None:
        self.messages = []

    def _trim_history(self) -> None:
        if len(self.messages) <= HISTORY_TURNS * 2:
            return
        cut = len(self.messages) - HISTORY_TURNS * 2
        while cut < len(self.messages) and self.messages[cut].get("role") != "user":
            cut += 1
        self.messages = self.messages[cut:]
        # Um "tool" sem o "assistant" que o pediu confunde o modelo.
        while self.messages and self.messages[0].get("role") == "tool":
            self.messages.pop(0)

    # -- chamada ----------------------------------------------------------

    def _chat(self, model: str) -> dict:
        payload = {
            "model": model,
            "messages": [{"role": "system", "content": self.system}, *self.messages],
            "tools": self.tools,
            "stream": False,
            "options": self.options,
        }
        # Modelos com modo de raciocínio (Qwen3, por exemplo) ficam lentos
        # demais pra voz. Desligado por padrão.
        if not self.think:
            payload["think"] = False
        return _post(self.host, "/api/chat", payload, self.timeout)

    def ask(self, user_text: str) -> Turn:
        started = time.monotonic()
        self.messages.append({"role": "user", "content": user_text})
        self._trim_history()

        tool_calls: list[str] = []

        for _iteration in range(MAX_TOOL_ITERATIONS):
            try:
                response = self._chat(self.model)
            except urllib.error.URLError as exc:
                return Turn(
                    f"Não consigo falar com o Ollama. {exc.reason}.",
                    tool_calls, time.monotonic() - started,
                )
            except TimeoutError:
                return Turn(
                    "O modelo local demorou demais e eu desisti.",
                    tool_calls, time.monotonic() - started,
                )
            except Exception as exc:  # noqa: BLE001
                return Turn(f"Erro no cérebro local: {exc}", tool_calls, 0)

            message = response.get("message", {}) or {}
            self._record_usage(response)

            requested = message.get("tool_calls") or []
            content = (message.get("content") or "").strip()

            if not requested:
                return Turn(self._clean(content), tool_calls, time.monotonic() - started)

            # Guarda o turno do assistente com os pedidos de ferramenta.
            self.messages.append({
                "role": "assistant",
                "content": content,
                "tool_calls": requested,
            })

            for call in requested:
                function = call.get("function", {}) or {}
                name = function.get("name", "")
                arguments = function.get("arguments") or {}
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except json.JSONDecodeError:
                        arguments = {}
                tool_calls.append(name)
                self._run_tool(name, arguments)

            self._trim_history()

        return Turn(
            "Me embananei em muitos passos. Pede de outro jeito.",
            tool_calls, time.monotonic() - started,
        )

    # -- ferramentas ------------------------------------------------------

    def _run_tool(self, name: str, arguments: dict) -> None:
        if name not in REGISTRY:
            self._append_tool_result(name, f"Erro: ferramenta '{name}' não existe.")
            return

        verdict = self.gate.evaluate(name, arguments)

        if verdict.risk is Risk.BLOCKED:
            self.on_status(f"BLOQUEADO {name}: {verdict.reason}")
            self._append_tool_result(
                name, f"Bloqueado pela segurança: {verdict.reason}. Não tente contornar."
            )
            return

        if verdict.risk is Risk.CONFIRM:
            self.on_status(f"CONFIRMAR {name}: {verdict.reason}")
            if not self.on_confirm(verdict.reason):
                self._append_tool_result(
                    name, "O usuário NÃO confirmou. A ação não foi executada. Pare."
                )
                return

        self.on_status(f"{name} {json.dumps(arguments, ensure_ascii=False)[:80]}")
        output = execute(name, arguments, self.ctx)

        if isinstance(output, list):
            self._append_image_result(name, output)
        else:
            self._append_tool_result(name, str(output))

    def _append_tool_result(self, name: str, content: str) -> None:
        # `tool_name` é aceito por versões novas do Ollama e ignorado pelas
        # antigas — mandar não custa nada e ajuda o modelo a se localizar.
        self.messages.append({"role": "tool", "tool_name": name, "content": content[:6000]})

    def _append_image_result(self, name: str, blocks: list) -> None:
        """Resultado com imagem (o screenshot). No Ollama a imagem não vai no
        tool result: vai numa mensagem de usuário, no campo `images`."""
        images, texts = [], []
        for block in blocks:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "image":
                data = (block.get("source") or {}).get("data")
                if data:
                    images.append(data)
            elif block.get("type") == "text":
                texts.append(block.get("text", ""))

        self._append_tool_result(name, " ".join(texts) or "Imagem capturada.")
        if images and self.vision_model:
            self.messages.append({
                "role": "user",
                "content": "Esta é a tela agora. Olhe e continue a tarefa.",
                "images": images[:1],
            })

    @staticmethod
    def _clean(text: str) -> str:
        """Modelos locais vazam raciocínio e markdown mesmo mandados não vazar.

        O bloco de código sai INTEIRO, não só as cercas: ler código em voz alta
        é pior que não dizer nada. Se o usuário quer o código, ele pede pra
        gravar num arquivo.
        """
        import re  # noqa: PLC0415

        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<\|.*?\|>", "", text)  # tokens especiais de chat template
        text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
        text = re.sub(r"```.*", " ", text, flags=re.DOTALL)  # bloco não fechado
        text = re.sub(r"^\s*[-*•]\s+", "", text, flags=re.MULTILINE)
        text = re.sub(r"[*_#`]", "", text)
        return " ".join(text.split()).strip()

    def _record_usage(self, response: dict) -> None:
        for src, dst in (("prompt_eval_count", "input_tokens"), ("eval_count", "output_tokens")):
            value = response.get(src)
            if value:
                self.last_usage[dst] = self.last_usage.get(dst, 0) + int(value)
