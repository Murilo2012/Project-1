"""Fala em fluxo: o que faz a diferença entre assistente de voz e JARVIS.

O PROBLEMA
O caminho ingênuo é: modelo gera a resposta inteira → sintetiza → toca. Numa
frase de duas linhas isso dá 3 a 6 segundos de silêncio antes do primeiro som.
O JARVIS do filme responde no ato, e é essa a diferença que se sente.

A SOLUÇÃO, EM DOIS ANDARES
1. Corte por pontuação com folga. O texto que sai do modelo entra num buffer
   que solta pedaços faláveis assim que fecha uma frase — ou uma vírgula, se já
   houver texto suficiente pra soar natural. Cortar no meio de uma oração deixa
   a prosódia picada; cortar só no ponto final desperdiça o tempo todo.
2. Esteira de dois estágios. Enquanto o pedaço N toca, o N+1 já está sendo
   sintetizado. Sem isso, cada pedaço paga o custo de síntese em silêncio.

Medido na literatura: corte por pontuação com folga leva o tempo até o primeiro
som de 1,8-2,5s para ~1,25s. É a diferença entre esperar e conversar.

INTERROMPER
Falar por cima dele tem que funcionar. `stop()` corta o som na hora e limpa as
duas filas — o alvo é abaixo de 200ms, senão a interrupção parece travamento.
"""

from __future__ import annotations

import queue
import re
import threading
from dataclasses import dataclass, field
from typing import Callable

# Fim de frase de verdade.
_TERMINAL = re.compile(r"[.!?…]+[\"'”’)\]]*(\s|$)")
# Pausa boa o bastante pra cortar, se já houver texto suficiente antes dela.
_SOFT = re.compile(r"[,;:—–][\"'”’)\]]*(\s|$)")
# Não cortar em "3.5", "R$ 1.200" nem em abreviação comum.
_NUMERIC_DOT = re.compile(r"\d\.\d?$")
_ABBREV = re.compile(r"\b(sr|sra|dr|dra|prof|etc|ex|obs|av|pág|núm|no|nº)\.$", re.IGNORECASE)


@dataclass
class SentenceChunker:
    """Recebe texto em fluxo, solta pedaços prontos pra falar."""

    min_chars: int = 25          # folga antes de aceitar corte em vírgula
    max_chars: int = 220         # trava de segurança: modelo sem pontuação
    _buffer: str = field(default="", init=False)

    def feed(self, text: str) -> list[str]:
        self._buffer += text
        out: list[str] = []

        while True:
            cut = self._find_cut()
            if cut is None:
                break
            chunk, self._buffer = self._buffer[:cut].strip(), self._buffer[cut:]
            if chunk:
                out.append(chunk)

        return out

    def flush(self) -> str:
        """O resto, no fim do fluxo. Sempre chame — senão a última frase some."""
        rest, self._buffer = self._buffer.strip(), ""
        return rest

    def _find_cut(self) -> int | None:
        buf = self._buffer

        for match in _TERMINAL.finditer(buf):
            end = match.end()
            head = buf[:match.start() + 1]
            if _NUMERIC_DOT.search(head) or _ABBREV.search(head.rstrip()):
                continue  # "3.5" e "Sr." não são fim de frase
            return end

        if len(buf) >= self.min_chars:
            for match in _SOFT.finditer(buf):
                if match.end() >= self.min_chars:
                    return match.end()

        if len(buf) >= self.max_chars:
            # Sem pontuação nenhuma: corta no último espaço pra não picar palavra.
            space = buf.rfind(" ", 0, self.max_chars)
            return space + 1 if space > self.min_chars else self.max_chars

        return None


class StreamingSpeech:
    """Esteira de duas etapas: sintetiza um pedaço enquanto toca o anterior."""

    def __init__(self, speaker, on_chunk: Callable[[str], None] | None = None):
        # speaker precisa expor synth(text) -> (samples, samplerate) e play(...).
        self.speaker = speaker
        self.on_chunk = on_chunk or (lambda _text: None)

        self._synth_q: queue.Queue = queue.Queue()
        self._play_q: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._done = threading.Event()
        self._threads: list[threading.Thread] = []
        self._spoken: list[str] = []
        self._lock = threading.Lock()

    # -- ciclo de vida ----------------------------------------------------

    def begin(self) -> None:
        self._stop.clear()
        self._done.clear()
        self._spoken.clear()
        self._synth_q = queue.Queue()
        self._play_q = queue.Queue()
        self._threads = [
            threading.Thread(target=self._synth_worker, name="apex-synth", daemon=True),
            threading.Thread(target=self._play_worker, name="apex-play", daemon=True),
        ]
        for thread in self._threads:
            thread.start()

    def push(self, chunk: str) -> None:
        if chunk.strip() and not self._stop.is_set():
            self._synth_q.put(chunk.strip())

    def end(self) -> None:
        """Sinaliza fim do texto. Não bloqueia — use wait() pra esperar tocar."""
        self._synth_q.put(None)

    def wait(self, timeout: float | None = None) -> bool:
        return self._done.wait(timeout)

    def stop(self) -> None:
        """Corta na hora. É o caminho da interrupção — tem que ser rápido."""
        self._stop.set()
        self.speaker.stop_playback()
        self._drain(self._synth_q)
        self._drain(self._play_q)
        self._synth_q.put(None)
        self._play_q.put(None)
        self._done.set()

    @property
    def interrupted(self) -> bool:
        return self._stop.is_set()

    @property
    def spoken_text(self) -> str:
        with self._lock:
            return " ".join(self._spoken)

    @staticmethod
    def _drain(q: queue.Queue) -> None:
        while True:
            try:
                q.get_nowait()
            except queue.Empty:
                return

    # -- trabalhadores ----------------------------------------------------

    def _synth_worker(self) -> None:
        while not self._stop.is_set():
            item = self._synth_q.get()
            if item is None:
                self._play_q.put(None)
                return
            try:
                audio = self.speaker.synth(item)
            except Exception:  # noqa: BLE001 - um pedaço mudo não derruba a fala
                audio = None
            if audio is not None and not self._stop.is_set():
                self._play_q.put((item, audio))

    def _play_worker(self) -> None:
        while True:
            item = self._play_q.get()
            if item is None or self._stop.is_set():
                self._done.set()
                return
            text, audio = item
            with self._lock:
                self._spoken.append(text)
            self.on_chunk(text)
            try:
                self.speaker.play(audio)
            except Exception:  # noqa: BLE001
                pass
            if self._stop.is_set():
                self._done.set()
                return
