"""
Coleta o estado da máquina para calibrar a migração do JARVIS para o Ollama.

    python diagnostico.py

Copie a saída inteira e cole na conversa. Ela responde de uma vez: qual modelo
do Ollama recomendar, se a voz offline é viável e o que ainda falta instalar.

Só lê — não instala nem altera nada.
"""
from __future__ import annotations

import platform
import shutil
import subprocess
import sys


def titulo(txt: str) -> None:
    print(f"\n── {txt} " + "─" * max(0, 58 - len(txt)))


def rodar(cmd: list[str], timeout: int = 20) -> str | None:
    """Executa um comando e devolve a saída, ou None se não der."""
    if not shutil.which(cmd[0]):
        return None
    try:
        p = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
        )
        return (p.stdout or p.stderr or "").strip()
    except Exception as e:
        return f"(falhou: {e})"


# ── Sistema ─────────────────────────────────────────────────────────────────

titulo("Sistema")
print(f"SO       : {platform.system()} {platform.release()} ({platform.machine()})")
print(f"Python   : {sys.version.split()[0]}")

if sys.version_info[:2] not in ((3, 11), (3, 12)):
    print("  ATENÇÃO: o Mark-L pede Python 3.11 ou 3.12.")

# ── Memória e CPU ───────────────────────────────────────────────────────────

titulo("Memória e CPU")
try:
    import psutil
    ram = psutil.virtual_memory()
    print(f"RAM      : {ram.total / 1e9:.1f} GB total, {ram.available / 1e9:.1f} GB livre")
    print(f"CPU      : {psutil.cpu_count(logical=False)} núcleos físicos, "
          f"{psutil.cpu_count()} lógicos")
except ImportError:
    print("psutil não instalado (vem com o Mark-L: pip install psutil)")

# ── GPU ─────────────────────────────────────────────────────────────────────

titulo("GPU")
gpu = rodar([
    "nvidia-smi",
    "--query-gpu=name,memory.total,driver_version",
    "--format=csv,noheader",
])
if gpu:
    print(f"NVIDIA   : {gpu}")
else:
    print("nvidia-smi não encontrado.")
    if platform.system() == "Windows":
        saida = rodar(["wmic", "path", "win32_VideoController", "get", "name"])
        if saida:
            print("Placas detectadas:")
            for linha in saida.splitlines()[1:]:
                if linha.strip():
                    print(f"  {linha.strip()}")
    print("Sem GPU NVIDIA, o Ollama roda em CPU — bem mais devagar.")

# ── Ollama ──────────────────────────────────────────────────────────────────

titulo("Ollama")
versao = rodar(["ollama", "--version"])
if versao:
    print(f"Versão   : {versao}")
    modelos = rodar(["ollama", "list"], timeout=30)
    print("\nModelos instalados:")
    print(modelos if modelos else "  (nenhum)")
else:
    print("Ollama não encontrado no PATH. Instale em https://ollama.com")

# ── Claude Code ─────────────────────────────────────────────────────────────

titulo("Claude Code")
claude = rodar(["claude", "--version"])
print(f"Versão   : {claude}" if claude
      else "Comando 'claude' não encontrado — é ele que destrava o kit inteiro.")

# ── Pacotes ─────────────────────────────────────────────────────────────────

titulo("Pacotes Python")
for pacote, para_que in [
    ("PyQt6",           "interface (HUD)"),
    ("sounddevice",     "áudio"),
    ("google.genai",    "cérebro atual (Gemini)"),
    ("mcp",             "servidor MCP"),
    ("faster_whisper",  "voz offline (fase 2)"),
    ("psutil",          "telemetria"),
]:
    try:
        __import__(pacote)
        print(f"  ok     {pacote:<16} {para_que}")
    except ImportError:
        print(f"  falta  {pacote:<16} {para_que}")

print("\n" + "─" * 62)
print("Copie tudo acima e cole na conversa.")
