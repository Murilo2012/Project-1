"""Transcrição local com faster-whisper. O áudio nunca sai da máquina.

Dois modelos, carregados sob demanda:
  - wake  (tiny)  — roda em toda fala captada, só pra ver se o nome foi dito.
                    Precisa ser barato porque roda o tempo todo.
  - main  (small) — roda só depois que o gatilho abriu. Pode ser mais lento.

Se `stt.wake_model` for null na config, o modelo principal é usado nos dois
casos (mais preciso, mais CPU).
"""

from __future__ import annotations

import re
import unicodedata

import numpy as np

_MODEL_CACHE: dict[tuple[str, str, str], object] = {}

# Palavras que podem legitimamente vir antes do nome numa chamada.
# "o" e "e" ficam de fora de propósito: aceitá-los faz "o apex do gráfico é
# alto" acordar o assistente. Um artigo é comum demais pra servir de vocativo.
VOCATIVES = {"ei", "ai", "oi", "ola", "opa", "hey", "psiu", "fala"}


def _resolve_device(device: str) -> tuple[str, str]:
    """Escolhe device e compute_type. 'auto' tenta GPU e cai pra CPU."""
    if device != "auto":
        return device, ("float16" if device == "cuda" else "int8")
    try:
        import torch  # noqa: PLC0415 - opcional, só pra detectar GPU

        if torch.cuda.is_available():
            return "cuda", "float16"
    except Exception:
        pass
    return "cpu", "int8"


def _load(model_name: str, device: str, compute_type: str):
    from faster_whisper import WhisperModel  # noqa: PLC0415 - import caro

    resolved_device, default_compute = _resolve_device(device)
    if compute_type == "auto":
        compute_type = default_compute

    key = (model_name, resolved_device, compute_type)
    if key not in _MODEL_CACHE:
        _MODEL_CACHE[key] = WhisperModel(
            model_name, device=resolved_device, compute_type=compute_type
        )
    return _MODEL_CACHE[key]


def normalize(text: str) -> str:
    """Minúsculas, sem acento, sem pontuação — pra comparar wake words."""
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9\s]", " ", text).strip()


class Transcriber:
    def __init__(self, stt_config: dict):
        self.language = stt_config.get("language", "pt")
        self.device = stt_config.get("device", "auto")
        self.compute_type = stt_config.get("compute_type", "auto")
        self.main_model_name = stt_config.get("model", "small")
        self.wake_model_name = stt_config.get("wake_model") or self.main_model_name

    def preload(self) -> None:
        """Carrega os modelos agora, pra primeira fala não ter 10s de espera."""
        _load(self.wake_model_name, self.device, self.compute_type)
        if self.wake_model_name != self.main_model_name:
            _load(self.main_model_name, self.device, self.compute_type)

    def _transcribe(self, model_name: str, audio: np.ndarray, beam_size: int) -> str:
        model = _load(model_name, self.device, self.compute_type)
        segments, _info = model.transcribe(
            audio.astype("float32"),
            language=self.language,
            beam_size=beam_size,
            vad_filter=True,
            condition_on_previous_text=False,
        )
        return " ".join(segment.text.strip() for segment in segments).strip()

    def transcribe(self, audio: np.ndarray) -> str:
        """Transcrição completa, para comandos."""
        return self._transcribe(self.main_model_name, audio, beam_size=5)

    def transcribe_fast(self, audio: np.ndarray) -> str:
        """Transcrição rápida e imprecisa, só pra checar o wake word."""
        return self._transcribe(self.wake_model_name, audio, beam_size=1)


def find_wake_word(text: str, wake_words: list[str]) -> tuple[bool, str]:
    """Procura o nome no texto. Devolve (encontrou, resto_da_frase).

    'Apex, abre o Spotify' -> (True, 'abre o Spotify')
    'Apex.'                -> (True, '')
    'abre o Spotify'       -> (False, 'abre o Spotify')

    O resto vem com acentuação e maiúsculas originais — quem fala "Apex, abre o
    Spotify" numa tacada só não deveria precisar repetir, e o comando que segue
    pro modelo tem que estar legível.
    """
    tokens = text.split()
    if not tokens:
        return False, ""

    targets = {normalize(w) for w in wake_words if normalize(w)}

    # O nome tem que ABRIR a frase. Só um vocativo pode vir antes ("ei, Apex").
    # Sem essa restrição, "o apex do gráfico é alto" acorda o assistente e vira
    # o comando "do gráfico é alto" — que é exatamente o tipo de falso positivo
    # que faz a pessoa desligar o wake word.
    for index, token in enumerate(tokens[:2]):
        if normalize(token) not in targets:
            if index == 0 and normalize(token) in VOCATIVES:
                continue
            break
        remainder = " ".join(tokens[index + 1:])
        return True, remainder.lstrip(",.;:!?- ").strip()

    return False, text.strip()
