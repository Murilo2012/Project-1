"""
Cria um atalho do JARVIS na área de trabalho, sem precisar abrir a interface.

    python jarvis/criar_atalho.py
    python jarvis/criar_atalho.py --nome "JARVIS PT"
    python jarvis/criar_atalho.py --remover

Por que existe, se a interface já tem o botão "CREATE DESKTOP SHORTCUT":
aquele botão grava sempre o nome "J.A.R.V.I.S", que é o mesmo do atalho de uma
instalação anterior — e sobrescreve o antigo. Aqui o nome é escolhido, então as
duas versões podem conviver na área de trabalho.

O atalho aponta para o pythonw.exe (Windows), que roda sem abrir janela preta
de terminal, com o diretório de trabalho fixado nesta pasta.
"""
from __future__ import annotations

import argparse
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
MAIN = RAIZ / "main.py"
ICONE = RAIZ / "config" / "jarvis.ico"


# ── Descobrir a área de trabalho ────────────────────────────────────────────

def area_de_trabalho() -> Path:
    """A pasta real da área de trabalho.

    No Windows, ~/Desktop erra quando o OneDrive assumiu a pasta (muito comum)
    ou quando o sistema está em português e a pasta se chama "Área de Trabalho".
    O caminho canônico vem do próprio Windows.
    """
    if platform.system() == "Windows":
        try:
            import ctypes
            from ctypes import windll, wintypes

            # FOLDERID_Desktop {B4BFCC3A-DB2C-424C-B029-7FE99A87C641}
            class GUID(ctypes.Structure):
                _fields_ = [
                    ("Data1", wintypes.DWORD),
                    ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD),
                    ("Data4", ctypes.c_byte * 8),
                ]

            folderid = GUID(
                0xB4BFCC3A, 0xDB2C, 0x424C,
                (ctypes.c_byte * 8)(0xB0, 0x29, 0x7F, 0xE9, 0x9A, 0x87, 0xC6, 0x41),
            )
            caminho = ctypes.c_wchar_p()
            if windll.shell32.SHGetKnownFolderPath(
                ctypes.byref(folderid), 0, None, ctypes.byref(caminho)
            ) == 0:
                return Path(caminho.value)
        except Exception:
            pass

        try:
            import winreg
            chave = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders",
            )
            valor, _ = winreg.QueryValueEx(chave, "Desktop")
            return Path(os.path.expandvars(valor))
        except Exception:
            pass

    for candidata in (Path.home() / "Desktop", Path.home() / "Área de Trabalho"):
        if candidata.is_dir():
            return candidata
    return Path.home() / "Desktop"


# ── Windows ─────────────────────────────────────────────────────────────────

def _criar_windows(destino: Path) -> None:
    python = Path(sys.executable)
    pythonw = python.parent / "pythonw.exe"     # roda sem console
    alvo = str(pythonw if pythonw.exists() else python)
    icone = str(ICONE) if ICONE.exists() else f"{alvo},0"

    try:
        from win32com.client import Dispatch  # type: ignore
        atalho = Dispatch("WScript.Shell").CreateShortCut(str(destino))
        atalho.TargetPath = alvo
        atalho.Arguments = f'"{MAIN}"'
        atalho.WorkingDirectory = str(RAIZ)
        atalho.Description = "JARVIS — Mark-L"
        atalho.IconLocation = icone
        atalho.save()
        return
    except ImportError:
        pass

    # Sem pywin32: VBScript via wscript.exe, que não abre janela.
    vbs = "\n".join([
        'Set ws = CreateObject("WScript.Shell")',
        f'Set sc = ws.CreateShortcut("{destino}")',
        f'sc.TargetPath = "{alvo}"',
        f'sc.Arguments = Chr(34) & "{MAIN}" & Chr(34)',
        f'sc.WorkingDirectory = "{RAIZ}"',
        'sc.Description = "JARVIS - Mark-L"',
        f'sc.IconLocation = "{icone}"',
        'sc.Save',
    ])
    fd, tmp = tempfile.mkstemp(suffix=".vbs")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(vbs)
        subprocess.run(["wscript.exe", "/nologo", tmp], timeout=15)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


# ── Linux ───────────────────────────────────────────────────────────────────

def _criar_linux(destino: Path, nome: str) -> None:
    destino.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={nome}\n"
        f"Exec={sys.executable} {MAIN}\n"
        f"Path={RAIZ}\n"
        f"Icon={ICONE}\n"
        "Terminal=false\n",
        encoding="utf-8",
    )
    destino.chmod(0o755)


# ── macOS ───────────────────────────────────────────────────────────────────

def _criar_macos(destino: Path) -> None:
    binarios = destino / "Contents" / "MacOS"
    binarios.mkdir(parents=True, exist_ok=True)
    executavel = binarios / "jarvis"
    executavel.write_text(
        "#!/bin/bash\n"
        f'cd "{RAIZ}"\n'
        f'exec "{sys.executable}" "{MAIN}"\n',
        encoding="utf-8",
    )
    executavel.chmod(0o755)


# ── Principal ───────────────────────────────────────────────────────────────

def caminho_do_atalho(nome: str) -> Path:
    mesa = area_de_trabalho()
    sufixo = {"Windows": ".lnk", "Linux": ".desktop", "Darwin": ".app"}
    return mesa / f"{nome}{sufixo.get(platform.system(), '')}"


def main() -> int:
    p = argparse.ArgumentParser(description="Cria o atalho do JARVIS.")
    p.add_argument("--nome", default="JARVIS PT",
                   help='Nome do atalho (padrão: "JARVIS PT")')
    p.add_argument("--remover", action="store_true", help="Apaga o atalho.")
    args = p.parse_args()

    if not MAIN.is_file():
        print(f"main.py não encontrado em {RAIZ}.")
        print("Rode este script de dentro da pasta do Mark-L.")
        return 1

    destino = caminho_do_atalho(args.nome)

    if args.remover:
        if destino.exists():
            import shutil
            shutil.rmtree(destino) if destino.is_dir() else destino.unlink()
            print(f"Atalho removido: {destino}")
        else:
            print(f"Não havia atalho em {destino}")
        return 0

    print(f"Pasta do JARVIS : {RAIZ}")
    print(f"Área de trabalho: {destino.parent}")

    # Em instalações traduzidas ou recém-criadas a pasta pode não existir.
    destino.parent.mkdir(parents=True, exist_ok=True)

    sistema = platform.system()
    try:
        if sistema == "Windows":
            _criar_windows(destino)
        elif sistema == "Darwin":
            _criar_macos(destino)
        else:
            _criar_linux(destino, args.nome)
    except Exception as e:
        print(f"\nNão consegui criar o atalho: {e}")
        return 1

    if destino.exists():
        print(f"\nAtalho criado: {destino.name}")
        print("Ele abre esta versão do JARVIS, sem janela de terminal.")
        return 0

    print("\nO comando rodou, mas o atalho não apareceu.")
    print("No Windows, tente: pip install pywin32")
    return 1


if __name__ == "__main__":
    sys.exit(main())
