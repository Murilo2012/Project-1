"""Controle do sistema: shell, programas, volume, energia."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys

from apex.tools.registry import ToolContext, boolean, integer, obj, string, tool

IS_WINDOWS = platform.system() == "Windows"
MAX_OUTPUT = 6000


def _shell_prefix() -> list[str]:
    if IS_WINDOWS:
        powershell = shutil.which("pwsh") or shutil.which("powershell") or "powershell"
        return [powershell, "-NoProfile", "-NonInteractive", "-Command"]
    return ["/bin/bash", "-lc"]


def _truncate(text: str, limit: int = MAX_OUTPUT) -> str:
    if len(text) <= limit:
        return text
    half = limit // 2
    return f"{text[:half]}\n\n[...saída cortada, {len(text) - limit} caracteres omitidos...]\n\n{text[-half:]}"


@tool(
    name="run_shell",
    description=(
        "Roda um comando no PowerShell (Windows) e devolve a saída. Use quando "
        "não houver uma ferramenta específica pra tarefa: consultar estado do "
        "sistema, manipular arquivos em lote, instalar coisa com winget, "
        "consultar processos. Comandos destrutivos passam por confirmação por "
        "voz automaticamente — não peça permissão você mesmo, só chame."
    ),
    schema=obj(
        {
            "command": string("O comando PowerShell a executar."),
            "timeout": integer("Tempo máximo em segundos. Padrão 60.", default=60),
            "working_dir": string("Pasta onde rodar. Padrão: pasta de trabalho do APEX."),
        },
        required=["command"],
    ),
)
def run_shell(ctx: ToolContext, command: str, timeout: int = 60, working_dir: str = "") -> str:
    cwd = working_dir or str(ctx.workspace)
    try:
        result = subprocess.run(
            [*_shell_prefix(), command],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        return f"O comando estourou o limite de {timeout}s e foi encerrado."

    parts = []
    if result.stdout.strip():
        parts.append(_truncate(result.stdout.strip()))
    if result.stderr.strip():
        parts.append(f"[stderr]\n{_truncate(result.stderr.strip(), 2000)}")
    if result.returncode != 0:
        parts.append(f"[código de saída: {result.returncode}]")
    return "\n\n".join(parts) if parts else "Comando executado. Sem saída."


@tool(
    name="open_app",
    description=(
        "Abre um programa, arquivo, pasta ou URL. Use pra 'abre o Spotify', "
        "'abre meus documentos', 'abre o YouTube'. Aceita nome de executável "
        "(spotify, notepad, chrome), caminho de arquivo ou URL completa. "
        "Prefira esta ferramenta a run_shell pra abrir coisas."
    ),
    schema=obj(
        {"target": string("Nome do programa, caminho ou URL.")},
        required=["target"],
    ),
)
def open_app(ctx: ToolContext, target: str) -> str:
    target = target.strip()
    if not IS_WINDOWS:
        opener = shutil.which("xdg-open") or shutil.which("open")
        if not opener:
            return "Sem comando de abertura disponível neste sistema."
        subprocess.Popen([opener, target])  # noqa: S603
        return f"Abri {target}."

    try:
        os.startfile(target)  # type: ignore[attr-defined]  # noqa: S606 - Windows
        return f"Abri {target}."
    except (OSError, FileNotFoundError):
        pass

    # Fallback: 'start' resolve nomes registrados no App Paths do Windows.
    result = subprocess.run(
        [*_shell_prefix(), f'Start-Process "{target}"'],
        capture_output=True, text=True, timeout=20, encoding="utf-8", errors="replace",
    )
    if result.returncode == 0:
        return f"Abri {target}."
    return f"Não consegui abrir '{target}'. {result.stderr.strip()[:300]}"


@tool(
    name="list_processes",
    description=(
        "Lista os processos em execução com uso de CPU e memória. Use quando o "
        "usuário perguntar o que está aberto, o que está pesando, ou antes de "
        "fechar um programa pra confirmar o nome certo do processo."
    ),
    schema=obj(
        {
            "filter": string("Filtra por parte do nome. Vazio lista os maiores."),
            "limit": integer("Quantos listar. Padrão 15.", default=15),
        }
    ),
)
def list_processes(ctx: ToolContext, filter: str = "", limit: int = 15) -> str:  # noqa: A002
    import psutil  # noqa: PLC0415

    rows = []
    for proc in psutil.process_iter(["pid", "name", "memory_info"]):
        try:
            info = proc.info
            name = info["name"] or "?"
            if filter and filter.lower() not in name.lower():
                continue
            memory_mb = (info["memory_info"].rss / 1_048_576) if info["memory_info"] else 0
            rows.append((memory_mb, info["pid"], name))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    rows.sort(reverse=True)
    if not rows:
        return f"Nenhum processo encontrado{f' com “{filter}”' if filter else ''}."

    lines = [f"{name} (pid {pid}) — {mb:.0f} MB" for mb, pid, name in rows[:limit]]
    return "\n".join(lines)


@tool(
    name="close_app",
    description=(
        "Fecha um programa pelo nome do processo. Passa por confirmação por voz "
        "porque pode haver trabalho não salvo. Se não tiver certeza do nome "
        "exato do processo, chame list_processes antes."
    ),
    schema=obj(
        {
            "process_name": string("Nome do processo, ex: 'notepad', 'chrome'."),
            "force": boolean("Força o encerramento sem esperar. Padrão false.", default=False),
        },
        required=["process_name"],
    ),
)
def close_app(ctx: ToolContext, process_name: str, force: bool = False) -> str:
    import psutil  # noqa: PLC0415

    needle = process_name.lower().removesuffix(".exe")
    closed = []
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            name = (proc.info["name"] or "").lower().removesuffix(".exe")
            if name != needle:
                continue
            proc.kill() if force else proc.terminate()
            closed.append(proc.info["pid"])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if not closed:
        return f"Nenhum processo chamado '{process_name}' estava rodando."
    return f"Fechei {len(closed)} processo(s) de '{process_name}'."


@tool(
    name="set_volume",
    description=(
        "Ajusta ou consulta o volume principal do Windows. Use pra 'aumenta o "
        "som', 'muta', 'coloca em 30 por cento'."
    ),
    schema=obj(
        {
            "level": integer("Volume de 0 a 100. Omita pra só consultar.", minimum=0, maximum=100),
            "mute": boolean("true muta, false desmuta. Omita pra não mexer."),
        }
    ),
)
def set_volume(ctx: ToolContext, level: int | None = None, mute: bool | None = None) -> str:
    if not IS_WINDOWS:
        return "Controle de volume só está implementado no Windows."
    try:
        from comtypes import CLSCTX_ALL  # noqa: PLC0415
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume  # noqa: PLC0415
    except ImportError:
        return "pycaw não está instalado. Rode: pip install pycaw comtypes"

    devices = AudioUtilities.GetSpeakers()
    interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    volume = interface.QueryInterface(IAudioEndpointVolume)

    if mute is not None:
        volume.SetMute(bool(mute), None)
    if level is not None:
        volume.SetMasterVolumeLevelScalar(max(0, min(100, level)) / 100.0, None)

    current = round(volume.GetMasterVolumeLevelScalar() * 100)
    muted = bool(volume.GetMute())
    return f"Volume em {current}%{', mutado' if muted else ''}."


@tool(
    name="media_control",
    description=(
        "Controla mídia (play/pause, próxima, anterior) via teclas de mídia. "
        "Funciona com Spotify, YouTube, qualquer player. Use pra 'pausa', "
        "'próxima música', 'volta'."
    ),
    schema=obj(
        {
            "action": {
                "type": "string",
                "enum": ["play_pause", "next", "previous", "stop"],
                "description": "A ação de mídia.",
            }
        },
        required=["action"],
    ),
)
def media_control(ctx: ToolContext, action: str) -> str:
    import pyautogui  # noqa: PLC0415

    keys = {
        "play_pause": "playpause",
        "next": "nexttrack",
        "previous": "prevtrack",
        "stop": "stop",
    }
    if action not in keys:
        return f"Ação de mídia inválida: {action}"
    pyautogui.press(keys[action])
    return f"Mídia: {action}."


@tool(
    name="system_status",
    description=(
        "Estado da máquina: CPU, memória, disco, bateria, uptime, rede. Use "
        "quando perguntarem como o PC está, se está pesado, quanto de espaço "
        "sobrou."
    ),
    schema=obj({}),
)
def system_status(ctx: ToolContext) -> str:
    import time  # noqa: PLC0415

    import psutil  # noqa: PLC0415

    memory = psutil.virtual_memory()
    disk = psutil.disk_usage("C:\\" if IS_WINDOWS else "/")
    uptime_hours = (time.time() - psutil.boot_time()) / 3600

    lines = [
        f"CPU: {psutil.cpu_percent(interval=0.4):.0f}%",
        f"Memória: {memory.percent:.0f}% ({memory.used / 1_073_741_824:.1f} de "
        f"{memory.total / 1_073_741_824:.1f} GB)",
        f"Disco: {disk.percent:.0f}% usado, {disk.free / 1_073_741_824:.0f} GB livres",
        f"Ligado há: {uptime_hours:.1f} horas",
        f"Python: {sys.version.split()[0]}",
    ]

    battery = getattr(psutil, "sensors_battery", lambda: None)()
    if battery is not None:
        plugged = "na tomada" if battery.power_plugged else "na bateria"
        lines.append(f"Bateria: {battery.percent:.0f}%, {plugged}")

    return "\n".join(lines)


@tool(
    name="shutdown_pc",
    description=(
        "Desliga, reinicia, suspende ou bloqueia o PC. Passa por confirmação "
        "por voz. Use só quando o usuário pedir explicitamente."
    ),
    schema=obj(
        {
            "action": {
                "type": "string",
                "enum": ["shutdown", "restart", "sleep", "lock"],
                "description": "O que fazer com a máquina.",
            },
            "delay_seconds": integer("Espera antes de agir. Padrão 10.", default=10),
        },
        required=["action"],
    ),
)
def shutdown_pc(ctx: ToolContext, action: str, delay_seconds: int = 10) -> str:
    if not IS_WINDOWS:
        return "Controle de energia só está implementado no Windows."

    commands = {
        "shutdown": f"shutdown /s /t {delay_seconds}",
        "restart": f"shutdown /r /t {delay_seconds}",
        "sleep": "rundll32.exe powrprof.dll,SetSuspendState 0,1,0",
        "lock": "rundll32.exe user32.dll,LockWorkStation",
    }
    if action not in commands:
        return f"Ação inválida: {action}"

    subprocess.Popen(commands[action], shell=True)  # noqa: S602 - comandos fixos
    if action in ("shutdown", "restart"):
        return f"{action} agendado pra daqui {delay_seconds}s. Pra cancelar: shutdown /a"
    return f"{action} executado."
