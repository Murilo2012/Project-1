"""O cérebro: laço agêntico contra a API da Claude.

Escrevi o laço à mão em vez de usar o tool runner do SDK por dois motivos:

  1. O gate de confirmação precisa acontecer ENTRE o modelo pedir a ferramenta
     e ela rodar, e a pergunta é feita por voz. Isso quer dizer parar o laço,
     falar, gravar a resposta e decidir. Controle no nível do harness.
  2. look_at_screen devolve uma imagem. Tool result com bloco de imagem exige
     montar o conteúdo na mão.

Sobre o thinking: fica LIGADO (adaptativo). No Opus 5, desligar o thinking tem
um modo de falha conhecido em que o modelo escreve a chamada de ferramenta como
texto visível em vez de emitir o bloco tool_use — a ação simplesmente não roda,
sem erro nenhum. Num assistente que é quase só ferramenta, isso seria fatal.
Pra economizar, o controle é o effort (padrão 'low'), não desligar o thinking.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import anthropic

from apex import persona
from apex.safety import Risk, SafetyGate
from apex.tools import ToolContext, all_tools, execute

# Ferramenta server-side: a busca roda na infraestrutura da Anthropic, não aqui.
WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search", "max_uses": 5}

MAX_TOOL_ITERATIONS = 25
MAX_PAUSE_RESUMES = 3
HISTORY_TURNS = 12


@dataclass
class Turn:
    text: str
    tool_calls: list[str]
    elapsed: float


class Brain:
    def __init__(
        self,
        config,
        vault,
        on_status: Callable[[str], None] | None = None,
        on_confirm: Callable[[str], bool] | None = None,
    ):
        self.config = config
        self.vault = vault
        self.client = anthropic.Anthropic(api_key=config.api_key)
        self.model = config.get("model", "claude-opus-5")
        self.effort = config.get("effort", "low")
        self.max_tokens = int(config.get("max_tokens", 8000))
        self.gate = SafetyGate(config.get("safety", {}))

        # on_status: mensagem curta pro HUD/terminal, não pra voz.
        # on_confirm: pergunta ao usuário por voz e devolve True/False.
        self.on_status = on_status or (lambda _msg: None)
        self.on_confirm = on_confirm or (lambda _reason: False)

        self.ctx = ToolContext(
            config=config,
            vault=vault,
            workspace=config.workspace,
            skills_dir=config.skills_dir,
        )
        self.tools = [*all_tools(), WEB_SEARCH_TOOL]
        self.system = persona.build_system_prompt(
            config.name, config.workspace, vault.root
        )
        self.messages: list[dict] = []
        self.last_usage: dict[str, int] = {}

    # -- histórico --------------------------------------------------------

    def reset(self) -> None:
        """Zera a conversa. Chamado quando a janela de conversa expira."""
        self.messages = []

    def _trim_history(self) -> None:
        """Segura o tamanho do contexto.

        Prints de tela são caros — cada um vale milhares de tokens. Em vez de
        truncar mensagens no meio (o que quebra os pares tool_use/tool_result),
        removo turnos inteiros do começo e apago as imagens dos turnos antigos.
        """
        if len(self.messages) > HISTORY_TURNS * 2:
            # Corta em um limite de turno do usuário, senão sobra um
            # tool_result órfão e a API rejeita.
            cut = len(self.messages) - HISTORY_TURNS * 2
            while cut < len(self.messages) and self.messages[cut].get("role") != "user":
                cut += 1
            self.messages = self.messages[cut:]
            while self.messages and self._has_orphan_tool_result(self.messages[0]):
                self.messages.pop(0)

        # Só o print mais recente fica; os anteriores viram texto.
        seen_image = False
        for message in reversed(self.messages):
            content = message.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                inner = block.get("content")
                if block.get("type") == "tool_result" and isinstance(inner, list):
                    for index, sub in enumerate(inner):
                        if isinstance(sub, dict) and sub.get("type") == "image":
                            if seen_image:
                                inner[index] = {
                                    "type": "text",
                                    "text": "[print antigo removido do contexto]",
                                }
                            else:
                                seen_image = True

    @staticmethod
    def _has_orphan_tool_result(message: dict) -> bool:
        content = message.get("content")
        if not isinstance(content, list):
            return False
        return any(
            isinstance(b, dict) and b.get("type") == "tool_result" for b in content
        )

    # -- chamada ----------------------------------------------------------

    def _create(self):
        return self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=[{"type": "text", "text": self.system, "cache_control": {"type": "ephemeral"}}],
            messages=self.messages,
            tools=self.tools,
            thinking={"type": "adaptive"},
            output_config={"effort": self.effort},
        )

    def ask(self, user_text: str) -> Turn:
        """Manda um comando e roda o laço até o modelo terminar."""
        started = time.monotonic()
        self.messages.append({"role": "user", "content": user_text})
        self._trim_history()

        tool_calls: list[str] = []
        pause_resumes = 0

        for _iteration in range(MAX_TOOL_ITERATIONS):
            try:
                response = self._create()
            except anthropic.RateLimitError:
                return Turn("Tô no limite de uso da API. Espera um pouco.", tool_calls, 0)
            except anthropic.AuthenticationError:
                return Turn("A chave da API foi rejeitada. Confere o config.", tool_calls, 0)
            except anthropic.APIConnectionError:
                return Turn("Sem conexão com a API. Confere a internet.", tool_calls, 0)
            except anthropic.APIStatusError as exc:
                return Turn(f"A API devolveu erro {exc.status_code}.", tool_calls, 0)

            self._record_usage(response)

            if response.stop_reason == "refusal":
                self.messages.append({"role": "assistant", "content": response.content})
                return Turn("Não vou fazer isso.", tool_calls, time.monotonic() - started)

            self.messages.append({"role": "assistant", "content": response.content})

            # Ferramenta server-side estourou o limite de iterações: reenviar
            # continua de onde parou. Não adicione mensagem de usuário aqui.
            if response.stop_reason == "pause_turn":
                pause_resumes += 1
                if pause_resumes > MAX_PAUSE_RESUMES:
                    return Turn(
                        "A busca ficou longa demais e eu parei.", tool_calls,
                        time.monotonic() - started,
                    )
                continue

            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if not tool_uses:
                text = "".join(b.text for b in response.content if b.type == "text").strip()
                return Turn(text, tool_calls, time.monotonic() - started)

            results = []
            for block in tool_uses:
                tool_calls.append(block.name)
                results.append(self._run_tool(block))

            self.messages.append({"role": "user", "content": results})
            self._trim_history()

        return Turn(
            "Tentei muitos passos e não cheguei ao fim. Tenta pedir de outro jeito.",
            tool_calls,
            time.monotonic() - started,
        )

    # -- execução de ferramenta com o gate --------------------------------

    def _run_tool(self, block) -> dict:
        tool_input = dict(block.input or {})
        verdict = self.gate.evaluate(block.name, tool_input)

        if verdict.risk is Risk.BLOCKED:
            self.on_status(f"BLOQUEADO {block.name}: {verdict.reason}")
            return {
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": f"Bloqueado pela camada de segurança: {verdict.reason}. "
                           "Não tente contornar — explique isso ao usuário.",
                "is_error": True,
            }

        if verdict.risk is Risk.CONFIRM:
            self.on_status(f"CONFIRMAR {block.name}: {verdict.reason}")
            if not self.on_confirm(verdict.reason):
                return {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": "O usuário NÃO confirmou. A ação não foi executada. "
                               "Pare e confirme o que ele quer.",
                    "is_error": True,
                }

        self.on_status(f"{block.name} {self._short_args(tool_input)}")
        output = execute(block.name, tool_input, self.ctx)

        return {
            "type": "tool_result",
            "tool_use_id": block.id,
            "content": output if isinstance(output, list) else str(output),
        }

    @staticmethod
    def _short_args(tool_input: dict) -> str:
        if not tool_input:
            return ""
        try:
            rendered = json.dumps(tool_input, ensure_ascii=False)
        except (TypeError, ValueError):
            rendered = str(tool_input)
        return rendered[:90] + ("..." if len(rendered) > 90 else "")

    def _record_usage(self, response) -> None:
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        for field in ("input_tokens", "output_tokens",
                      "cache_read_input_tokens", "cache_creation_input_tokens"):
            value = getattr(usage, field, None)
            if value:
                self.last_usage[field] = self.last_usage.get(field, 0) + value


def make_brain(config, vault, on_status=None, on_confirm=None):
    """Escolhe o cérebro conforme a config. Os dois expõem a mesma interface,
    então nada mais no sistema precisa saber qual está rodando.

        "brain": "claude"   API da Anthropic — mais esperto, custa por comando
        "brain": "ollama"   modelo local — de graça, offline, e mais burro
    """
    kind = str(config.get("brain", "claude")).lower()

    if kind in ("ollama", "local"):
        # Import tardio: ollama_brain importa Turn daqui, e o import no topo
        # fecharia um ciclo.
        from apex.ollama_brain import OllamaBrain  # noqa: PLC0415

        return OllamaBrain(config, vault, on_status=on_status, on_confirm=on_confirm)

    if kind not in ("claude", "anthropic"):
        raise ValueError(f"cérebro desconhecido: '{kind}'. Use 'claude' ou 'ollama'.")

    return Brain(config, vault, on_status=on_status, on_confirm=on_confirm)


def one_shot(config, vault, prompt: str) -> str:
    """Uma pergunta, uma resposta, sem gate interativo. Usado pelo agendador —
    ninguém está lá pra confirmar nada, então ações destrutivas são negadas."""
    brain = make_brain(config, vault, on_confirm=lambda _reason: False)
    return brain.ask(prompt).text
