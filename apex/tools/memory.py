"""Memória e skills: o vault de markdown e a pasta de SKILL.md."""

from __future__ import annotations

from apex.tools.registry import ToolContext, boolean, obj, string, tool


@tool(
    name="vault_search",
    description=(
        "Procura no vault — a memória de longo prazo do APEX. SEMPRE chame "
        "isto antes de dizer que não sabe algo sobre o usuário, os projetos "
        "dele, decisões passadas ou preferências. A resposta pode já estar "
        "gravada."
    ),
    schema=obj(
        {"query": string("O que procurar. Palavras-chave funcionam melhor que frases.")},
        required=["query"],
    ),
)
def vault_search(ctx: ToolContext, query: str) -> str:
    hits = ctx.vault.search(query)
    if not hits:
        return f"Nada no vault sobre '{query}'."
    lines = [f"{len(hits)} resultado(s) pra '{query}':", ""]
    for hit in hits:
        lines.append(f"[{hit.path}] {hit.title}")
        lines.append(f"    {hit.excerpt}")
    return "\n".join(lines)


@tool(
    name="vault_read",
    description=(
        "Lê uma nota do vault pelo caminho relativo, ex: 'wiki/projetos.md'. "
        "Use depois de vault_search, quando o trecho não bastar."
    ),
    schema=obj(
        {"path": string("Caminho relativo dentro do vault.")},
        required=["path"],
    ),
)
def vault_read(ctx: ToolContext, path: str) -> str:
    try:
        return ctx.vault.read(path)
    except (FileNotFoundError, ValueError) as exc:
        return f"Erro: {exc}"


@tool(
    name="vault_write",
    description=(
        "Escreve uma nota no vault. Use 'wiki/' pra conhecimento que vale reter "
        "(preferências do usuário, decisões, fatos sobre a vida dele) e "
        "'outputs/' pra entregas (relatórios, planos, resumos). Grave na wiki "
        "sem o usuário pedir, sempre que ele contar algo que vale lembrar entre "
        "conversas. Use links [[assim]] pra ligar notas."
    ),
    schema=obj(
        {
            "path": string("Caminho relativo, ex: 'wiki/preferencias.md'."),
            "content": string("O conteúdo em markdown. Comece com um título '# '."),
            "append": boolean("true anexa no fim em vez de sobrescrever.", default=False),
        },
        required=["path", "content"],
    ),
)
def vault_write(ctx: ToolContext, path: str, content: str, append: bool = False) -> str:
    try:
        written = ctx.vault.write(path, content, append=append)
    except ValueError as exc:
        return f"Erro: {exc}"
    verb = "Anexei em" if append else "Gravei"
    return f"{verb} {written}."


@tool(
    name="vault_capture",
    description=(
        "Joga algo cru no inbox do vault (raw/), com data e hora. Use pra "
        "capturar rápido: uma ideia solta, um recado, algo que o usuário mandou "
        "anotar. Captura primeiro, organiza depois — a destilação pra wiki "
        "acontece na revisão."
    ),
    schema=obj(
        {
            "text": string("O que capturar."),
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Tags opcionais pra achar depois.",
            },
        },
        required=["text"],
    ),
)
def vault_capture(ctx: ToolContext, text: str, tags: list[str] | None = None) -> str:
    return f"Capturei em {ctx.vault.capture(text, tags=tags)}."


@tool(
    name="vault_list",
    description=(
        "Lista as notas do vault, mais recentes primeiro. Passe 'wiki', 'raw' "
        "ou 'outputs' pra filtrar por seção."
    ),
    schema=obj({"section": string("Seção: 'wiki', 'raw', 'outputs', ou vazio pra tudo.")}),
)
def vault_list(ctx: ToolContext, section: str = "") -> str:
    notes = ctx.vault.list_notes(section)
    if not notes:
        return f"Nada em {section or 'no vault'}."
    return f"{len(notes)} nota(s):\n" + "\n".join(notes)


@tool(
    name="list_skills",
    description=(
        "Lista as skills disponíveis com a descrição de cada uma. Chame no "
        "começo de uma tarefa que pareça um procedimento repetido (briefing, "
        "revisão do dia, planejamento) — pode já existir uma skill pra isso."
    ),
    schema=obj({}),
)
def list_skills(ctx: ToolContext) -> str:
    skills_dir = ctx.skills_dir
    if not skills_dir.exists():
        return "Nenhuma pasta de skills configurada."

    entries = []
    for skill_file in sorted(skills_dir.glob("*/SKILL.md")):
        name = skill_file.parent.name
        description = ""
        for line in skill_file.read_text(encoding="utf-8-sig").splitlines():
            stripped = line.strip()
            if stripped.lower().startswith("descricao:") or stripped.lower().startswith("descrição:"):
                description = stripped.split(":", 1)[1].strip()
                break
        entries.append(f"{name} — {description or 'sem descrição'}")

    if not entries:
        return "Nenhuma skill instalada em skills/."
    return "Skills disponíveis:\n" + "\n".join(entries)


@tool(
    name="read_skill",
    description=(
        "Lê o SKILL.md de uma skill e carrega o procedimento dela. Depois de "
        "ler, SIGA o que está escrito ali — a skill é a instrução, não uma "
        "sugestão."
    ),
    schema=obj(
        {"name": string("Nome da skill, ex: 'briefing'.")},
        required=["name"],
    ),
)
def read_skill(ctx: ToolContext, name: str) -> str:
    safe = name.strip().strip("/\\").replace("..", "")
    skill_file = ctx.skills_dir / safe / "SKILL.md"
    if not skill_file.exists():
        return f"Skill '{name}' não existe. Use list_skills pra ver as disponíveis."
    return skill_file.read_text(encoding="utf-8-sig")
