"""Agendador: o que faz o APEX agir sozinho.

Isto é o que falta no desenho original do carrossel. Um HUD que mostra
"09:30 — briefing" é decoração se nada dispara aquilo. Aqui, dispara.

Roda numa thread, checa a cada 30 segundos, e garante que cada job roda no
máximo uma vez por dia por horário (senão o minuto inteiro dispararia várias
vezes).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Callable

DAY_KEYS = {
    0: "mon", 1: "tue", 2: "wed", 3: "thu", 4: "fri", 5: "sat", 6: "sun",
}
DAY_ALIASES = {
    "seg": "mon", "ter": "tue", "qua": "wed", "qui": "thu",
    "sex": "fri", "sab": "sat", "sáb": "sat", "dom": "sun",
}


@dataclass
class Job:
    name: str
    at: str
    prompt: str
    days: list[str] = field(default_factory=lambda: list(DAY_KEYS.values()))
    speak: bool = True
    last_run: date | None = None

    @property
    def hour_minute(self) -> tuple[int, int]:
        hour, _, minute = self.at.partition(":")
        return int(hour), int(minute or 0)

    def normalized_days(self) -> set[str]:
        return {DAY_ALIASES.get(d.lower(), d.lower()) for d in self.days}

    def due(self, now: datetime) -> bool:
        if self.last_run == now.date():
            return False
        if DAY_KEYS[now.weekday()] not in self.normalized_days():
            return False
        hour, minute = self.hour_minute
        # Janela de 2 minutos: se a máquina estava ocupada, ainda pega o job.
        now_minutes = now.hour * 60 + now.minute
        job_minutes = hour * 60 + minute
        return 0 <= now_minutes - job_minutes <= 2


class Scheduler:
    def __init__(
        self,
        jobs_config: list[dict],
        runner: Callable[[Job], None],
        on_status: Callable[[str], None] | None = None,
    ):
        self.jobs = [
            Job(
                name=j.get("name", f"job-{i}"),
                at=j.get("at", "09:00"),
                prompt=j.get("prompt", ""),
                days=j.get("days") or list(DAY_KEYS.values()),
                speak=j.get("speak", True),
            )
            for i, j in enumerate(jobs_config)
            if j.get("prompt")
        ]
        self.runner = runner
        self.on_status = on_status or (lambda _msg: None)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not self.jobs:
            return
        self._thread = threading.Thread(target=self._loop, name="apex-scheduler", daemon=True)
        self._thread.start()
        schedule = ", ".join(f"{j.at} {j.name}" for j in self.jobs)
        self.on_status(f"agendador ligado: {schedule}")

    def stop(self) -> None:
        self._stop.set()

    def next_job(self) -> tuple[Job, datetime] | None:
        """Próximo job a disparar. Usado pelo HUD."""
        now = datetime.now()
        best: tuple[Job, datetime] | None = None

        for job in self.jobs:
            hour, minute = job.hour_minute
            days = job.normalized_days()
            candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

            # Procura o próximo dia válido dentro de uma semana.
            for offset in range(8):
                attempt = candidate + timedelta(days=offset)
                if attempt > now and DAY_KEYS[attempt.weekday()] in days:
                    if best is None or attempt < best[1]:
                        best = (job, attempt)
                    break

        return best

    def _loop(self) -> None:
        while not self._stop.is_set():
            now = datetime.now()
            for job in self.jobs:
                if job.due(now):
                    job.last_run = now.date()
                    self.on_status(f"disparando job '{job.name}'")
                    try:
                        self.runner(job)
                    except Exception as exc:  # noqa: BLE001 - job ruim não derruba o daemon
                        self.on_status(f"job '{job.name}' falhou: {exc}")
            self._stop.wait(30)
