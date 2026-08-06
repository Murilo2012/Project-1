"""Arquivos: ler, escrever, listar, procurar, mover, apagar."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from apex.tools.registry import ToolContext, boolean, integer, obj, string, tool

MAX_READ_CHARS = 20000
BINARY_SUFFIXES = {
    ".exe", ".dll", ".zip", ".rar", ".7z", ".png", ".jpg", ".jpeg", ".gif",
    ".mp3", ".mp4", ".mkv", ".avi", ".pdf", ".docx", ".xlsx", ".pptx", ".onnx",
}


def _expand(path: str) -> Path:
    return Path(os.path.expandvars(str(path))).expanduser()


@tool(
    name="read_file",
    description=(
        "Lê o conteúdo de um arquivo de texto do PC. Use quando o usuário "
        "pedir pra você olhar, resumir ou trabalhar em cima de um arquivo. "
        "Não funciona em binários (exe, zip, imagem) — pra imagem use "
        "look_at_screen ou peça pro usuário abrir."
    ),
    schema=obj(
        {
            "path": string("Caminho do arquivo. Aceita ~ e variáveis do Windows."),
            "max_chars": integer("Máximo de caracteres. Padrão 20000.", default=MAX_READ_CHARS),
        },
        required=["path"],
    ),
)
def read_file(ctx: ToolContext, path: str, max_chars: int = MAX_READ_CHARS) -> str:
    target = _expand(path)
    if not target.exists():
        return f"Arquivo não existe: {target}"
    if target.is_dir():
        return f"{target} é uma pasta. Use list_dir."
    if target.suffix.lower() in BINARY_SUFFIXES:
        size_mb = target.stat().st_size / 1_048_576
        return f"{target.name} é binário ({size_mb:.1f} MB). Não dá pra ler como texto."

    content = target.read_text(encoding="utf-8", errors="replace")
    if len(content) > max_chars:
        return content[:max_chars] + f"\n\n[...cortado, o arquivo tem {len(content)} caracteres...]"
    return content or "[arquivo vazio]"


@tool(
    name="write_file",
    description=(
        "Escreve ou anexa texto num arquivo do PC. Cria as pastas do caminho se "
        "não existirem. Use pra salvar relatórios, anotações e scripts que o "
        "usuário pediu. Para memória do APEX, prefira vault_write."
    ),
    schema=obj(
        {
            "path": string("Caminho do arquivo a escrever."),
            "content": string("O conteúdo."),
            "append": boolean("true anexa no fim em vez de sobrescrever.", default=False),
        },
        required=["path", "content"],
    ),
)
def write_file(ctx: ToolContext, path: str, content: str, append: bool = False) -> str:
    target = _expand(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    with target.open(mode, encoding="utf-8") as handle:
        handle.write(content if content.endswith("\n") else content + "\n")
    verb = "Anexei em" if append else "Escrevi"
    return f"{verb} {target} ({len(content)} caracteres)."


@tool(
    name="list_dir",
    description=(
        "Lista o conteúdo de uma pasta, com tamanho e data. Use antes de mexer "
        "em arquivos, pra saber o que tem lá."
    ),
    schema=obj(
        {
            "path": string("Caminho da pasta. Padrão: pasta de trabalho."),
            "limit": integer("Máximo de itens. Padrão 50.", default=50),
        }
    ),
)
def list_dir(ctx: ToolContext, path: str = "", limit: int = 50) -> str:
    target = _expand(path) if path else ctx.workspace
    if not target.exists():
        return f"Pasta não existe: {target}"
    if not target.is_dir():
        return f"{target} não é uma pasta."

    entries = sorted(
        target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())
    )
    if not entries:
        return f"{target} está vazia."

    lines = []
    for entry in entries[:limit]:
        try:
            stat = entry.stat()
        except OSError:
            continue
        if entry.is_dir():
            lines.append(f"[pasta] {entry.name}")
        else:
            size = stat.st_size
            unit = f"{size / 1_048_576:.1f} MB" if size > 1_048_576 else f"{size / 1024:.0f} KB"
            lines.append(f"        {entry.name}  ({unit})")

    header = f"{target}  —  {len(entries)} itens"
    if len(entries) > limit:
        header += f" (mostrando {limit})"
    return header + "\n" + "\n".join(lines)


@tool(
    name="search_files",
    description=(
        "Procura arquivos por nome dentro de uma pasta, recursivamente. Use "
        "quando o usuário souber o nome mas não o lugar: 'acha meu currículo', "
        "'onde tá aquele contrato'."
    ),
    schema=obj(
        {
            "pattern": string("Parte do nome ou glob, ex: '*.pdf', 'curriculo'."),
            "root": string("Onde procurar. Padrão: pasta do usuário."),
            "limit": integer("Máximo de resultados. Padrão 25.", default=25),
        },
        required=["pattern"],
    ),
)
def search_files(ctx: ToolContext, pattern: str, root: str = "", limit: int = 25) -> str:
    base = _expand(root) if root else Path.home()
    if not base.exists():
        return f"Pasta não existe: {base}"

    glob_pattern = pattern if any(c in pattern for c in "*?[") else f"*{pattern}*"
    skip = {"AppData", "node_modules", ".git", "Windows", "$Recycle.Bin", "venv", "__pycache__"}

    found: list[Path] = []
    for candidate in base.rglob(glob_pattern):
        if any(part in skip for part in candidate.parts):
            continue
        found.append(candidate)
        if len(found) >= limit:
            break

    if not found:
        return f"Nada encontrado com '{pattern}' em {base}."
    return f"{len(found)} resultado(s):\n" + "\n".join(str(p) for p in found)


@tool(
    name="move_path",
    description="Move ou renomeia um arquivo ou pasta.",
    schema=obj(
        {
            "source": string("Caminho de origem."),
            "destination": string("Caminho de destino."),
        },
        required=["source", "destination"],
    ),
)
def move_path(ctx: ToolContext, source: str, destination: str) -> str:
    src, dst = _expand(source), _expand(destination)
    if not src.exists():
        return f"Origem não existe: {src}"
    if dst.exists():
        return f"O destino já existe: {dst}. Escolha outro nome."
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    return f"Movi {src.name} para {dst}."


@tool(
    name="delete_path",
    description=(
        "Apaga um arquivo ou pasta. Passa por confirmação por voz. Por padrão "
        "manda pra Lixeira em vez de apagar de vez — sempre prefira assim."
    ),
    schema=obj(
        {
            "path": string("O que apagar."),
            "permanent": boolean(
                "true apaga de vez (sem Lixeira). Use só se pedirem.", default=False
            ),
        },
        required=["path"],
    ),
)
def delete_path(ctx: ToolContext, path: str, permanent: bool = False) -> str:
    target = _expand(path)
    if not target.exists():
        return f"Não existe: {target}"

    if not permanent:
        try:
            from send2trash import send2trash  # noqa: PLC0415

            send2trash(str(target))
            return f"Mandei {target.name} pra Lixeira. Dá pra recuperar."
        except ImportError:
            pass  # sem send2trash, cai pro caminho permanente com aviso

    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()
    suffix = "" if permanent else " (send2trash não instalado, foi permanente)"
    return f"Apaguei {target.name} de vez{suffix}."
