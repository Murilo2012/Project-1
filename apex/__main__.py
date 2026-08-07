"""APEX — ponto de entrada.

    python -m apex                    roda o daemon de voz + HUD
    python -m apex --texto            modo texto (sem microfone), pra depurar
    python -m apex --sem-hud          sem HUD, log corrido no terminal
    python -m apex --listar-audio     lista os microfones disponíveis
    python -m apex --testar-audio     calibra e mostra níveis, pra ajustar o mic
    python -m apex --testar-cerebro   confere se o cérebro responde
    python -m apex --local            força o cérebro local (Ollama)
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from datetime import datetime

from apex import config as config_module
from apex import persona
from apex.audio.speech import SentenceChunker, StreamingSpeech
from apex.audio.stt import Transcriber, find_wake_word
from apex.awareness import Awareness
from apex.brain import make_brain
from apex.hud import Hud
from apex.safety import interpret_confirmation
from apex.scheduler import Scheduler
from apex.server import Bridge, WebFace
from apex.vault import Vault


class Apex:
    def __init__(self, cfg, use_hud: bool = True):
        # Importados aqui, não no topo: o modo texto tem que rodar numa máquina
        # sem PortAudio, e importar estes módulos exige o driver de áudio.
        from apex.audio.listener import Microphone  # noqa: PLC0415
        from apex.audio.tts import Speaker  # noqa: PLC0415

        self.config = cfg
        self.name = cfg.name
        self.vault = Vault(
            cfg.vault_path,
            max_results=cfg.get("vault.max_search_results", 12),
            max_note_chars=cfg.get("vault.max_note_chars", 8000),
        )

        self.streaming = bool(cfg.get("speech.streaming", True))
        self.chunk_min_chars = int(cfg.get("speech.chunk_min_chars", 25))
        self.barge_enabled = bool(cfg.get("speech.barge_in", True))
        self.barge_threshold = float(cfg.get("speech.barge_threshold_above_floor", 28.0))
        self.barge_sustain = float(cfg.get("speech.barge_sustain_seconds", 0.25))

        self.wake_words = cfg.get("wake.words", ["apex"])
        self.conversation_timeout = float(cfg.get("wake.conversation_timeout", 30))
        self.require_name_every_time = bool(cfg.get("wake.require_name_every_time", False))

        self.transcriber = Transcriber(cfg.get("stt", {}))
        self.mic = Microphone(cfg.get("audio", {}), cfg.get("clap", {}))
        self.speaker = Speaker(
            cfg.get("tts", {}),
            output_device=cfg.get("audio.output_device"),
            on_speaking=self._on_speaking,
        )

        self.scheduler = Scheduler(
            cfg.get("scheduler.jobs", []) if cfg.get("scheduler.enabled", True) else [],
            runner=self._run_job,
            on_status=lambda msg: self.hud.log(msg),
        )
        self.hud = Hud(self.name, cfg, self.vault, self.scheduler)
        if not use_hud:
            self.hud._enabled = False  # noqa: SLF001 - flag interna, é o dono aqui

        # O rosto no navegador. O Python continua dono do microfone; o console
        # só mostra o que ele ouve e aceita comando digitado.
        self.bridge = Bridge(self.name, self.vault, self.scheduler)
        self.bridge.on_ask = self.ask_text
        self.web = WebFace(
            self.bridge,
            host=cfg.get("web.host", "127.0.0.1"),
            port=int(cfg.get("web.port", 8765)),
        ) if cfg.get("web.enabled", True) else None

        self.brain = make_brain(
            cfg,
            self.vault,
            on_status=lambda msg: self.hud.log(msg),
            on_confirm=self._confirm_by_voice,
        )

        # A camada que faz ele falar primeiro. É a diferença entre um assistente
        # que responde e um que acompanha.
        self.awareness = Awareness(
            cfg.get("awareness", {}),
            speak=self._speak_unprompted,
            think=self._think_unprompted,
            on_status=lambda msg: self.hud.log(msg),
            is_busy=self._is_busy,
        )

        # A conversa fica aberta por um tempo depois da primeira interação, pra
        # não ter que repetir o nome a cada frase.
        self.window_until = 0.0
        self._brain_lock = threading.Lock()
        self._running = True

    # -- callbacks ---------------------------------------------------------

    def _on_speaking(self, speaking: bool) -> None:
        """Silencia o microfone enquanto o APEX fala, senão ele se ouve e se
        auto-ativa num laço infinito."""
        if speaking:
            self.mic.pause()
            self.hud.set_state("speaking")
        else:
            time.sleep(0.25)  # deixa o eco da caixa morrer antes de voltar a ouvir
            self.mic.resume()

    def _confirm_by_voice(self, reason: str) -> bool:
        """Pergunta em voz alta e espera sim ou não. Timeout é não."""
        self.hud.set_state("confirming")
        self.speak(persona.CONFIRM_TEMPLATE.format(reason=reason))

        deadline = time.monotonic() + self.brain.gate.confirm_timeout
        while time.monotonic() < deadline:
            audio = self.mic.record_utterance(timeout=max(1.0, deadline - time.monotonic()))
            if audio is None:
                break
            answer = self.transcriber.transcribe(audio)
            self.hud.set_heard(answer)
            decision = interpret_confirmation(answer)
            if decision is True:
                self.hud.log("confirmado pelo usuário")
                return True
            if decision is False:
                self.hud.log("negado pelo usuário")
                self.speak(persona.CANCELLED)
                return False
            self.speak("Sim ou não?")

        self.hud.log("confirmação expirou — negando por segurança")
        self.speak(persona.TIMEOUT)
        return False

    # -- proatividade -------------------------------------------------------

    def _is_busy(self) -> bool:
        """Não interrompe quem já está falando com ele."""
        return self.hud.state != "idle" or time.monotonic() < self.window_until

    def _speak_unprompted(self, text: str) -> None:
        """Fala sem ter sido chamado. Abre a janela de conversa depois, porque
        se ele te cutucou, você provavelmente vai responder."""
        self.speak(text)
        self.vault.append_daily_log(f"[proativo] {text}")
        self.window_until = time.monotonic() + self.conversation_timeout
        self.hud.set_state("listening")

    def _think_unprompted(self, prompt: str) -> str:
        """Deixa o modelo compor a interrupção. Só usado quando o sensor pede —
        a maioria das interrupções usa frase pronta e não custa nada."""
        with self._brain_lock:
            self.brain.reset()
            turn = self.brain.ask(prompt)
            self.brain.reset()
        return turn.text

    def _run_job(self, job) -> None:
        """Executa um job agendado. Roda na thread do agendador."""
        with self._brain_lock:
            self.hud.set_state("job")
            self.brain.reset()
            turn = self.brain.ask(job.prompt)
            self.brain.reset()
        self.vault.append_daily_log(f"[job {job.name}] {turn.text[:200]}")
        if job.speak and turn.text:
            self.speak(turn.text)
        self.hud.set_state("idle")

    # -- fala e escuta ------------------------------------------------------

    def speak(self, text: str) -> None:
        if not text:
            return
        self.hud.set_said(text)
        self.bridge.push("apex", text)
        self.bridge.set_phase("speaking")
        self.speaker.say(text)
        self.bridge.set_phase("idle")

    def _respond_streaming(self, text: str) -> tuple[str, bool]:
        """Fala a resposta conforme ela é gerada, e deixa ser interrompida.

        É o que separa assistente de voz de JARVIS: a primeira frase já está no
        alto-falante enquanto o modelo ainda escreve a segunda, e falar por cima
        dele corta o som na hora.
        """
        chunker = SentenceChunker(min_chars=self.chunk_min_chars)
        stream = StreamingSpeech(self.speaker, on_chunk=self._on_chunk_spoken)
        stop_watch = threading.Event()
        barged = threading.Event()

        def watch() -> None:
            # Limiar bem acima do de fala normal: sem cancelamento de eco, o
            # microfone ouve o próprio alto-falante e ele se interromperia.
            threshold = self.mic.noise_floor + self.barge_threshold
            if self.mic.watch_for_speech(stop_watch, threshold, self.barge_sustain):
                barged.set()
                stream.stop()

        self.hud.set_state("speaking")
        self.bridge.set_phase("speaking")
        stream.begin()

        watcher: threading.Thread | None = None
        if self.barge_enabled:
            watcher = threading.Thread(target=watch, name="apex-barge", daemon=True)
            watcher.start()
        else:
            self.mic.pause()

        try:
            for piece in self.brain.ask_streaming(text):
                if stream.interrupted:
                    break
                for chunk in chunker.feed(piece):
                    stream.push(chunk)
            if not stream.interrupted:
                rest = chunker.flush()
                if rest:
                    stream.push(rest)
        finally:
            stream.end()
            stream.wait(timeout=180)
            stop_watch.set()
            if watcher is not None:
                watcher.join(timeout=1.0)
            else:
                self.mic.resume()
            # Descarta o eco do próprio alto-falante antes de voltar a ouvir.
            time.sleep(0.2)
            self.mic.flush()

        self.bridge.end_stream()
        turn = getattr(self.brain, "last_turn", None)
        spoken = stream.spoken_text or (turn.text if turn else "")
        return spoken or "Feito.", barged.is_set()

    def _on_chunk_spoken(self, chunk: str) -> None:
        """Cada pedaço aparece no HUD e no console no instante em que é falado."""
        self.hud.set_said(chunk)
        self.bridge.stream_chunk(chunk)

    def handle_command(self, text: str) -> None:
        self.ask_text(text)

    def ask_text(self, text: str) -> str:
        """Um comando, uma resposta falada. Serve tanto pro laço de voz quanto
        pro console web — os dois passam por aqui, e pelo mesmo cadeado."""
        text = text.strip()
        if not text:
            self.speak(persona.ACK[0])
            return persona.ACK[0]

        self.hud.set_heard(text)
        self.bridge.push("you", text)
        self.hud.set_state("thinking")
        self.bridge.set_phase("thinking")
        self.bridge.bump("cmd")

        started = time.monotonic()
        usa_fluxo = self.streaming and hasattr(self.brain, "ask_streaming")

        if usa_fluxo:
            with self._brain_lock:
                reply, interrompido = self._respond_streaming(text)
            if interrompido:
                self.hud.log("interrompido pelo usuário")
                self.bridge.push("sys", "Interrompido — pode falar.")
        else:
            with self._brain_lock:
                turn = self.brain.ask(text)
            reply = turn.text or "Feito."
            self.speak(reply)

        self.bridge.last_latency = int((time.monotonic() - started) * 1000)
        self.hud.tokens = self.brain.last_usage
        self.bridge.tokens = self.brain.last_usage
        self.vault.append_daily_log(f"“{text}” → {reply[:160]}")

        self.window_until = time.monotonic() + self.conversation_timeout
        self.bridge.window_until = self.window_until
        self.hud.set_state("idle")
        self.bridge.set_phase("idle")
        return reply

    # -- laço principal -----------------------------------------------------

    def run(self) -> None:
        print(f"[{self.name}] carregando modelos de voz...")
        self.transcriber.preload()

        self.mic.start()
        self.hud.noise_floor = self.mic.noise_floor
        self.hud.start()
        self.scheduler.start()
        self.awareness.start()

        if self.web is not None:
            try:
                url = self.web.start()
                self.hud.log(f"console em {url}?k={self.bridge.token}")
                print(f"\n  Console: {url}?k={self.bridge.token}\n")
            except OSError as exc:
                self.hud.log(f"não subi o console web: {exc}")
                self.web = None

        self.hud.log(f"piso de ruído em {self.mic.noise_floor:.0f} dB")
        self.hud.set_state("idle")
        self._boot_sequence()

        try:
            self._event_loop()
        except KeyboardInterrupt:
            pass
        finally:
            self.shutdown()

    def _boot_sequence(self) -> None:
        """O momento 'sistemas online'.

        É teatro — mas do tipo certo: cada linha relata um fato verificado
        agora, não uma animação. Um assistente que abre dizendo o que
        carregou é um assistente que você confia mais no minuto seguinte.
        """
        from apex.tools import REGISTRY  # noqa: PLC0415

        stats = self.vault.stats()
        cerebro = str(self.config.get("brain", "claude")).lower()
        cerebro_desc = (
            f"{self.config.get('model')} · esforço {self.config.get('effort')}"
            if cerebro in ("claude", "anthropic")
            else f"{self.config.get('ollama.model')} · local"
        )

        linhas = [
            ("núcleo", cerebro_desc),
            ("ouvidos", f"whisper {self.config.get('stt.model')} · local"),
            ("voz", f"{self.config.get('tts.engine')} · pt-BR"),
            ("ferramentas", f"{len(REGISTRY)} carregadas"),
            ("memória", f"{stats['wiki']} notas na wiki, {stats['raw']} capturas"),
            ("gatilhos", f"nome “{self.wake_words[0]}”, duas palmas, agendador"),
        ]

        for chave, valor in linhas:
            self.hud.log(f"{chave}: {valor}")
            self.bridge.push("sys", f"{chave}: {valor}")
            time.sleep(0.18)

        saudacao = self._greeting()
        self.hud.log("online")
        self.speak(saudacao)

    def _greeting(self) -> str:
        """Cumprimento pela hora. Curto — ninguém quer discurso às 7 da manhã."""
        hora = datetime.now().hour
        if hora < 5:
            periodo = "Ainda acordado."
        elif hora < 12:
            periodo = "Bom dia."
        elif hora < 18:
            periodo = "Boa tarde."
        else:
            periodo = "Boa noite."
        return f"{periodo} Sistemas online. Tô ouvindo."

    def _event_loop(self) -> None:
        for kind, payload in self.mic.events():
            if not self._running:
                return

            window_open = time.monotonic() < self.window_until
            self.bridge.set_audio(self.mic.last_level, self.mic.noise_floor,
                                  self.mic.silence_threshold_db)
            self.bridge.window_until = self.window_until

            if kind == "idle":
                if self.hud.state == "idle" and window_open is False and self.window_until:
                    self.window_until = 0.0
                    self.brain.reset()
                    self.hud.log("conversa encerrada por inatividade")
                continue

            if kind == "clap":
                self.hud.log("palmas detectadas")
                self.bridge.bump("clap")
                self.bridge.push("sys", "Duas palmas — janela aberta.")
                self.window_until = time.monotonic() + self.conversation_timeout
                self.speak(persona.ACK[0])
                self.hud.set_state("listening")
                continue

            if kind != "utterance" or payload is None:
                continue

            self.hud.set_state("listening")

            # Janela aberta: tudo que for falado é comando, sem repetir o nome.
            if window_open and not self.require_name_every_time:
                text = self.transcriber.transcribe(payload)
                if text.strip():
                    self.handle_command(text)
                else:
                    self.hud.set_state("idle")
                continue

            # Janela fechada: passa pelo modelo rápido só pra achar o nome.
            self.bridge.bump("utt")
            rough = self.transcriber.transcribe_fast(payload)
            found, remainder = find_wake_word(rough, self.wake_words)
            if not found:
                self.bridge.bump("ign")
                self.hud.set_state("idle")
                continue

            self.hud.log(f"acordado por voz: “{rough[:50]}”")
            self.window_until = time.monotonic() + self.conversation_timeout

            if remainder:
                # Reprocessa com o modelo bom: o tiny erra demais em comando.
                full = self.transcriber.transcribe(payload)
                _found, command = find_wake_word(full, self.wake_words)
                self.handle_command(command or remainder)
            else:
                self.speak(persona.ACK[0])
                self.hud.set_state("listening")

    def shutdown(self) -> None:
        self._running = False
        if self.web is not None:
            self.web.stop()
        self.awareness.stop()
        self.scheduler.stop()
        self.hud.stop()
        self.mic.stop()
        print(f"\n[{self.name}] encerrado.")


def run_text_mode(cfg) -> None:
    """Modo texto: mesmo cérebro, mesmas ferramentas, sem microfone.
    É como se depura o comportamento sem brigar com o áudio."""
    vault = Vault(cfg.vault_path)
    brain = make_brain(
        cfg,
        vault,
        on_status=lambda msg: print(f"  \033[38;5;244m· {msg}\033[0m"),
        on_confirm=lambda reason: input(f"  ⚠ Isso {reason}. Confirma? [s/N] ").lower().startswith("s"),
    )
    print(f"{cfg.name} em modo texto. Ctrl+C ou 'sair' encerra.\n")
    while True:
        try:
            text = input("\033[38;5;196mvocê ›\033[0m ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if text.lower() in {"sair", "exit", "quit"}:
            break
        if not text:
            continue
        turn = brain.ask(text)
        print(f"\033[38;5;208m{cfg.name.lower()} ›\033[0m {turn.text}\n")
    print("\nencerrado.")


def list_audio_devices() -> int:
    """Lista os microfones disponíveis com o índice de cada um.

    Existe porque o dispositivo padrão do Windows frequentemente não é o
    microfone que a pessoa acha que é — pode ser um "Stereo Mix" desligado,
    uma webcam sem permissão, ou uma entrada virtual. O sintoma é sempre o
    mesmo: o nível fica travado em -96 dB, que é silêncio digital.
    """
    try:
        import sounddevice as sd  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        print(f"Não consegui carregar o áudio: {exc}")
        return 1

    try:
        devices = sd.query_devices()
        padrao = sd.default.device[0]
    except Exception as exc:  # noqa: BLE001
        print(f"Não consegui listar os dispositivos: {exc}")
        return 1

    print("\nMicrofones disponíveis:\n")
    achou = False
    for index, dev in enumerate(devices):
        if dev.get("max_input_channels", 0) < 1:
            continue
        achou = True
        marca = " <- padrão do Windows" if index == padrao else ""
        taxa = int(dev.get("default_samplerate", 0))
        print(f"  [{index:>2}] {dev['name']}")
        print(f"       {dev['max_input_channels']} canal(is), {taxa} Hz{marca}")

    if not achou:
        print("  Nenhum microfone encontrado.")
        print("  Confira Windows + I > Privacidade e seguranca > Microfone.")
        return 1

    print("\nPra testar um específico:")
    print("  .\\rodar.bat --testar-audio --dispositivo N")
    print("\nPra fixar no config.json, coloque o número em audio.input_device.\n")
    return 0


def run_audio_test(cfg, device=None) -> None:
    """Mostra níveis em tempo real, pra calibrar limiar e detector de palmas."""
    from apex.audio.listener import Microphone  # noqa: PLC0415

    audio_cfg = dict(cfg.get("audio", {}))
    if device is not None:
        audio_cfg["input_device"] = device

    try:
        import sounddevice as sd  # noqa: PLC0415

        escolhido = audio_cfg.get("input_device")
        info = sd.query_devices(escolhido if escolhido is not None else sd.default.device[0])
        print(f"Microfone: {info['name']}")
    except Exception:  # noqa: BLE001
        print("Microfone: padrão do sistema")

    mic = Microphone(audio_cfg, cfg.get("clap", {}))
    print("Calibrando... fique em silêncio por 2 segundos.")
    mic.start()
    print(f"Piso de ruído: {mic.noise_floor:.1f} dB")
    print(f"Limiar de voz: {mic.silence_threshold_db:.1f} dB")

    if mic.noise_floor < -85:
        print("\n  AVISO: piso em silêncio digital. Este dispositivo não está")
        print("  capturando nada. Veja os outros com:  .\\rodar.bat --listar-audio")

    print("\nFale e bata palmas. Ctrl+C pra sair.\n")

    pico = -120.0
    try:
        for block, level, clapped in mic.blocks():
            if block is None:
                continue
            pico = max(pico, level)
            filled = max(0, min(40, int((level + 60) / 60 * 40)))
            bar = "#" * filled + "." * (40 - filled)
            voice = "VOZ  " if level > mic.silence_threshold_db else "     "
            clap = "PALMAS!" if clapped else ""
            print(f"\r{level:>6.1f} dB {bar} {voice}{clap}   ", end="", flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        mic.stop()
        print("\n")
        if pico < -80:
            print("Este microfone não captou nada. O pico ficou em "
                  f"{pico:.0f} dB, que é silêncio.")
            print("Rode  .\\rodar.bat --listar-audio  e teste outro índice.\n")
        else:
            print(f"Pico captado: {pico:.0f} dB. O microfone está funcionando.\n")


def run_brain_test(cfg) -> int:
    """Confere se o cérebro configurado responde, antes de brigar com o áudio."""
    kind = str(cfg.get("brain", "claude")).lower()
    print(f"Cérebro configurado: {kind}")

    if kind in ("ollama", "local"):
        from apex.ollama_brain import check_server  # noqa: PLC0415

        host = cfg.get("ollama.host", "http://localhost:11434")
        model = cfg.get("ollama.model", "qwen3:8b")
        ok, message = check_server(host, model)
        print(("  " if ok else "  ✗ ") + message)
        if not ok:
            return 1
    elif not cfg.has_api_key:
        print(f"  ✗ Sem chave da API. Preencha 'anthropic_api_key' em {cfg.path}.")
        return 1
    else:
        print(f"  Modelo: {cfg.get('model')} · effort {cfg.get('effort')}")

    print("\nMandando uma pergunta de teste...")
    vault = Vault(cfg.vault_path)
    brain = make_brain(cfg, vault, on_status=lambda m: print(f"  · {m}"))
    turn = brain.ask("Em uma frase curta: você está funcionando?")
    print(f"\n  {cfg.name}: {turn.text}")
    print(f"  ({turn.elapsed:.1f}s, ferramentas usadas: {turn.tool_calls or 'nenhuma'})")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="apex", description="APEX — copiloto de voz")
    parser.add_argument("--texto", action="store_true", help="modo texto, sem microfone")
    parser.add_argument("--sem-hud", action="store_true", help="desliga o HUD")
    parser.add_argument("--testar-audio", action="store_true", help="calibra o microfone")
    parser.add_argument("--listar-audio", action="store_true", help="lista os microfones")
    parser.add_argument("--dispositivo", type=int, default=None,
                        help="índice do microfone (veja com --listar-audio)")
    parser.add_argument("--testar-cerebro", action="store_true", help="testa o cérebro configurado")
    parser.add_argument("--local", action="store_true", help="força o cérebro local (Ollama)")
    parser.add_argument("--config", default=None, help="caminho do config.json")
    args = parser.parse_args()

    try:
        cfg = config_module.load(args.config)
    except config_module.ConfigError as exc:
        print(f"Erro de configuração: {exc}")
        return 1

    if args.local:
        cfg._data["brain"] = "ollama"  # noqa: SLF001 - override de linha de comando

    if args.listar_audio:
        return list_audio_devices()

    if args.testar_audio:
        run_audio_test(cfg, device=args.dispositivo)
        return 0

    if args.testar_cerebro:
        return run_brain_test(cfg)

    usa_claude = str(cfg.get("brain", "claude")).lower() in ("claude", "anthropic")
    if usa_claude and not cfg.has_api_key:
        print(persona.NO_API_KEY)
        print(f"Coloque a chave em {cfg.path} no campo 'anthropic_api_key',")
        print('ou rode com cérebro local: python -m apex --local')
        return 1

    if args.texto:
        run_text_mode(cfg)
        return 0

    Apex(cfg, use_hud=not args.sem_hud).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
