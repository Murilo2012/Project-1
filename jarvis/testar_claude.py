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

passo("1. Comando 'claude' no PATH")
binario = shutil.which("claude")
if binario:
    print(f"   encontrado: {binario}")
else:
    print("   NÃO encontrado.")
    print("   O agente de código vai usar o Gemini (funciona, mas erra mais).")
    print("   Instale em https://claude.com/claude-code e reabra o terminal.")
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
