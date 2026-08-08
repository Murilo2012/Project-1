"""
Cria na área de trabalho um atalho que abre o Claude Code já na pasta do JARVIS,
retomando a última conversa.

    python jarvis/atalho_claude.py
    python jarvis/atalho_claude.py --nome "Claude Jarvis"
    python jarvis/atalho_claude.py --remover

Por que existe: retomar o trabalho exige entrar na pasta certa e lembrar da
flag de continuação. Digitar isso toda vez é onde os comandos se perdem — um
clique não erra.

O .bat gerado tenta `claude --continue` (retoma a última conversa daquela
pasta) e, se não houver nenhuma, cai para `claude --resume`, que lista as
conversas para escolher.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from criar_atalho import area_de_trabalho  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent

MODELO = """@echo off
title JARVIS - Claude Code
cd /d "{raiz}"

echo  Pasta : %CD%
echo  Abrindo o Claude Code e retomando a ultima conversa...
echo.

call claude --continue
if errorlevel 1 (
    echo.
    echo  Nao havia conversa para retomar. Escolha uma da lista:
    echo.
    call claude --resume
)

echo.
pause
"""


def main() -> int:
    p = argparse.ArgumentParser(description="Atalho para o Claude Code no JARVIS.")
    p.add_argument("--nome", default="JARVIS Claude", help='Padrão: "JARVIS Claude"')
    p.add_argument("--remover", action="store_true")
    args = p.parse_args()

    if not (RAIZ / "main.py").is_file():
        print(f"main.py não encontrado em {RAIZ}.")
        print("Rode este script de dentro da pasta do Mark-L.")
        return 1

    mesa = area_de_trabalho()
    mesa.mkdir(parents=True, exist_ok=True)
    destino = mesa / f"{args.nome}.bat"

    if args.remover:
        if destino.exists():
            destino.unlink()
            print(f"Atalho removido: {destino.name}")
        else:
            print(f"Não havia atalho em {destino}")
        return 0

    # newline="\r\n": o cmd do Windows precisa de CRLF para ler o .bat direito.
    with open(destino, "w", encoding="utf-8", newline="\r\n") as f:
        f.write(MODELO.format(raiz=RAIZ))

    print(f"Pasta do JARVIS : {RAIZ}")
    print(f"Área de trabalho: {mesa}")
    print(f"\nAtalho criado: {destino.name}")
    print("Clique duas vezes nele para voltar ao Claude Code de onde parou.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
