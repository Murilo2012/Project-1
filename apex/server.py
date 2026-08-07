"""Servidor local: o rosto do APEX no navegador.

A ARQUITETURA, NA ANALOGIA CERTA
  ORBIT (navegador) está para o APEX assim como o Claude normal está para o
  Claude Code. Um conversa e mostra; o outro tem mãos.

  O navegador é o ROSTO: mostra estado, telemetria e histórico, e aceita texto.
  O Python é o CORPO: microfone, transcrição, voz, ferramentas, o PC inteiro.

  Um microfone só. Quem segura é o Python — ele já tem Whisper local, detector
  de palmas e wake word. O navegador NÃO abre o microfone quando está ligado ao
  APEX; ele desenha o que o Python está ouvindo. Dois processos disputando o
  mesmo microfone é bug garantido.

SEGURANÇA, E POR QUE NÃO BASTA ESCUTAR EM 127.0.0.1
  Escutar só no loopback impede acesso de fora da máquina, mas NÃO impede que
  um site qualquer aberto no seu navegador mande um POST pra localhost — CORS
  bloqueia a leitura da resposta, não o envio do pedido. Um site malicioso
  poderia mandar comandos pro seu APEX.

  Duas travas, as duas necessárias:
    1. Token gerado a cada inicialização, exigido em toda chamada de API.
    2. Content-Type: application/json obrigatório no POST, o que força o
       navegador a fazer preflight — e o preflight nós recusamos pra origem
       estranha.
"""

from __future__ import annotations

import json
import secrets
import threading
from collections import deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

WEB_DIR = Path(__file__).resolve().parent / "web"
MAX_FEED = 60
MAX_HIST = 120


class Bridge:
    """Estado compartilhado entre o laço de voz e o navegador.

    O navegador consulta por polling em vez de SSE. Em localhost o polling é
    gratuito e não tem os casos de borda de stream que morre — reconexão,
    buffer preso no http.server. Menos elegante, muito menos bug.
    """

    def __init__(self, name: str, vault, scheduler=None):
        self.name = name
        self.vault = vault
        self.scheduler = scheduler

        self.token = secrets.token_urlsafe(16)
        self.lock = threading.Lock()

        self.phase = "idle"
        self.level = -120.0
        self.floor = -60.0
        self.thresh = -38.0
        self.hist: deque[float] = deque([-120.0] * MAX_HIST, maxlen=MAX_HIST)
        self.feed: deque[dict] = deque(maxlen=MAX_FEED)
        self._streaming = False
        self.window_until = 0.0

        self.counters = {"utt": 0, "cmd": 0, "ign": 0, "clap": 0, "words": 0}
        self.tokens = {}
        self.last_latency: int | None = None
        self.started = datetime.now()

        # Preenchido pelo Apex — é como o navegador manda comando pro cérebro.
        self.on_ask: Callable[[str], str] | None = None

    # -- escrita, vinda do laço de voz -------------------------------------

    def push(self, who: str, text: str, note: str = "") -> None:
        with self.lock:
            self._streaming = False
            self.feed.append({
                "who": who, "text": text, "note": note,
                "at": datetime.now().strftime("%H:%M:%S"),
            })

    def stream_chunk(self, text: str) -> None:
        """Anexa à última fala em vez de criar mensagem nova.

        A fala sai em pedaços de uma frase; cada pedaço virando um balão
        separado no console picotaria a resposta. Aqui a frase cresce na tela
        no mesmo ritmo em que sai do alto-falante.
        """
        with self.lock:
            if self._streaming and self.feed and self.feed[-1]["who"] == "apex":
                self.feed[-1]["text"] = (self.feed[-1]["text"] + " " + text).strip()
                return
            self._streaming = True
            self.feed.append({
                "who": "apex", "text": text, "note": "",
                "at": datetime.now().strftime("%H:%M:%S"),
            })

    def end_stream(self) -> None:
        with self.lock:
            self._streaming = False

    def set_phase(self, phase: str) -> None:
        with self.lock:
            self.phase = phase

    def set_audio(self, level: float, floor: float, thresh: float) -> None:
        with self.lock:
            self.level = level
            self.floor = floor
            self.thresh = thresh
            self.hist.append(level)

    def bump(self, key: str, amount: int = 1) -> None:
        with self.lock:
            self.counters[key] = self.counters.get(key, 0) + amount

    # -- leitura, pro navegador --------------------------------------------

    def snapshot(self) -> dict:
        with self.lock:
            upcoming = None
            if self.scheduler is not None:
                nxt = self.scheduler.next_job()
                if nxt:
                    job, when = nxt
                    upcoming = {"name": job.name, "at": when.strftime("%d/%m %H:%M")}

            return {
                "name": self.name,
                "phase": self.phase,
                "level": round(self.level, 1),
                "floor": round(self.floor, 1),
                "thresh": round(self.thresh, 1),
                "hist": [round(v, 1) for v in self.hist],
                "feed": list(self.feed),
                "counters": dict(self.counters),
                "tokens": dict(self.tokens),
                "latency": self.last_latency,
                "vault": self.vault.stats(),
                "job": upcoming,
                "uptime": int((datetime.now() - self.started).total_seconds()),
                "clock": datetime.now().strftime("%H:%M:%S"),
                "window": max(0, int(self.window_until - __import__("time").monotonic())),
            }


class Handler(BaseHTTPRequestHandler):
    bridge: Bridge = None  # type: ignore[assignment]
    server_version = "APEX"
    sys_version = ""

    def log_message(self, *_args) -> None:
        pass  # o HUD já é o log; não queremos linha de acesso poluindo o terminal

    # -- utilidades --------------------------------------------------------

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        # Sem CORS de propósito: nenhuma origem externa deve ler isto.
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, payload: dict) -> None:
        self._send(code, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _authorized(self) -> bool:
        from urllib.parse import parse_qs, urlparse  # noqa: PLC0415

        query = parse_qs(urlparse(self.path).query)
        given = (query.get("k") or [""])[0] or self.headers.get("X-Apex-Token", "")
        return secrets.compare_digest(given, self.bridge.token)

    # -- rotas -------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802 - assinatura da stdlib
        from urllib.parse import urlparse  # noqa: PLC0415

        path = urlparse(self.path).path

        if path in ("/", "/index.html"):
            page = WEB_DIR / "console.html"
            if not page.exists():
                self._send(404, b"console.html nao encontrado", "text/plain; charset=utf-8")
                return
            html = page.read_text(encoding="utf-8-sig")
            # O token entra na página servida, não na URL que o usuário digita.
            html = html.replace("__APEX_TOKEN__", self.bridge.token)
            self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
            return

        if path == "/api/state":
            if not self._authorized():
                self._json(403, {"error": "token inválido"})
                return
            self._json(200, self.bridge.snapshot())
            return

        self._send(404, b"nao encontrado", "text/plain; charset=utf-8")

    def do_POST(self) -> None:  # noqa: N802 - assinatura da stdlib
        from urllib.parse import urlparse  # noqa: PLC0415

        if urlparse(self.path).path != "/api/ask":
            self._send(404, b"nao encontrado", "text/plain; charset=utf-8")
            return

        # Exigir JSON força preflight em requisição de outra origem, e o
        # preflight nós não respondemos. Junto com o token, fecha a porta.
        if "application/json" not in (self.headers.get("Content-Type") or ""):
            self._json(415, {"error": "esperado application/json"})
            return

        if not self._authorized():
            self._json(403, {"error": "token inválido"})
            return

        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            text = str(payload.get("text", "")).strip()
        except (ValueError, UnicodeDecodeError):
            self._json(400, {"error": "corpo inválido"})
            return

        if not text:
            self._json(400, {"error": "texto vazio"})
            return

        if self.bridge.on_ask is None:
            self._json(503, {"error": "cérebro indisponível"})
            return

        try:
            reply = self.bridge.on_ask(text)
        except Exception as exc:  # noqa: BLE001 - o erro tem que virar resposta
            self._json(500, {"error": f"{type(exc).__name__}: {exc}"})
            return

        self._json(200, {"reply": reply})

    def do_OPTIONS(self) -> None:  # noqa: N802 - assinatura da stdlib
        # Preflight recusado: é exatamente o que impede um site externo de
        # mandar comando pro APEX pelo navegador do usuário.
        self._send(403, b"", "text/plain")


class WebFace:
    def __init__(self, bridge: Bridge, host: str = "127.0.0.1", port: int = 8765):
        self.bridge = bridge
        self.host = host
        self.port = port
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/"

    def start(self) -> str:
        handler = type("BoundHandler", (Handler,), {"bridge": self.bridge})
        self._server = ThreadingHTTPServer((self.host, self.port), handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(
            target=self._server.serve_forever, name="apex-web", daemon=True
        )
        self._thread.start()
        return self.url

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
