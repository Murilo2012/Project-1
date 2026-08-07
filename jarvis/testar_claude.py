"""
Testa a ponte entre o JARVIS e o Claude Code, sem precisar falar com o assistente.

    python jarvis/testar_claude.py

Verifica, em ordem: se o comando claude existe, se ele responde a um prompt, e
se o dev_agent e o code_helper estão de fato roteados para cá. Falhar aqui é
muito mais rápido de diagnosticar do que falhar no meio de um comando de voz.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

falhas = 0


def passo(titulo: str) -> None:
    print(f"\n── {titulo} " + "─" * max(0, 52 - len(titulo)))


# ── 1. O binário existe? ────────────────────────────────────────────────────

def _procurar_instalado() -> list[Path]:
    """Locais onde o Claude Code costuma cair quando não está no PATH.

    Instalar não coloca o comando num terminal já aberto: o PATH é lido na
    abertura. Encontrar o binário aqui distingue "não instalado" de "instalado,
    terminal velho" — que exigem coisas bem diferentes do usuário.
    """
    import os

    nomes = ("claude.exe", "claude.cmd", "claude.ps1", "claude")
    pastas = [
        Path(os.environ.get("APPDATA", "")) / "npm",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "claude",
        Path(os.environ.get("LOCALAPPDATA", "")) / "claude",
        Path.home() / ".local" / "bin",
        Path.home() / ".claude" / "local",
        Path.home() / "AppData" / "Roaming" / "npm",
    ]

    achados = []
    for pasta in pastas:
        if not pasta or not pasta.is_dir():
            continue
        for nome in nomes:
            caminho = pasta / nome
            if caminho.is_file():
                achados.append(caminho)
    return achados


passo("1. Comando 'claude' no PATH")
binario = shutil.which("claude")
if binario:
    print(f"   encontrado: {binario}")
else:
    print("   NÃO está no PATH deste terminal.")
    instalado = _procurar_instalado()
    if instalado:
        print("   Mas ele ESTÁ instalado, aqui:")
        for caminho in instalado:
            print(f"      {caminho}")
        print("   O PATH só é lido quando o terminal abre — feche esta janela,")
        print("   abra outra e rode este teste de novo.")
    else:
        print("   E não achei instalação nos lugares habituais.")
        print("   Instale em https://claude.com/claude-code e reabra o terminal.")
    print("   Enquanto isso o agente de código usa o Gemini — funciona, erra mais.")
    falhas += 1

# ── 2. Ele responde? ────────────────────────────────────────────────────────

passo("2. O Claude responde a um prompt")
try:
    from claude_backend import get_model

    modelo = get_model()
    tipo = type(modelo).__name__
    print(f"   motor selecionado: {tipo}")

    resposta = modelo.generate_content(
        "Responda apenas com a palavra PONTE, sem mais nada."
    )
    texto = (resposta.text or "").strip()
    print(f"   resposta: {texto[:200]!r}")

    if "PONTE" in texto.upper():
        print("   ok — a ponte está funcionando.")
    elif texto.startswith("[claude]"):
        print("   FALHOU — o comando rodou mas devolveu erro.")
        print("   Se falar em autenticação, rode 'claude' sozinho uma vez e faça login.")
        falhas += 1
    else:
        print("   resposta inesperada, mas houve resposta. Provavelmente ok.")
except Exception as e:
    print(f"   ERRO: {type(e).__name__}: {e}")
    falhas += 1

# ── 3. Os módulos do JARVIS estão roteados? ─────────────────────────────────

passo("3. dev_agent e code_helper estão usando a ponte")
for modulo, funcao in (("dev_agent", "_get_model"), ("code_helper", "_get_gemini")):
    caminho = RAIZ / "actions" / f"{modulo}.py"
    if not caminho.is_file():
        print(f"   {modulo}: arquivo não existe")
        continue
    fonte = caminho.read_text(encoding="utf-8")
    if "claude_backend" in fonte:
        print(f"   {modulo}.{funcao}(): roteado")
    else:
        print(f"   {modulo}.{funcao}(): NÃO roteado — rode 'python jarvis/instalar.py'")
        falhas += 1

# ── Resultado ───────────────────────────────────────────────────────────────

print("\n" + "─" * 58)
if falhas:
    print(f"{falhas} problema(s). Veja as mensagens acima.")
else:
    print("Tudo certo. Peça ao JARVIS para criar um programa e ele vem para o Claude.")
sys.exit(1 if falhas else 0)
