"""
Temas prontos para o JARVIS.

    python jarvis/temas.py                    lista os temas, com amostra de cor
    python jarvis/temas.py homem-de-ferro     aplica um tema
    python jarvis/temas.py --atual            mostra o que está em uso

A interface já sabe derivar a paleta inteira a partir de uma cor de destaque
(apply_ui_accent em ui.py) e lê "ui_color" do config ao abrir. Este script só
grava a escolha — e reproduz a mesma matemática de derivação para mostrar como
o tema vai ficar antes de você abrir o JARVIS.

As cores de estado (verde de ok, vermelho de alerta) não entram na derivação,
de propósito: um alerta precisa continuar parecendo um alerta em qualquer tema.
"""
from __future__ import annotations

import colorsys
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CONFIG = RAIZ / "config" / "api_keys.json"

# Paleta original do Mark-L, base de toda derivação.
BASE = {
    "BG": "#00060a", "PANEL": "#010d14", "PANEL2": "#010f18",
    "BORDER": "#0d3347", "BORDER_B": "#1a5c7a", "BORDER_A": "#0f4060",
    "PRI": "#00d4ff", "PRI_DIM": "#007a99", "PRI_GHO": "#001f2e",
    "TEXT": "#8ffcff", "TEXT_DIM": "#3a8a9a", "TEXT_MED": "#5ab8cc",
    "WHITE": "#d8f8ff", "DARK": "#000d14", "BAR_BG": "#011520",
}

# accent  = cor de destaque, de onde a paleta inteira é derivada
# acc/acc2 = realces (barras, avisos); sem eles, ficam os originais laranja/amarelo
TEMAS: dict[str, dict] = {
    "homem-de-ferro": {
        "accent": "#ff2b2b", "acc": "#ffb400", "acc2": "#ffd966",
        "desc": "Vermelho com realces dourados — o JARVIS do filme",
    },
    "ciano": {
        "accent": "#00d4ff",
        "desc": "O original do Mark-L, azul-ciano de HUD",
    },
    "matrix": {
        "accent": "#00ff66", "acc": "#88ff00", "acc2": "#ccff33",
        "desc": "Verde de terminal, alto contraste",
    },
    "roxo-neon": {
        "accent": "#b44dff", "acc": "#ff00aa", "acc2": "#ff66cc",
        "desc": "Roxo com rosa neon",
    },
    "ambar": {
        "accent": "#ffaa00", "acc": "#ff7700", "acc2": "#ffdd55",
        "desc": "Âmbar de monitor antigo, quente e sóbrio",
    },
    # Abaixo de 8% de saturação a derivação dessatura a paleta inteira; este
    # accent fica de propósito logo abaixo desse limiar, senão o tema sai azul.
    "gelo": {
        "accent": "#d0d8e0", "acc": "#5aa0d0", "acc2": "#88c0e0",
        "desc": "Cinza dessaturado, discreto",
    },
}


# ── Derivação (mesma lógica de apply_ui_accent, para o preview bater) ────────

def _hsv(h: str) -> tuple[float, float, float]:
    return colorsys.rgb_to_hsv(
        int(h[1:3], 16) / 255, int(h[3:5], 16) / 255, int(h[5:7], 16) / 255
    )


def derivar(accent: str) -> dict[str, str]:
    """Desloca o matiz da paleta base até o accent, mantendo as proporções."""
    base_h = _hsv(BASE["PRI"])[0]
    acc_h, acc_s, _ = _hsv(accent)
    dh = acc_h - base_h
    cinza = acc_s < 0.08          # accent quase sem cor → tema dessaturado

    saida = {}
    for chave, hex0 in BASE.items():
        h, s, v = _hsv(hex0)
        if cinza:
            s *= 0.15
        r, g, b = colorsys.hsv_to_rgb((h + dh) % 1.0, s, v)
        saida[chave] = "#{:02x}{:02x}{:02x}".format(
            int(r * 255 + 0.5), int(g * 255 + 0.5), int(b * 255 + 0.5)
        )
    return saida


def _bloco(hexcor: str, largura: int = 4) -> str:
    """Um retângulo colorido no terminal, via cor de fundo ANSI de 24 bits."""
    r, g, b = (int(hexcor[i:i + 2], 16) for i in (1, 3, 5))
    return f"\033[48;2;{r};{g};{b}m{' ' * largura}\033[0m"


def _amostra(tema: dict) -> str:
    p = derivar(tema["accent"])
    cores = [p["BG"], p["PANEL"], p["BORDER_B"], p["PRI"], p["TEXT"], p["WHITE"]]
    cores += [tema.get("acc", "#ff6b00"), tema.get("acc2", "#ffcc00")]
    return "".join(_bloco(c) for c in cores)


# ── Config ──────────────────────────────────────────────────────────────────

def _ler() -> dict:
    if not CONFIG.is_file():
        return {}
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return {}


def aplicar(nome: str) -> int:
    tema = TEMAS.get(nome)
    if not tema:
        print(f"Tema '{nome}' não existe. Veja os disponíveis com: python jarvis/temas.py")
        return 1

    if not CONFIG.is_file():
        print(f"{CONFIG} não existe — configure o JARVIS primeiro.")
        return 1

    dados = _ler()
    dados["ui_color"] = tema["accent"]
    if "acc" in tema:
        dados["ui_accent"] = tema["acc"]
    if "acc2" in tema:
        dados["ui_accent2"] = tema["acc2"]
    dados["ui_theme"] = nome

    CONFIG.write_text(json.dumps(dados, indent=4), encoding="utf-8")

    print(f"Tema aplicado: {nome}")
    print(f"  {tema['desc']}")
    print(f"  {_amostra(tema)}")
    print("\nFeche e abra o JARVIS para ver.")
    return 0


def listar() -> int:
    atual = _ler().get("ui_theme", "")
    print("Temas disponíveis:\n")
    for nome, tema in TEMAS.items():
        marca = " (em uso)" if nome == atual else ""
        print(f"  {_amostra(tema)}  {nome}{marca}")
        print(f"  {'':17}{tema['desc']}\n")
    print("Aplicar:  python jarvis/temas.py <nome>")
    return 0


def main() -> int:
    args = [a for a in sys.argv[1:] if a]

    if not args:
        return listar()
    if args[0] in ("--atual", "-a"):
        cfg = _ler()
        print(f"tema : {cfg.get('ui_theme', '(nenhum — usando o padrão)')}")
        print(f"cor  : {cfg.get('ui_color', BASE['PRI'])}")
        return 0
    return aplicar(args[0].strip().lower())


if __name__ == "__main__":
    sys.exit(main())
