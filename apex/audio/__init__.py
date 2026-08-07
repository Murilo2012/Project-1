"""Ouvidos e boca do APEX.

Os imports são preguiçosos de propósito: `listener` precisa do PortAudio via
sounddevice, e o modo texto (`python -m apex --texto`) tem que funcionar numa
máquina sem áudio nenhum. Importar o pacote não pode exigir microfone.
"""

from __future__ import annotations

__all__ = [
    "ClapDetector",
    "Microphone",
    "Speaker",
    "Transcriber",
    "dbfs",
    "find_wake_word",
    "normalize",
]

_LAZY = {
    "ClapDetector": "apex.audio.listener",
    "Microphone": "apex.audio.listener",
    "dbfs": "apex.audio.listener",
    "Transcriber": "apex.audio.stt",
    "find_wake_word": "apex.audio.stt",
    "normalize": "apex.audio.stt",
    "Speaker": "apex.audio.tts",
}


def __getattr__(name: str):
    if name not in _LAZY:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    return getattr(importlib.import_module(_LAZY[name]), name)
