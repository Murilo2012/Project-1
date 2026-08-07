"""
Lista os modelos Gemini que a SUA chave consegue usar.

    python jarvis/modelos.py

O código do Mark-L pede gemini-2.5-flash em 12 lugares, e o Google tirou esse
modelo do ar para chaves novas — daí o erro 404 "no longer available to new
users" que aparece no log ao buscar notícias. Este script pergunta à API quais
modelos a sua chave realmente enxerga, em vez de adivinharmos um nome.

Só lê — não altera nada. Não imprime a sua chave.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CONFIG = RAIZ / "config" / "api_keys.json"


def main() -> int:
    if not CONFIG.is_file():
        print(f"Não achei {CONFIG}.")
        return 1

    try:
        chave = json.loads(CONFIG.read_text(encoding="utf-8"))["gemini_api_key"]
    except Exception as e:
        print(f"Não consegui ler a chave: {e}")
        return 1

    try:
        from google import genai
    except ImportError:
        print("Falta o pacote: pip install google-genai")
        return 1

    print("Consultando a API do Gemini...\n")
    try:
        modelos = list(genai.Client(api_key=chave).models.list())
    except Exception as e:
        print(f"A consulta falhou: {e}")
        return 1

    gera, ao_vivo, outros = [], [], []
    for m in modelos:
        nome = (m.name or "").replace("models/", "")
        acoes = set(getattr(m, "supported_actions", None) or [])
        if "bidiGenerateContent" in acoes:
            ao_vivo.append(nome)
        elif "generateContent" in acoes:
            gera.append(nome)
        else:
            outros.append(nome)

    def bloco(titulo: str, itens: list[str], nota: str = "") -> None:
        print(f"── {titulo} ({len(itens)}) " + "─" * max(0, 40 - len(titulo)))
        if nota:
            print(f"   {nota}")
        for nome in sorted(itens):
            print(f"   {nome}")
        print()

    bloco("Texto / geração", gera, "candidatos para substituir gemini-2.5-flash")
    bloco("Áudio ao vivo", ao_vivo, "usados pela voz do JARVIS (LIVE_MODEL)")
    if outros:
        bloco("Outros", outros)

    print("─" * 62)
    print("Cole a saída na conversa para escolhermos o substituto certo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
