"""
Motor de programação do JARVIS: Claude Code quando disponível, Gemini quando não.

O actions/dev_agent.py e o actions/code_helper.py planejam, escrevem e corrigem
código. Rodando no Gemini flash — um modelo pequeno e rápido — erram bastante
nessa tarefa. Quando o Claude Code está instalado na máquina, este módulo os
roteia para lá em modo headless (`claude -p`), usando a assinatura local: sem
chave de API e sem cobrança por token.

Sem o Claude Code instalado, cai de volta no Gemini. Isso é deliberado: trocar
um motor existente por um ausente deixaria o agente de código pior do que
estava. O fallback mantém o comportamento original enquanto o Claude Code não
estiver lá.

Instalar o Claude Code: https://claude.com/claude-code
"""
from __future__ import annotations

import shutil
import subprocess

# O dev_agent encadeia planejamento, escrita e até 5 tentativas de correção.
# 10 minutos cobrem o pior caso sem travar a interface para sempre.
_TIMEOUT = 600

_avisado = False


class _Response:
    """Imita a resposta do google-genai: os chamadores só leem .text."""

    def __init__(self, text: str):
        self.text = text

    def __str__(self) -> str:
        return self.text


class _ClaudeModel:
    def __init__(self, binary: str):
        self._binary = binary

    def generate_content(self, contents) -> _Response:
        prompt = contents if isinstance(contents, str) else "\n\n".join(map(str, contents))

        try:
            proc = subprocess.run(
                [self._binary, "-p", prompt],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            return _Response(f"[claude] Sem resposta em {_TIMEOUT}s.")

        if proc.returncode != 0:
            err = (proc.stderr or "").strip()[:300]
            return _Response(f"[claude] Falhou (código {proc.returncode}): {err}")

        return _Response((proc.stdout or "").strip())


def _gemini(model_name: str = ""):
    """O motor original, usado quando o Claude Code não está instalado."""
    import json
    import sys
    from pathlib import Path

    raiz = (
        Path(sys.executable).parent
        if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parent
    )
    if str(raiz) not in sys.path:
        sys.path.insert(0, str(raiz))

    from google import genai
    from actions.gemini_model import flash

    chave = json.loads(
        (raiz / "config" / "api_keys.json").read_text(encoding="utf-8")
    )["gemini_api_key"]
    cliente = genai.Client(api_key=chave)
    modelo = model_name or flash()

    class _W:
        def generate_content(self, contents):
            return cliente.models.generate_content(model=modelo, contents=contents)

    return _W()


def get_model(model_name: str = ""):
    """Drop-in das fábricas do dev_agent e do code_helper.

    model_name era o nome do modelo Gemini. Ele é ignorado no caminho do Claude
    Code e respeitado no fallback.
    """
    global _avisado

    binary = shutil.which("claude")
    if binary:
        return _ClaudeModel(binary)

    if not _avisado:
        _avisado = True
        print(
            "[Código] Claude Code não encontrado no PATH — usando o Gemini.\n"
            "         Para o agente de programação ficar bem melhor, instale:\n"
            "         https://claude.com/claude-code"
        )
    # O nome cravado não vale mais nada; deixe o resolvedor escolher.
    return _gemini("")
