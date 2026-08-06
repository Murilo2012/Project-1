"""Captura de microfone: calibração de ruído, VAD por energia e detecção de palmas.

Um único stream de áudio alimenta tudo. Blocos de 30ms entram numa fila e são
consumidos por uma máquina de estados:

    OCIOSO ──(voz detectada)──> GRAVANDO ──(silêncio)──> devolve o áudio
       └────(duas palmas)─────> dispara o gatilho de palma

Não uso webrtcvad de propósito: é extensão em C e instalar no Windows dá dor de
cabeça. VAD por energia com piso de ruído adaptativo resolve bem em ambiente
doméstico, que é o caso de uso.
"""

from __future__ import annotations

import math
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass, field

import numpy as np

try:
    import sounddevice as sd
except (ImportError, OSError) as exc:  # pragma: no cover - sem PortAudio no sistema
    raise RuntimeError(
        "Não consegui carregar o sounddevice/PortAudio. No Windows costuma bastar "
        "'pip install sounddevice'. No Linux: 'apt install libportaudio2'. "
        "Pra rodar sem microfone, use: python -m apex --texto"
    ) from exc


def dbfs(block: np.ndarray) -> float:
    """Nível do bloco em dBFS. -inf vira -120 pra não estourar contas."""
    rms = float(np.sqrt(np.mean(np.square(block, dtype=np.float64))))
    if rms < 1e-9:
        return -120.0
    return 20.0 * math.log10(rms)


@dataclass
class ClapConfig:
    enabled: bool = True
    count: int = 2
    min_interval: float = 0.12
    max_interval: float = 0.9
    threshold_db_above_noise: float = 22.0
    min_seconds_between_triggers: float = 2.0
    # Uma palma decai rápido; fala se sustenta. Esse é o teste que separa os dois.
    decay_window: float = 0.20
    decay_db_above_noise: float = 9.0


@dataclass
class ClapDetector:
    config: ClapConfig
    noise_floor: float = -60.0
    _peaks: deque[float] = field(default_factory=lambda: deque(maxlen=8))
    _pending: float | None = None
    _pending_decayed: bool = False
    # -inf, não 0: com 0 o primeiro disparo seria engolido pelo cooldown nos
    # dois primeiros segundos de vida do processo.
    _last_trigger: float = float("-inf")
    _refractory_until: float = 0.0

    def feed(self, level_db: float, now: float) -> bool:
        """Alimenta um bloco. Devolve True quando o padrão de palmas fecha."""
        if not self.config.enabled:
            return False

        loud = level_db > self.noise_floor + self.config.threshold_db_above_noise
        quiet = level_db < self.noise_floor + self.config.decay_db_above_noise

        # Candidata em avaliação: confirmamos só se o som sumir rápido.
        if self._pending is not None:
            elapsed = now - self._pending
            if quiet:
                self._pending_decayed = True
            if elapsed >= self.config.decay_window:
                if self._pending_decayed:
                    self._peaks.append(self._pending)
                self._pending = None
                self._pending_decayed = False

        if loud and self._pending is None and now >= self._refractory_until:
            self._pending = now
            self._pending_decayed = False
            self._refractory_until = now + self.config.min_interval

        return self._check_pattern(now)

    def _check_pattern(self, now: float) -> bool:
        needed = self.config.count
        if len(self._peaks) < needed:
            return False
        if now - self._last_trigger < self.config.min_seconds_between_triggers:
            return False

        recent = list(self._peaks)[-needed:]
        for earlier, later in zip(recent, recent[1:]):
            gap = later - earlier
            if not (self.config.min_interval <= gap <= self.config.max_interval):
                return False

        # A última palma precisa ser recente, senão é eco de um padrão antigo.
        if now - recent[-1] > self.config.max_interval + 0.3:
            return False

        self._peaks.clear()
        self._last_trigger = now
        return True


class Microphone:
    """Stream contínuo do microfone com VAD e detector de palmas acoplados."""

    def __init__(self, audio_config: dict, clap_config: dict | None = None):
        self.sample_rate = int(audio_config.get("sample_rate", 16000))
        self.block_ms = int(audio_config.get("block_ms", 30))
        self.block_size = max(1, int(self.sample_rate * self.block_ms / 1000))
        self.device = audio_config.get("input_device")

        self.silence_threshold_db = float(audio_config.get("silence_threshold_db", -38.0))
        self.silence_duration = float(audio_config.get("silence_duration", 0.9))
        self.min_speech_duration = float(audio_config.get("min_speech_duration", 0.35))
        self.max_recording_duration = float(audio_config.get("max_recording_duration", 25.0))
        self.calibration_seconds = float(audio_config.get("calibration_seconds", 2.0))
        self.pre_roll_seconds = float(audio_config.get("pre_roll_seconds", 0.4))

        clap_cfg = ClapConfig(**{
            k: v for k, v in (clap_config or {}).items()
            if k in ClapConfig.__dataclass_fields__
        })
        self.clap = ClapDetector(clap_cfg)

        self.noise_floor = -60.0
        self._queue: queue.Queue[np.ndarray] = queue.Queue()
        self._stream: sd.InputStream | None = None
        self._paused = threading.Event()
        pre_roll_blocks = max(1, int(self.pre_roll_seconds * 1000 / self.block_ms))
        self._pre_roll: deque[np.ndarray] = deque(maxlen=pre_roll_blocks)

    # -- ciclo de vida ----------------------------------------------------

    def _callback(self, indata, _frames, _time_info, status):  # pragma: no cover
        if status:
            pass  # overflow de buffer é comum e não fatal; ignoramos
        self._queue.put(indata[:, 0].copy())

    def start(self) -> None:
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            blocksize=self.block_size,
            device=self.device,
            channels=1,
            dtype="float32",
            callback=self._callback,
        )
        self._stream.start()
        self.calibrate()

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def __enter__(self) -> "Microphone":
        self.start()
        return self

    def __exit__(self, *_exc) -> None:
        self.stop()

    # -- silenciar durante a própria fala ---------------------------------

    def pause(self) -> None:
        """Ignora o áudio de entrada — usado enquanto o APEX está falando,
        pra ele não se ouvir e se auto-ativar."""
        self._paused.set()

    def resume(self) -> None:
        self._drain()
        self._paused.clear()

    def _drain(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                return

    # -- calibração -------------------------------------------------------

    def calibrate(self) -> float:
        """Mede o piso de ruído do ambiente. Chame com o ambiente em silêncio."""
        levels: list[float] = []
        deadline = time.monotonic() + self.calibration_seconds
        while time.monotonic() < deadline:
            try:
                block = self._queue.get(timeout=0.5)
            except queue.Empty:
                break
            levels.append(dbfs(block))

        if levels:
            levels.sort()
            # Mediana em vez de média: um estalo isolado não sobe o piso.
            self.noise_floor = levels[len(levels) // 2]
        self.clap.noise_floor = self.noise_floor

        # O limiar de voz acompanha o ambiente, com um mínimo de segurança.
        adaptive = self.noise_floor + 12.0
        self.silence_threshold_db = max(self.silence_threshold_db, adaptive)
        return self.noise_floor

    # -- consumo ----------------------------------------------------------

    def blocks(self, timeout: float = 0.5):
        """Gera blocos de áudio. Já atualiza o detector de palmas."""
        while True:
            try:
                block = self._queue.get(timeout=timeout)
            except queue.Empty:
                yield None, None, False
                continue

            if self._paused.is_set():
                continue

            now = time.monotonic()
            level = dbfs(block)
            clapped = self.clap.feed(level, now)
            self._pre_roll.append(block)
            yield block, level, clapped

    def events(self):
        """Fluxo único de eventos do microfone.

        Existe um só consumidor do stream, então palma e fala precisam sair do
        mesmo laço — senão gravar uma frase engoliria as palmas daquele período.

        Emite:
            ("clap", None)          duas palmas detectadas
            ("utterance", ndarray)  alguém falou e parou de falar
            ("idle", None)          nada acontecendo (deixa o chamador respirar)
        """
        collected: list[np.ndarray] = []
        speaking = False
        silence_started: float | None = None

        for block, level, clapped in self.blocks(timeout=0.5):
            now = time.monotonic()

            if clapped and not speaking:
                collected.clear()
                yield "clap", None
                continue

            if block is None:
                if not speaking:
                    yield "idle", None
                continue

            is_speech = level > self.silence_threshold_db

            if not speaking:
                if is_speech:
                    speaking = True
                    silence_started = None
                    collected = list(self._pre_roll)
                else:
                    yield "idle", None
                continue

            collected.append(block)

            duration = len(collected) * self.block_size / self.sample_rate
            finished = False

            if is_speech:
                silence_started = None
            elif silence_started is None:
                silence_started = now
            elif now - silence_started >= self.silence_duration:
                finished = True

            if duration >= self.max_recording_duration:
                finished = True

            if finished:
                audio = np.concatenate(collected) if collected else None
                speaking = False
                silence_started = None
                collected = []
                if audio is not None and len(audio) / self.sample_rate >= self.min_speech_duration:
                    yield "utterance", audio

    def record_utterance(self, timeout: float = 8.0) -> np.ndarray | None:
        """Espera alguém falar e grava até o silêncio. None se ninguém falou.

        Inclui o pre-roll: os ~400ms antes do gatilho, senão a primeira sílaba
        é cortada e o Whisper transcreve 'pex' em vez de 'Apex'.
        """
        started = time.monotonic()
        collected: list[np.ndarray] = []
        speaking = False
        silence_started: float | None = None

        for block, level, _clapped in self.blocks(timeout=0.5):
            now = time.monotonic()

            if block is None:
                if not speaking and now - started > timeout:
                    return None
                continue

            is_speech = level > self.silence_threshold_db

            if not speaking:
                if now - started > timeout:
                    return None
                if is_speech:
                    speaking = True
                    collected.extend(self._pre_roll)
                    silence_started = None
                continue

            collected.append(block)

            if is_speech:
                silence_started = None
            elif silence_started is None:
                silence_started = now
            elif now - silence_started >= self.silence_duration:
                break

            duration = len(collected) * self.block_size / self.sample_rate
            if duration >= self.max_recording_duration:
                break

        if not collected:
            return None

        audio = np.concatenate(collected)
        duration = len(audio) / self.sample_rate
        if duration < self.min_speech_duration:
            return None
        return audio
