"""
Instalador do kit JARVIS ↔ Claude.

Aplica sobre uma instalação do Mark-L:
  1. core/prompt.txt em português
  2. claude_backend.py + patch no dev_agent.py e no code_helper.py
  3. jarvis_mcp_server.py na raiz

Uso, de dentro da pasta do Mark-L:

    python instalar.py                 # aplica tudo
    python instalar.py --só-portugues  # só o passo 1
    python instalar.py --desfazer      # restaura os backups

Todo arquivo alterado ganha um backup .bak-jarvis antes. Rodar duas vezes não
duplica nada — o instalador detecta o que já foi aplicado.
"""
from __future__ import annotations

import ast
import shutil
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent
BACKUP_SUFFIX = ".bak-jarvis"

# Substituto da fábrica do Gemini. O import fica dentro da função de propósito:
# no topo do arquivo, um claude_backend ausente derrubaria o módulo inteiro na
# importação, em vez de falhar só quando o agente de código for usado.
SUBSTITUTO = '''def {alias}(model_name: str = ""):
    """Motor de programação: Claude Code (instalado pelo kit JARVIS)."""
    import sys as _sys
    from pathlib import Path as _Path

    _raiz = str(_Path(__file__).resolve().parent.parent)
    if _raiz not in _sys.path:
        _sys.path.insert(0, _raiz)

    from claude_backend import get_model
    return get_model(model_name)
'''

# arquivo → nome da função-fábrica que será substituída
PATCH_TARGETS = {
    Path("actions") / "dev_agent.py": "_get_model",
    Path("actions") / "code_helper.py": "_get_gemini",
}

ok, warn, fail = [], [], []


def _find_root() -> Path:
    """A raiz do Mark-L é onde estão main.py e actions/."""
    for base in (Path.cwd(), KIT, KIT.parent):
        if (base / "main.py").is_file() and (base / "actions").is_dir():
            return base
    sys.exit(
        "Não encontrei o Mark-L.\n"
        "Rode este script de dentro da pasta que contém main.py e actions/."
    )


def _backup(path: Path) -> None:
    bak = path.with_suffix(path.suffix + BACKUP_SUFFIX)
    if not bak.exists():
        shutil.copy2(path, bak)


def _copiar(origem: Path, destino: Path) -> bool:
    """Copia, tolerando o caso de o kit já estar dentro da pasta do Mark-L.

    Devolve True se algo foi de fato copiado.
    """
    if origem.resolve() == destino.resolve():
        return False
    shutil.copy2(origem, destino)
    return True


# ── 1. Português ────────────────────────────────────────────────────────────

def instalar_portugues(root: Path) -> None:
    origem = KIT / "prompt-pt.txt"
    destino = root / "core" / "prompt.txt"

    if not origem.is_file():
        fail.append("prompt-pt.txt não está junto do instalador.")
        return
    if not destino.parent.is_dir():
        fail.append("core/ não existe — a instalação do Mark-L está incompleta.")
        return

    if destino.is_file():
        _backup(destino)
    _copiar(origem, destino)
    ok.append("core/prompt.txt agora está em português (backup em prompt.txt.bak-jarvis)")


# ── 2. Claude Code como motor de programação ────────────────────────────────

def _ler_preservando(arquivo: Path) -> tuple[str, str]:
    """Lê o arquivo sem traduzir quebras de linha.

    Os fontes do Mark-L são CRLF. Ler e escrever pelo caminho normal do Python
    converteria tudo para LF, e o patch de 10 linhas viraria um diff do arquivo
    inteiro. Devolve (conteúdo, quebra_de_linha_dominante).
    """
    with open(arquivo, "r", encoding="utf-8", newline="") as f:
        bruto = f.read()

    quebra = "\r\n" if bruto.count("\r\n") > bruto.count("\n") - bruto.count("\r\n") else "\n"
    return bruto, quebra


def _patch_factory(arquivo: Path, func_name: str) -> None:
    """Troca a função-fábrica do Gemini por um wrapper do claude_backend.

    Usa AST para achar as linhas exatas da função, em vez de casar texto —
    assim o patch sobrevive a mudanças de formatação no upstream.
    """
    fonte, quebra = _ler_preservando(arquivo)

    if "claude_backend" in fonte:
        warn.append(f"{arquivo.name} já estava com o patch — pulei.")
        return

    try:
        arvore = ast.parse(fonte)
    except SyntaxError as e:
        fail.append(f"{arquivo.name} não compila ({e}) — não mexi nele.")
        return

    alvo = next(
        (
            n for n in arvore.body
            if isinstance(n, ast.FunctionDef) and n.name == func_name
        ),
        None,
    )
    if alvo is None:
        fail.append(f"{arquivo.name}: função {func_name}() não encontrada — pulei.")
        return

    linhas = fonte.splitlines(keepends=True)
    inicio = alvo.lineno - 1              # ast conta a partir de 1
    fim = alvo.end_lineno                 # exclusivo depois do fatiamento

    substituto = SUBSTITUTO.format(alias=func_name)
    if quebra != "\n":
        substituto = substituto.replace("\n", quebra)

    _backup(arquivo)
    linhas[inicio:fim] = [substituto]
    with open(arquivo, "w", encoding="utf-8", newline="") as f:
        f.write("".join(linhas))

    # Só declaramos sucesso se o arquivo ainda for Python válido.
    try:
        ast.parse(_ler_preservando(arquivo)[0])
    except SyntaxError as e:
        shutil.copy2(arquivo.with_suffix(arquivo.suffix + BACKUP_SUFFIX), arquivo)
        fail.append(f"{arquivo.name}: patch quebrou a sintaxe ({e}) — revertido.")
        return

    ok.append(f"{arquivo.name}: {func_name}() agora usa o Claude Code")


def instalar_claude(root: Path) -> None:
    origem = KIT / "claude_backend.py"
    if not origem.is_file():
        fail.append("claude_backend.py não está junto do instalador.")
        return

    if _copiar(origem, root / "claude_backend.py"):
        ok.append("claude_backend.py copiado para a raiz")
    else:
        ok.append("claude_backend.py já estava na raiz")

    for rel, func in PATCH_TARGETS.items():
        arquivo = root / rel
        if arquivo.is_file():
            _patch_factory(arquivo, func)
        else:
            warn.append(f"{rel} não existe nesta versão — pulei.")

    if not shutil.which("claude"):
        warn.append(
            "O comando 'claude' não está no PATH. O patch está aplicado, mas só "
            "funciona depois de instalar o Claude Code."
        )


# ── 3. Servidor MCP ─────────────────────────────────────────────────────────

def instalar_mcp(root: Path) -> None:
    origem = KIT / "jarvis_mcp_server.py"
    if not origem.is_file():
        fail.append("jarvis_mcp_server.py não está junto do instalador.")
        return

    destino = root / "jarvis_mcp_server.py"
    if _copiar(origem, destino):
        ok.append("jarvis_mcp_server.py copiado para a raiz")
    else:
        ok.append("jarvis_mcp_server.py já estava na raiz")

    try:
        import mcp  # noqa: F401
    except ImportError:
        warn.append('Falta o pacote MCP. Rode: pip install "mcp[cli]"')

    print("\nPara registrar o servidor no Claude Code, rode:")
    print(f'    claude mcp add jarvis python "{destino}"\n')


# ── Desfazer ────────────────────────────────────────────────────────────────

def desfazer(root: Path) -> None:
    backups = list(root.rglob(f"*{BACKUP_SUFFIX}"))
    if not backups:
        print("Nenhum backup encontrado — nada a desfazer.")
        return

    for bak in backups:
        original = bak.with_suffix("")
        shutil.copy2(bak, original)
        bak.unlink()
        ok.append(f"{original.relative_to(root)} restaurado")

    for extra in ("claude_backend.py", "jarvis_mcp_server.py"):
        alvo = root / extra
        if alvo.is_file():
            alvo.unlink()
            ok.append(f"{extra} removido")


# ── Relatório ───────────────────────────────────────────────────────────────

def relatorio() -> int:
    print()
    for msg in ok:
        print(f"  [ok]     {msg}")
    for msg in warn:
        print(f"  [atenção] {msg}")
    for msg in fail:
        print(f"  [erro]   {msg}")

    print()
    if fail:
        print("Terminou com erros. Os backups .bak-jarvis estão intactos.")
        return 1
    print("Tudo aplicado. Rode 'python main.py' para testar.")
    return 0


def main() -> int:
    args = set(sys.argv[1:])
    root = _find_root()
    print(f"Mark-L encontrado em: {root}")

    if "--desfazer" in args:
        desfazer(root)
        return relatorio()

    instalar_portugues(root)
    if "--só-portugues" not in args and "--so-portugues" not in args:
        instalar_claude(root)
        instalar_mcp(root)

    return relatorio()


if __name__ == "__main__":
    sys.exit(main())
