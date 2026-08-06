"""Síntese de voz com cadeia de fallback.

Ordem de preferência:
  1. piper   — offline, rápido em CPU, vozes pt-BR decentes. O padrão.
  2. edge    — precisa de internet, mas a voz é bem melhor.
  3. pyttsx3 — voz nativa do Windows (SAPI). Robótica, mas sempre funciona.

Se o motor escolhido falhar, cai pro próximo em vez de emudecer. Um assistente
de voz que fica mudo por causa de um problema de rede é inútil.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

import numpy as np

try:
    import sounddevice as sd
except OSError:  # pragma: no cover
    sd = None  # type: ignore[assignment]


PIPER_VOICE_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main/pt/pt_BR"

# Vozes pt-BR conhecidas do Piper e o caminho delas no repositório.
KNOWN_PIPER_VOICES = {
    "pt_BR-faber-medium": f"{PIPER_VOICE_BASE}/faber/medium/pt_BR-faber-medium",
    "pt_BR-edresson-low": f"{PIPER_VOICE_BASE}/edresson/low/pt_BR-edresson-low",
    "pt_BR-cadu-medium": f"{PIPER_VOICE_BASE}/cadu/medium/pt_BR-cadu-medium",
    "pt_BR-jeff-medium": f"{PIPER_VOICE_BASE}/jeff/medium/pt_BR-jeff-medium",
}


class SpeechError(RuntimeError):
    pass


def _play_wav(path: Path, device=None) -> None:
    import soundfile as sf  # noqa: PLC0415 - import caro

    data, samplerate = sf.read(str(path), dtype="float32", always_2d=False)
    if sd is None:
        raise SpeechError("sounddevice indisponível — não consigo tocar áudio")
    sd.play(data, samplerate, device=device)
    sd.wait()


class Speaker:
    """Fala texto em voz alta. Serializa as falas — nunca duas ao mesmo tempo."""

    def __init__(self, tts_config: dict, output_device=None, on_speaking=None):
        self.engine = tts_config.get("engine", "piper")
        self.piper_voice = tts_config.get("piper_voice", "pt_BR-faber-medium")
        self.piper_model_dir = Path(
            tts_config.get("piper_model_dir", "~/APEX/voices")
        ).expanduser()
        self.edge_voice = tts_config.get("edge_voice", "pt-BR-AntonioNeural")
        self.rate = tts_config.get("rate", "+0%")
        self.pitch = tts_config.get("pitch", "+0Hz")
        self.output_device = output_device
        # Callback (bool) avisando quando começa e para de falar, pra quem
        # estiver ouvindo poder silenciar o microfone.
        self.on_speaking = on_speaking
        self._lock = threading.Lock()
        self._failed: set[str] = set()

    # -- API pública ------------------------------------------------------

    def say(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return

        with self._lock:
            if self.on_speaking:
                self.on_speaking(True)
            try:
                for engine in self._engine_chain():
                    try:
                        getattr(self, f"_say_{engine}")(text)
                        return
                    except Exception as exc:  # noqa: BLE001 - queremos o fallback
                        if engine not in self._failed:
                            self._failed.add(engine)
                            print(f"[tts] motor '{engine}' falhou ({exc}); tentando o próximo")
                print(f"[tts] nenhum motor funcionou. Texto era: {text}")
            finally:
                if self.on_speaking:
                    self.on_speaking(False)

    def _engine_chain(self) -> list[str]:
        chain = [self.engine] + [e for e in ("piper", "edge", "pyttsx3") if e != self.engine]
        return [e for e in chain if e not in self._failed] or ["pyttsx3"]

    # -- motores ----------------------------------------------------------

    def _piper_paths(self) -> tuple[Path, Path]:
        model = self.piper_model_dir / f"{self.piper_voice}.onnx"
        config = self.piper_model_dir / f"{self.piper_voice}.onnx.json"
        return model, config

    def _say_piper(self, text: str) -> None:
        model, config = self._piper_paths()
        if not model.exists():
            raise SpeechError(
                f"voz do Piper não encontrada em {model}. "
                "Rode: python -m apex.audio.tts --baixar-voz"
            )

        binary = shutil.which("piper") or shutil.which("piper.exe")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "fala.wav"
            if binary:
                cmd = [binary, "--model", str(model), "--output_file", str(out)]
                if config.exists():
                    cmd += ["--config", str(config)]
                subprocess.run(
                    cmd, input=text.encode("utf-8"), check=True,
                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=60,
                )
            else:
                # Sem binário no PATH, tenta o módulo Python do pacote piper-tts.
                subprocess.run(
                    ["python", "-m", "piper", "--model", str(model), "--output_file", str(out)],
                    input=text.encode("utf-8"), check=True,
                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=60,
                )
            _play_wav(out, self.output_device)

    def _say_edge(self, text: str) -> None:
        import edge_tts  # noqa: PLC0415 - import caro e opcional

        async def synthesize(destination: Path) -> None:
            communicate = edge_tts.Communicate(
                text, self.edge_voice, rate=self.rate, pitch=self.pitch
            )
            await communicate.save(str(destination))

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "fala.mp3"
            asyncio.run(synthesize(out))
            _play_wav(out, self.output_device)

    def _say_pyttsx3(self, text: str) -> None:
        import pyttsx3  # noqa: PLC0415 - import caro e opcional

        engine = pyttsx3.init()
        for voice in engine.getProperty("voices"):
            if "brazil" in voice.name.lower() or "portug" in voice.name.lower():
                engine.setProperty("voice", voice.id)
                break
        engine.setProperty("rate", 190)
        engine.say(text)
        engine.runAndWait()
        engine.stop()


def download_piper_voice(voice: str, target_dir: Path) -> None:
    """Baixa modelo e config de uma voz do Piper do HuggingFace."""
    import urllib.request  # noqa: PLC0415

    if voice not in KNOWN_PIPER_VOICES:
        raise SpeechError(
            f"voz '{voice}' desconhecida. Conhecidas: {', '.join(KNOWN_PIPER_VOICES)}"
        )

    base = KNOWN_PIPER_VOICES[voice]
    target_dir.mkdir(parents=True, exist_ok=True)

    for suffix in (".onnx", ".onnx.json"):
        destination = target_dir / f"{voice}{suffix}"
        if destination.exists():
            print(f"[tts] {destination.name} já existe, pulando")
            continue
        url = f"{base}{suffix}"
        print(f"[tts] baixando {url}")
        urllib.request.urlretrieve(url, destination)  # noqa: S310 - URL fixa e confiável
        print(f"[tts] salvo em {destination}")


if __name__ == "__main__":  # pragma: no cover
    import argparse
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from apex import config as config_module

    parser = argparse.ArgumentParser(description="Utilitários de voz do APEX")
    parser.add_argument("--baixar-voz", action="store_true", help="baixa a voz do Piper")
    parser.add_argument("--voz", default=None, help="nome da voz (padrão: o da config)")
    parser.add_argument("--testar", default=None, help="fala um texto de teste")
    args = parser.parse_args()

    cfg = config_module.load()
    voice_name = args.voz or cfg.get("tts.piper_voice", "pt_BR-faber-medium")
    model_dir = Path(cfg.get("tts.piper_model_dir", "~/APEX/voices")).expanduser()

    if args.baixar_voz:
        download_piper_voice(voice_name, model_dir)
    if args.testar:
        Speaker(cfg.get("tts", {}), cfg.get("audio.output_device")).say(args.testar)
    if not args.baixar_voz and not args.testar:
        parser.print_help()
