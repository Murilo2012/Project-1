"""Camada de segurança: classifica ações e decide o que precisa de confirmação.

Por que isso existe: o modelo pode se enganar interpretando um comando falado.
"Limpa a pasta de downloads" e "limpa o disco C" ficam parecidos num áudio ruim
com o ventilador ligado. Esta camada é o que impede um erro de transcrição de
virar perda de dados.

Modos:
  permissive — só bloqueia a lista negra permanente
  confirm    — padrão: confirma ações destrutivas por voz
  paranoid   — confirma todo comando de shell e toda escrita
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class Risk(str, Enum):
    SAFE = "safe"
    CONFIRM = "confirm"
    BLOCKED = "blocked"


@dataclass
class Verdict:
    risk: Risk
    reason: str = ""


# Padrões de shell que sempre pedem confirmação (exceto em modo permissive).
_DESTRUCTIVE_SHELL: list[tuple[str, str]] = [
    (r"\b(Remove-Item|rm|del|erase|rd|rmdir)\b", "apaga arquivos ou pastas"),
    (r"\bformat\b", "formata uma unidade"),
    (r"\b(Stop-Computer|shutdown|Restart-Computer)\b", "desliga ou reinicia o PC"),
    (r"\bStop-Process\b", "encerra processos"),
    (r"\b(reg|Registry)\b.*\b(delete|Remove)\b", "mexe no registro do Windows"),
    (r"\bSet-ExecutionPolicy\b", "altera a política de execução"),
    (r"\b(Uninstall|msiexec\s+/x|winget\s+uninstall)\b", "desinstala um programa"),
    (r"\bnetsh\b", "altera a configuração de rede"),
    (r"\bSet-ItemProperty\b", "altera configurações do sistema"),
    (r"\b(icacls|takeown|attrib)\b", "altera permissões de arquivo"),
    (r"\bInvoke-(WebRequest|Expression)\b.*\|", "baixa e executa código da internet"),
    (r"\bcurl\b.*\|\s*(iex|powershell|cmd)", "baixa e executa código da internet"),
    (r"\bschtasks\b", "mexe em tarefas agendadas"),
    (r"\b(net\s+user|New-LocalUser|Remove-LocalUser)\b", "mexe em contas de usuário"),
    (r"\bgit\b.*\b(push\s+--force|reset\s+--hard|clean\s+-[a-z]*f)", "descarta trabalho no git"),
]

# Ferramentas que sempre exigem confirmação, qualquer que seja o argumento.
_DESTRUCTIVE_TOOLS: dict[str, str] = {
    "delete_path": "apaga um arquivo ou pasta",
    "shutdown_pc": "desliga o computador",
    "close_app": "fecha um programa, e pode ter coisa não salva",
}


class SafetyGate:
    def __init__(self, config: dict | None = None):
        config = config or {}
        self.mode = config.get("mode", "confirm")
        self.allow_shell = config.get("allow_shell", True)
        self.confirm_timeout = float(config.get("confirm_timeout", 12))
        self._blocked = [
            re.compile(p, re.IGNORECASE) for p in config.get("blocked_patterns", [])
        ]

    def evaluate(self, tool_name: str, tool_input: dict) -> Verdict:
        if tool_name == "run_shell":
            if not self.allow_shell:
                return Verdict(Risk.BLOCKED, "execução de comandos está desligada na config")
            return self._evaluate_shell(str(tool_input.get("command", "")))

        if tool_name in _DESTRUCTIVE_TOOLS:
            if self.mode == "permissive":
                return Verdict(Risk.SAFE)
            return Verdict(Risk.CONFIRM, _DESTRUCTIVE_TOOLS[tool_name])

        if tool_name == "write_file" and self.mode == "paranoid":
            return Verdict(Risk.CONFIRM, "grava um arquivo")

        return Verdict(Risk.SAFE)

    def _evaluate_shell(self, command: str) -> Verdict:
        for pattern in self._blocked:
            if pattern.search(command):
                return Verdict(Risk.BLOCKED, "esse comando está na lista de bloqueio permanente")

        if self.mode == "permissive":
            return Verdict(Risk.SAFE)

        if self.mode == "paranoid":
            return Verdict(Risk.CONFIRM, "roda um comando no sistema")

        for pattern, reason in _DESTRUCTIVE_SHELL:
            if re.search(pattern, command, re.IGNORECASE):
                return Verdict(Risk.CONFIRM, reason)

        return Verdict(Risk.SAFE)


_YES = {
    "sim", "pode", "confirmo", "isso", "manda", "vai", "ok", "claro", "confirma",
    "positivo", "autorizo", "yes", "beleza", "aham", "uhum", "bora", "certo",
}
_NO = {
    "não", "nao", "cancela", "para", "negativo", "esquece", "deixa", "cancelar",
    "no", "pare", "aborta", "peraí", "espera", "nada",
}


def interpret_confirmation(text: str) -> bool | None:
    """Interpreta a resposta falada. None = não deu pra entender."""
    words = re.findall(r"[\wáàâãéêíóôõúüç]+", text.lower())
    if not words:
        return None
    # Negação vence: "sim, mas não" é não.
    if any(w in _NO for w in words):
        return False
    if any(w in _YES for w in words):
        return True
    return None
