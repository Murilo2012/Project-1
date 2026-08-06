"""Consciência ambiente: a camada que faz o APEX falar primeiro.

Essa é a diferença entre a Alexa e o JARVIS. Repara nas falas do JARVIS no
filme — quase nenhuma responde a uma pergunta. "Sir, the suit's power is at
15%." Ele observa e decide interromper.

COMO FUNCIONA
Sensores baratos rodam em laço (bateria, disco, CPU, foco de janela, tempo
parado). Cada um pode emitir uma Observação. Uma política decide se aquilo
merece abrir a boca.

DUAS REGRAS QUE SUSTENTAM ISSO

1. Interromper é caro em atenção, não em token. Um assistente que fala a cada
   cinco minutos é mutado no primeiro dia. Por isso existe orçamento de
   interrupções por hora, horário de silêncio, cooldown por assunto, e
   detecção de tela cheia (jogo, chamada, apresentação — não interrompe).

2. A maioria das interrupções NÃO deve custar chamada de API. "Bateria em 15%"
   é uma frase pronta. Só sobe pro modelo o que exige julgamento, e mesmo
   assim só na prioridade alta.
"""

from __future__ import annotations

import platform
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

IS_WINDOWS = platform.system() == "Windows"

# Prioridades
LOW = 1      # só fala se estiver tudo calmo
MEDIUM = 2   # fala, respeitando orçamento e silêncio
HIGH = 3     # fura o silêncio e o orçamento (bateria acabando, disco cheio)


@dataclass
class Observation:
    key: str                 # id estável do assunto, usado no cooldown
    priority: int
    message: str             # frase pronta — custo zero
    prompt: str = ""         # se preenchido, o modelo compõe a fala (custa)
    cooldown: float = 3600.0  # segundos até poder falar do mesmo assunto


@dataclass
class SensorState:
    """Memória curta dos sensores, pra detectar mudança em vez de estado."""

    last_battery: float | None = None
    last_focus_title: str = ""
    focus_since: float = field(default_factory=time.monotonic)
    last_seen_active: float = field(default_factory=time.monotonic)
    high_cpu_since: float | None = None
    announced_focus_streak: bool = False


# --------------------------------------------------------------- SENSORES ---


def sensor_battery(state: SensorState, cfg: dict) -> Observation | None:
    try:
        import psutil  # noqa: PLC0415

        battery = getattr(psutil, "sensors_battery", lambda: None)()
    except Exception:  # noqa: BLE001
        return None
    if battery is None:
        return None

    percent = battery.percent
    previous = state.last_battery
    state.last_battery = percent

    if battery.power_plugged:
        return None

    critical = float(cfg.get("battery_critical", 10))
    low = float(cfg.get("battery_low", 20))

    # Só fala na travessia do limiar, não enquanto estiver abaixo dele.
    if previous is not None and previous > critical >= percent:
        return Observation(
            "bateria-critica", HIGH,
            f"Bateria em {percent:.0f} por cento. Liga na tomada agora.",
            cooldown=600,
        )
    if previous is not None and previous > low >= percent:
        return Observation(
            "bateria-baixa", MEDIUM,
            f"Bateria em {percent:.0f} por cento.",
            cooldown=1800,
        )
    return None


def sensor_disk(state: SensorState, cfg: dict) -> Observation | None:
    try:
        import psutil  # noqa: PLC0415

        disk = psutil.disk_usage("C:\\" if IS_WINDOWS else "/")
    except Exception:  # noqa: BLE001
        return None

    free_gb = disk.free / 1_073_741_824
    threshold = float(cfg.get("disk_free_gb", 10))
    if free_gb >= threshold:
        return None

    priority = HIGH if free_gb < threshold / 2 else MEDIUM
    return Observation(
        "disco-cheio", priority,
        f"Sobrou {free_gb:.0f} giga no disco. Tá apertado.",
        prompt=(
            "O disco está com pouco espaço livre. Descubra o que está ocupando "
            "mais espaço e me diga em UMA frase o que dá pra apagar. Não apague "
            "nada."
        ) if priority == HIGH else "",
        cooldown=21600,
    )


def sensor_cpu(state: SensorState, cfg: dict) -> Observation | None:
    """CPU alta e SUSTENTADA. Pico de dois segundos não é notícia."""
    try:
        import psutil  # noqa: PLC0415

        cpu = psutil.cpu_percent(interval=None)
    except Exception:  # noqa: BLE001
        return None

    threshold = float(cfg.get("cpu_percent", 92))
    sustained = float(cfg.get("cpu_sustained_seconds", 180))
    now = time.monotonic()

    if cpu < threshold:
        state.high_cpu_since = None
        return None

    if state.high_cpu_since is None:
        state.high_cpu_since = now
        return None

    if now - state.high_cpu_since < sustained:
        return None

    state.high_cpu_since = now  # reinicia, senão repete a cada ciclo
    return Observation(
        "cpu-alta", MEDIUM,
        "A CPU tá no talo faz uns minutos.",
        prompt=(
            "A CPU está acima de 90% há vários minutos. Veja qual processo está "
            "causando isso e me diga em UMA frase. Não feche nada."
        ),
        cooldown=1800,
    )


def sensor_focus_streak(state: SensorState, cfg: dict) -> Observation | None:
    """Tempo grudado na mesma janela. É o sensor mais 'JARVIS' de todos —
    ele nota o que você está fazendo, não só o que a máquina está fazendo."""
    if not IS_WINDOWS:
        return None
    try:
        import pygetwindow as gw  # noqa: PLC0415

        active = gw.getActiveWindow()
    except Exception:  # noqa: BLE001
        return None

    title = (active.title if active else "").strip()
    now = time.monotonic()

    if title != state.last_focus_title:
        state.last_focus_title = title
        state.focus_since = now
        state.announced_focus_streak = False
        return None

    limit = float(cfg.get("focus_streak_minutes", 90)) * 60
    if now - state.focus_since < limit or state.announced_focus_streak or not title:
        return None

    state.announced_focus_streak = True
    minutes = int((now - state.focus_since) / 60)
    return Observation(
        "foco-longo", LOW,
        f"Você tá há {minutes} minutos na mesma janela. Levanta um pouco.",
        cooldown=7200,
    )


def sensor_return(state: SensorState, cfg: dict) -> Observation | None:
    """Você sumiu e voltou. JARVIS sempre nota quando o Tony entra na sala."""
    now = time.monotonic()
    gap = now - state.last_seen_active
    state.last_seen_active = now

    away = float(cfg.get("away_minutes", 45)) * 60
    if gap < away:
        return None

    return Observation(
        "voltou", LOW,
        "De volta. Precisa de alguma coisa?",
        cooldown=1800,
    )


SENSORS: list[Callable[[SensorState, dict], Observation | None]] = [
    sensor_battery,
    sensor_disk,
    sensor_cpu,
    sensor_focus_streak,
    sensor_return,
]


# --------------------------------------------------------------- POLÍTICA ---


class InterruptPolicy:
    """Decide se vale abrir a boca. Existe pra ele não virar praga."""

    def __init__(self, cfg: dict):
        self.max_per_hour = int(cfg.get("max_interrupts_per_hour", 4))
        self.quiet_start = int(cfg.get("quiet_hours_start", 23))
        self.quiet_end = int(cfg.get("quiet_hours_end", 8))
        self.respect_fullscreen = bool(cfg.get("respect_fullscreen", True))
        self._history: list[float] = []
        self._cooldowns: dict[str, float] = {}

    def in_quiet_hours(self, now: datetime | None = None) -> bool:
        hour = (now or datetime.now()).hour
        if self.quiet_start == self.quiet_end:
            return False
        if self.quiet_start < self.quiet_end:
            return self.quiet_start <= hour < self.quiet_end
        return hour >= self.quiet_start or hour < self.quiet_end  # cruza a meia-noite

    def is_fullscreen(self) -> bool:
        """Jogo, chamada de vídeo, apresentação. Não se interrompe isso."""
        if not (IS_WINDOWS and self.respect_fullscreen):
            return False
        try:
            import pyautogui  # noqa: PLC0415
            import pygetwindow as gw  # noqa: PLC0415

            active = gw.getActiveWindow()
            if active is None:
                return False
            screen_width, screen_height = pyautogui.size()
            return active.width >= screen_width and active.height >= screen_height
        except Exception:  # noqa: BLE001
            return False

    def allows(self, observation: Observation, now: float | None = None) -> tuple[bool, str]:
        now = now if now is not None else time.monotonic()

        until = self._cooldowns.get(observation.key)
        if until is not None and now < until:
            return False, "em cooldown"

        if observation.priority >= HIGH:
            return True, ""  # urgência fura tudo

        if self.in_quiet_hours():
            return False, "horário de silêncio"

        if self.is_fullscreen():
            return False, "tela cheia"

        self._history = [t for t in self._history if now - t < 3600]
        if len(self._history) >= self.max_per_hour:
            return False, "orçamento de interrupções esgotado"

        return True, ""

    def record(self, observation: Observation, now: float | None = None) -> None:
        now = now if now is not None else time.monotonic()
        self._history.append(now)
        self._cooldowns[observation.key] = now + observation.cooldown


# ------------------------------------------------------------ CONSCIÊNCIA ---


class Awareness:
    """Laço de vigilância. Roda em thread, cutuca quando vale a pena."""

    def __init__(
        self,
        cfg: dict,
        speak: Callable[[str], None],
        think: Callable[[str], str] | None = None,
        on_status: Callable[[str], None] | None = None,
        is_busy: Callable[[], bool] | None = None,
    ):
        self.cfg = cfg or {}
        self.enabled = bool(self.cfg.get("enabled", True))
        self.interval = float(self.cfg.get("check_interval_seconds", 30))
        self.speak = speak
        # think: manda o assunto pro modelo compor a fala. Custa dinheiro,
        # então só é usado quando o sensor pede explicitamente.
        self.think = think
        self.on_status = on_status or (lambda _msg: None)
        self.is_busy = is_busy or (lambda: False)

        self.state = SensorState()
        self.policy = InterruptPolicy(self.cfg)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not self.enabled:
            return
        self._thread = threading.Thread(target=self._loop, name="apex-awareness", daemon=True)
        self._thread.start()
        self.on_status(
            f"consciência ligada: até {self.policy.max_per_hour} interrupções/hora, "
            f"silêncio das {self.policy.quiet_start}h às {self.policy.quiet_end}h"
        )

    def stop(self) -> None:
        self._stop.set()

    def poll_once(self) -> list[Observation]:
        """Roda todos os sensores. Separado do laço pra dar pra testar."""
        observations = []
        for sensor in SENSORS:
            try:
                observation = sensor(self.state, self.cfg)
            except Exception as exc:  # noqa: BLE001 - sensor ruim não derruba o laço
                self.on_status(f"sensor {sensor.__name__} falhou: {exc}")
                continue
            if observation is not None:
                observations.append(observation)
        return observations

    def _loop(self) -> None:
        # Deixa a máquina assentar antes de começar a observar, senão o pico de
        # CPU do próprio carregamento dos modelos vira a primeira notícia.
        self._stop.wait(60)

        while not self._stop.is_set():
            if not self.is_busy():
                for observation in sorted(
                    self.poll_once(), key=lambda o: o.priority, reverse=True
                ):
                    allowed, reason = self.policy.allows(observation)
                    if not allowed:
                        self.on_status(f"segurei “{observation.key}”: {reason}")
                        continue

                    self.policy.record(observation)
                    self._deliver(observation)
                    break  # uma interrupção por ciclo. Nunca duas seguidas.

            self._stop.wait(self.interval)

    def _deliver(self, observation: Observation) -> None:
        self.on_status(f"interrompendo: {observation.key}")

        if observation.prompt and self.think is not None:
            try:
                composed = self.think(observation.prompt)
                if composed.strip():
                    self.speak(composed)
                    return
            except Exception as exc:  # noqa: BLE001
                self.on_status(f"não consegui compor a fala: {exc}")

        self.speak(observation.message)
