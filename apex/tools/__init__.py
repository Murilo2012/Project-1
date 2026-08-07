"""Ferramentas do APEX.

Importar este pacote registra tudo no REGISTRY. A ordem dos imports não importa
— all_tools() ordena por nome, o que mantém o prompt cache estável.
"""

from apex.tools import desktop, files, memory, system  # noqa: F401
from apex.tools.registry import REGISTRY, ToolContext, all_tools, execute

__all__ = ["REGISTRY", "ToolContext", "all_tools", "execute"]
