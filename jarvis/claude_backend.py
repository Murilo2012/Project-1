"""
Backend do Claude Code para o JARVIS — substitui o Gemini nos módulos de código.

O actions/dev_agent.py e o actions/code_helper.py hoje rodam em
gemini-2.5-flash, um modelo pequeno que erra bastante ao escrever e corrigir
código. Este módulo troca esse motor pelo Claude Code em modo headless
(`claude -p`), que usa a assinatura já instalada na máquina — sem chave de API
e sem cobrança por token.

Instalação:
    1. Copie este arquivo para a raiz do Mark-L (ao lado de main.py).
    2. Em actions/dev_agent.py, troque a função _get_model inteira por:

           from claude_backend import get_model as _get_model

    3. Faça o mesmo em actions/code_helper.py, se ele tiver um _get_model.

A interface imita a do google-genai (objeto com .generate_content(contents)
devolvendo algo com .text), então o resto do dev_agent continua funcionando sem
nenhuma outra alteração.

Pré-requisito: Claude Code instalado e autenticado (`claude --version` responde).
"""
from __future__ import annotations

import shutil
import subprocess

# O dev_agent às vezes roda por vários minutos encadeando planejamento,
# escrita e até 5 tentativas de correção. 10 min cobre o pior caso.
_TIMEOUT = 600


class _Response:
    """Imita a resposta do google-genai: o dev_agent só lê .text."""

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


def get_model(model_name: str = "") -> _ClaudeModel:
    """Drop-in do _get_model do dev_agent. model_name é ignorado."""
    binary = shutil.which("claude")
    if not binary:
        raise RuntimeError(
            "Comando 'claude' não encontrado no PATH.\n"
            "Instale o Claude Code e confirme com: claude --version"
        )
    return _ClaudeModel(binary)
