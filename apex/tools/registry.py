"""Registro de ferramentas.

Cada ferramenta declara nome, descrição e schema JSON, e recebe um contexto com
o vault e a config. O retorno pode ser:
  - str  — vira um tool_result de texto
  - list — blocos de conteúdo crus (usado pelo screenshot, que devolve imagem)

Descrições prescritivas de propósito: dizer *quando* chamar, não só o que faz.
Isso muda de verdade a taxa de acerto na escolha da ferramenta.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


@dataclass
class ToolContext:
    config: Any
    vault: Any
    workspace: Path
    skills_dir: Path
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass
class Tool:
    name: str
    description: str
    schema: dict
    fn: Callable[..., Any]

    def to_api(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.schema,
        }


REGISTRY: dict[str, Tool] = {}


def tool(name: str, description: str, schema: dict) -> Callable:
    def decorator(fn: Callable) -> Callable:
        REGISTRY[name] = Tool(name=name, description=description, schema=schema, fn=fn)
        return fn

    return decorator


def obj(properties: dict, required: list[str] | None = None) -> dict:
    """Atalho pra montar um schema de objeto."""
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
    }


def string(description: str, **extra) -> dict:
    return {"type": "string", "description": description, **extra}


def integer(description: str, **extra) -> dict:
    return {"type": "integer", "description": description, **extra}


def boolean(description: str, default: bool | None = None) -> dict:
    schema: dict = {"type": "boolean", "description": description}
    if default is not None:
        schema["default"] = default
    return schema


def all_tools() -> list[dict]:
    """Definições no formato da API, em ordem estável (importa pro cache)."""
    return [REGISTRY[name].to_api() for name in sorted(REGISTRY)]


def execute(name: str, tool_input: dict, ctx: ToolContext) -> Any:
    if name not in REGISTRY:
        return f"Erro: ferramenta desconhecida '{name}'."
    try:
        return REGISTRY[name].fn(ctx, **tool_input)
    except TypeError as exc:
        return f"Erro: argumentos inválidos para {name}: {exc}"
    except Exception as exc:  # noqa: BLE001 - o erro precisa voltar pro modelo
        return f"Erro ao executar {name}: {type(exc).__name__}: {exc}"
