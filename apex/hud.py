"""O HUD: uma tela, tudo que o APEX sabe.

ANSI puro, sem curses e sem dependência externa — funciona no Windows Terminal,
no PowerShell moderno e em qualquer terminal Linux. Redesenha a tela inteira a
cada ciclo em vez de posicionar cursor, o que é mais burro e muito mais estável
com saída concorrente.
"""

from __future__ import annotations

import os
import platform
import shutil
import threading
import time
from collections import deque
from datetime import datetime

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
HIDE_CURSOR = "\033[?25l"
SHOW_CURSOR = "\033[?25h"
CLEAR = "\033[2J\033[H"

ACCENTS = {
    "red": ("\033[38;5;196m", "\033[38;5;208m"),
    "green": ("\033[38;5;46m", "\033[38;5;226m"),
    "cyan": ("\033[38;5;51m", "\033[38;5;39m"),
    "violet": ("\033[38;5;135m", "\033[38;5;177m"),
}
GREY = "\033[38;5;244m"
WHITE = "\033[38;5;252m"

STATE_LABELS = {
    "idle": "OCIOSO",
    "listening": "OUVINDO",
    "thinking": "PENSANDO",
    "speaking": "FALANDO",
    "confirming": "CONFIRMANDO",
    "job": "TAREFA AGENDADA",
}


def enable_ansi_on_windows() -> None:
    """PowerShell antigo não interpreta ANSI sem isso."""
    if platform.system() != "Windows":
        return
    try:
        import ctypes  # noqa: PLC0415

        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    except Exception:  # noqa: BLE001 - se falhar, sai texto sem cor
        pass


class Hud:
    def __init__(self, name: str, config, vault, scheduler=None):
        self.name = name
        self.config = config
        self.vault = vault
        self.scheduler = scheduler
        self.accent, self.accent2 = ACCENTS.get(config.get("hud.accent", "red"), ACCENTS["red"])
        self.refresh_seconds = float(config.get("hud.refresh_seconds", 2))

        self.state = "idle"
        self.heard = ""
        self.said = ""
        self.noise_floor = 0.0
        self.activity: deque[tuple[str, str]] = deque(maxlen=8)
        self.tokens: dict[str, int] = {}
        self.started = time.time()

        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._enabled = bool(config.get("hud.enabled", True))

    # -- atualizações vindas do laço de voz --------------------------------

    def set_state(self, state: str) -> None:
        with self._lock:
            self.state = state
        self.render()

    def log(self, message: str) -> None:
        with self._lock:
            self.activity.append((datetime.now().strftime("%H:%M:%S"), message))
        self.render()

    def set_heard(self, text: str) -> None:
        with self._lock:
            self.heard = text
        self.render()

    def set_said(self, text: str) -> None:
        with self._lock:
            self.said = text
        self.render()

    # -- ciclo de vida -----------------------------------------------------

    def start(self) -> None:
        if not self._enabled:
            return
        enable_ansi_on_windows()
        print(HIDE_CURSOR, end="")
        self._thread = threading.Thread(target=self._loop, name="apex-hud", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._enabled:
            print(SHOW_CURSOR + RESET)

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.render()
            self._stop.wait(self.refresh_seconds)

    # -- desenho -----------------------------------------------------------

    def render(self) -> None:
        if not self._enabled:
            return
        try:
            width = min(shutil.get_terminal_size((100, 30)).columns, 110)
        except OSError:
            width = 100

        with self._lock:
            lines = self._compose(width)

        os.write(1, (CLEAR + "\n".join(lines) + RESET + "\n").encode("utf-8", "replace"))

    def _rule(self, width: int, label: str = "") -> str:
        if not label:
            return f"{GREY}{'─' * width}{RESET}"
        left = f"{GREY}── {self.accent}{label}{GREY} "
        pad = width - len(label) - 4
        return f"{left}{'─' * max(0, pad)}{RESET}"

    def _compose(self, width: int) -> list[str]:
        now = datetime.now()
        uptime = int(time.time() - self.started)
        state_label = STATE_LABELS.get(self.state, self.state.upper())

        header_left = f"{self.accent}{BOLD}{self.name}{RESET}{GREY} · copiloto{RESET}"
        header_right = f"{WHITE}{now.strftime('%H:%M:%S')}{RESET}{GREY} · {now.strftime('%d/%m')}{RESET}"
        pad = width - self._visible_len(header_left) - self._visible_len(header_right)
        lines = [f"{header_left}{' ' * max(1, pad)}{header_right}", self._rule(width)]

        # Estado, grandão, porque é o que se olha de longe.
        indicator = "●" if self.state != "idle" else "○"
        lines.append(f"  {self.accent2}{BOLD}{indicator} {state_label}{RESET}")
        lines.append("")

        # Últimas falas
        if self.heard:
            lines.append(f"  {GREY}você{RESET}  {WHITE}{self._clip(self.heard, width - 10)}{RESET}")
        if self.said:
            lines.append(f"  {GREY}apex{RESET}  {self.accent2}{self._clip(self.said, width - 10)}{RESET}")
        if self.heard or self.said:
            lines.append("")

        # Vitais
        lines.append(self._rule(width, "VITAIS"))
        lines.append("  " + "   ".join(self._vitals()))
        lines.append("")

        # Vault
        lines.append(self._rule(width, "VAULT"))
        stats = self.vault.stats()
        lines.append(
            f"  {GREY}raw{RESET} {WHITE}{stats['raw']}{RESET}   "
            f"{GREY}wiki{RESET} {WHITE}{stats['wiki']}{RESET}   "
            f"{GREY}outputs{RESET} {WHITE}{stats['outputs']}{RESET}   "
            f"{DIM}{self.vault.root}{RESET}"
        )
        lines.append("")

        # Agenda
        lines.append(self._rule(width, "AGENDA"))
        upcoming = self.scheduler.next_job() if self.scheduler else None
        if upcoming:
            job, when = upcoming
            delta = when - now
            hours = int(delta.total_seconds() // 3600)
            minutes = int((delta.total_seconds() % 3600) // 60)
            lines.append(
                f"  {self.accent}{when.strftime('%H:%M')}{RESET} {WHITE}{job.name}{RESET}"
                f"   {GREY}em {hours}h{minutes:02d}m{RESET}"
            )
        else:
            lines.append(f"  {GREY}nenhuma tarefa agendada{RESET}")
        lines.append("")

        # Atividade
        lines.append(self._rule(width, "ATIVIDADE"))
        if not self.activity:
            lines.append(f"  {GREY}aguardando{RESET}")
        for stamp, message in self.activity:
            lines.append(f"  {GREY}{stamp}{RESET}  {WHITE}{self._clip(message, width - 14)}{RESET}")

        # Rodapé
        lines.append("")
        lines.append(self._rule(width))
        tokens_in = self.tokens.get("input_tokens", 0) + self.tokens.get("cache_read_input_tokens", 0)
        tokens_out = self.tokens.get("output_tokens", 0)
        lines.append(
            f"  {DIM}ligado há {uptime // 3600}h{(uptime % 3600) // 60:02d}m · "
            f"ruído {self.noise_floor:.0f} dB · tokens {tokens_in}/{tokens_out} · "
            f"Ctrl+C encerra{RESET}"
        )
        return lines

    def _vitals(self) -> list[str]:
        try:
            import psutil  # noqa: PLC0415

            cpu = psutil.cpu_percent(interval=None)
            memory = psutil.virtual_memory().percent
            disk = psutil.disk_usage("C:\\" if platform.system() == "Windows" else "/").percent
        except Exception:  # noqa: BLE001
            return [f"{GREY}vitais indisponíveis{RESET}"]

        return [
            self._gauge("cpu", cpu),
            self._gauge("ram", memory),
            self._gauge("disco", disk),
        ]

    def _gauge(self, label: str, percent: float) -> str:
        filled = int(percent / 10)
        color = self.accent if percent > 85 else (self.accent2 if percent > 60 else WHITE)
        bar = f"{color}{'█' * filled}{GREY}{'░' * (10 - filled)}{RESET}"
        return f"{GREY}{label}{RESET} {bar} {color}{percent:>3.0f}%{RESET}"

    @staticmethod
    def _clip(text: str, limit: int) -> str:
        text = " ".join(text.split())
        return text if len(text) <= limit else text[: limit - 1] + "…"

    @staticmethod
    def _visible_len(text: str) -> int:
        """Comprimento ignorando os códigos de escape ANSI."""
        import re  # noqa: PLC0415

        return len(re.sub(r"\033\[[0-9;?]*[a-zA-Z]", "", text))
