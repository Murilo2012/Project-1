"""
Servidor MCP que expõe as ações do Mark-L (JARVIS) como ferramentas do Claude Code.

Depois de registrado, o Claude passa a conseguir abrir aplicativos, ler a
telemetria da máquina, mexer em arquivos e controlar volume/brilho — usando os
módulos que já existem em actions/.

Registro:
    claude mcp add jarvis python C:\\caminho\\para\\jarvis_mcp_server.py

Requisitos:
    pip install "mcp[cli]"

Configuração:
    Defina JARVIS_HOME apontando para a pasta do Mark-L, ou deixe este arquivo
    dentro dela.

Escopo deliberado: nada que apague arquivos, desligue ou reinicie a máquina é
exposto aqui. Essas funções existem em actions/ e continuam disponíveis por voz
no JARVIS — só não ficam ao alcance de uma chamada de ferramenta automática.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# O pacote mcp renomeou FastMCP para MCPServer e mudou o caminho na versão 2.0.
# A API usada aqui — construtor, decorador .tool(), .run() — é idêntica nas
# duas, então aceitamos ambas em vez de amarrar o kit a uma versão do pacote.
try:
    from mcp.server import MCPServer as _Servidor        # mcp >= 2.0
except ImportError:                                      # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Servidor

# ── Localizar a instalação do Mark-L ────────────────────────────────────────
JARVIS_HOME = Path(os.environ.get("JARVIS_HOME", Path(__file__).resolve().parent))

if not (JARVIS_HOME / "actions").is_dir():
    sys.exit(
        f"actions/ não encontrado em {JARVIS_HOME}.\n"
        "Defina JARVIS_HOME com o caminho da pasta do Mark-L."
    )

sys.path.insert(0, str(JARVIS_HOME))

mcp = _Servidor("jarvis")


def _lazy(module: str, attr: str):
    """Importa sob demanda — um módulo quebrado não derruba o servidor inteiro."""
    import importlib
    return getattr(importlib.import_module(f"actions.{module}"), attr)


# ── Aplicativos ─────────────────────────────────────────────────────────────

@mcp.tool()
def open_app(app_name: str) -> str:
    """Abre um aplicativo pelo nome (ex.: 'spotify', 'vscode', 'chrome')."""
    return _lazy("open_app", "open_app")(parameters={"app_name": app_name})


# ── Telemetria ──────────────────────────────────────────────────────────────

@mcp.tool()
def system_status() -> dict:
    """Uso atual de CPU, RAM, GPU e temperatura da máquina."""
    return _lazy("system_monitor", "get_system_status")()


# ── Arquivos (somente leitura) ──────────────────────────────────────────────

@mcp.tool()
def list_files(path: str = "desktop", show_hidden: bool = False) -> str:
    """Lista os arquivos de uma pasta. Aceita atalhos: desktop, downloads,
    documents, pictures, music, videos — ou um caminho absoluto."""
    return _lazy("file_controller", "list_files")(path=path, show_hidden=show_hidden)


@mcp.tool()
def read_file(path: str, name: str = "", max_chars: int = 4000) -> str:
    """Lê o conteúdo de um arquivo de texto da máquina."""
    return _lazy("file_controller", "read_file")(path=path, name=name, max_chars=max_chars)


@mcp.tool()
def find_files(name: str = "", extension: str = "") -> str:
    """Procura arquivos por nome ou extensão nas pastas do usuário."""
    return _lazy("file_controller", "find_files")(name=name, extension=extension)


# ── Controles do sistema ────────────────────────────────────────────────────

@mcp.tool()
def set_volume(level: int) -> str:
    """Define o volume do sistema (0 a 100)."""
    if not 0 <= level <= 100:
        return "O volume precisa estar entre 0 e 100."
    _lazy("computer_settings", "volume_set")(level)
    return f"Volume ajustado para {level}."


@mcp.tool()
def computer_action(action: str, value: str = "") -> str:
    """Executa uma ação do sistema pelo dispatcher do JARVIS.

    Exemplos de action: brightness_up, minimize_window, snap_left, new_tab,
    show_desktop, take_screenshot, dark_mode, toggle_wifi.
    """
    params: dict = {"action": action}
    if value:
        params["value"] = value
    return _lazy("computer_settings", "computer_settings")(parameters=params)


# ── Busca ───────────────────────────────────────────────────────────────────

@mcp.tool()
def web_search(query: str, mode: str = "search") -> str:
    """Busca na web pelo motor do JARVIS.

    mode: search | news | research | price | compare
    """
    return _lazy("web_search", "web_search")(parameters={"query": query, "mode": mode})


if __name__ == "__main__":
    mcp.run()
