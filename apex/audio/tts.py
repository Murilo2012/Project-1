"""Síntese de voz com cadeia de fallback e síntese separada da reprodução.

Ordem de preferência:
  1. piper   — offline, rápido em CPU, vozes pt-BR decentes. O padrão.
  2. edge    — precisa de internet, mas a voz é bem melhor.
  3. pyttsx3 — voz nativa do Windows (SAPI). Robótica, mas sempre funciona.

Se o motor escolhido falhar, cai pro próximo em vez de emudecer. Um assistente
de voz que fica mudo por causa de um problema de rede é inútil.

POR QUE synth() E play() SÃO SEPARADOS
A fala em fluxo precisa sintetizar o pedaço N+1 enquanto toca o N. Com um
`say()` monolítico isso é impossível: cada pedaço pagaria o custo de síntese em
silêncio. `synth()` devolve amostras, `play()` toca, e `stop_playback()` corta
na hora — que é o que a interrupção exige.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

import numpy as np

try:
    import sounddevice as sd
except (ImportError, OSError):  # pragma: no cover - sem PortAudio no sistema
    sd = None  # type: ignore[assignment]


PIPER_VOICE_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main/pt/pt_BR"

KNOWN_PIPER_VOICES = {
    "pt_BR-faber-medium": f"{PIPER_VOICE_BASE}/faber/medium/pt_BR-faber-medium",
    "pt_BR-edresson-low": f"{PIPER_VOICE_BASE}/edresson/low/pt_BR-edresson-low",
    "pt_BR-cadu-medium": f"{PIPER_VOICE_BASE}/cadu/medium/pt_BR-cadu-medium",
    "pt_BR-jeff-medium": f"{PIPER_VOICE_BASE}/jeff/medium/pt_BR-jeff-medium",
}

Audio = tuple[np.ndarray, int]


class SpeechError(RuntimeError):
    pass


def _read_audio(path: Path) -> Audio:
    import soundfile as sf  # noqa: PLC0415 - import caro

    data, samplerate = sf.read(str(path), dtype="float32", always_2d=False)
    return data, samplerate


class Speaker:
    """Sintetiza e toca. Serializa a reprodução — nunca duas falas ao mesmo tempo."""

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
        self.on_speaking = on_speaking

        self._play_lock = threading.Lock()
        self._failed: set[str] = set()

    # -- síntese ----------------------------------------------------------

    def synth(self, text: str) -> Audio | None:
        """Texto vira amostras. Não toca nada."""
        text = (text or "").strip()
        if not text:
            return None

        for engine in self._engine_chain():
            try:
                return getattr(self, f"_synth_{engine}")(text)
            except Exception as exc:  # noqa: BLE001 - a cadeia de fallback é o ponto
                if engine not in self._failed:
                    self._failed.add(engine)
                    print(f"[tts] motor '{engine}' falhou ({exc}); tentando o próximo")
        print(f"[tts] nenhum motor funcionou. Texto era: {text}")
        return None

    def _engine_chain(self) -> list[str]:
        chain = [self.engine] + [e for e in ("piper", "edge", "pyttsx3") if e != self.engine]
        return [e for e in chain if e not in self._failed] or ["pyttsx3"]

    def _piper_paths(self) -> tuple[Path, Path]:
        return (self.piper_model_dir / f"{self.piper_voice}.onnx",
                self.piper_model_dir / f"{self.piper_voice}.onnx.json")

    def _synth_piper(self, text: str) -> Audio:
        model, config = self._piper_paths()
        if not model.exists():
            raise SpeechError(
                f"voz do Piper não encontrada em {model}. "
                "Rode: python -m apex.audio.tts --baixar-voz"
            )

        binary = shutil.which("piper") or shutil.which("piper.exe")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "fala.wav"
            cmd = ([binary] if binary else ["python", "-m", "piper"]) + [
                "--model", str(model), "--output_file", str(out)
            ]
            if binary and config.exists():
                cmd += ["--config", str(config)]
            subprocess.run(
                cmd, input=text.encode("utf-8"), check=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=60,
            )
            return _read_audio(out)

    def _synth_edge(self, text: str) -> Audio:
        import edge_tts  # noqa: PLC0415 - import caro e opcional

        async def run(destination: Path) -> None:
            await edge_tts.Communicate(
                text, self.edge_voice, rate=self.rate, pitch=self.pitch
            ).save(str(destination))

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "fala.mp3"
            asyncio.run(run(out))
            return _read_audio(out)

    def _synth_pyttsx3(self, text: str) -> Audio:
        import pyttsx3  # noqa: PLC0415 - import caro e opcional

        engine = pyttsx3.init()
        for voice in engine.getProperty("voices"):
            if "brazil" in voice.name.lower() or "portug" in voice.name.lower():
                engine.setProperty("voice", voice.id)
                break
        engine.setProperty("rate", 190)

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "fala.wav"
            engine.save_to_file(text, str(out))
            engine.runAndWait()
            engine.stop()
            if not out.exists():
                raise SpeechError("pyttsx3 não gerou o arquivo")
            return _read_audio(out)

    # -- reprodução -------------------------------------------------------

    def play(self, audio: Audio) -> None:
        if sd is None:
            raise SpeechError("sounddevice indisponível — não consigo tocar áudio")
        data, samplerate = audio
        with self._play_lock:
            sd.play(data, samplerate, device=self.output_device)
            sd.wait()

    def stop_playback(self) -> None:
        """Corta o som imediatamente. É o caminho da interrupção."""
        if sd is not None:
            try:
                sd.stop()
            except Exception:  # noqa: BLE001
                pass

    def say(self, text: str) -> None:
        """Fala de uma vez. Usado onde latência não importa — confirmação,
        boot, frase curta. Pra resposta do modelo, use a fala em fluxo."""
        if not (text or "").strip():
            return
        if self.on_speaking:
            self.on_speaking(True)
        try:
            audio = self.synth(text)
            if audio is not None:
                self.play(audio)
        finally:
            if self.on_speaking:
                self.on_speaking(False)


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
