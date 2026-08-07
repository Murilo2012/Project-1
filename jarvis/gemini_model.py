"""
Descobre em tempo de execução qual modelo Gemini a chave do usuário pode usar.

O Mark-L pedia "gemini-2.5-flash" cravado em 12 lugares. O Google tirou esse
modelo do ar para chaves criadas recentemente, e todas essas chamadas passaram
a devolver 404 — notícias, leitura de arquivos, YouTube, voos, controle de
desktop. Cravar outro nome só adiaria o problema: a família flash já foi
renomeada várias vezes, e o alias "gemini-flash-latest" mudou de destino.

Aqui a escolha é feita perguntando à API o que a chave enxerga, uma vez por
sessão, com preferência pelos modelos mais novos. Se a consulta falhar, cai
para uma lista de nomes conhecidos, e o comportamento é o de antes.
"""
from __future__ import annotations

import json
import re
import sys
import threading
from pathlib import Path


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


CONFIG_PATH = _base_dir() / "config" / "api_keys.json"

# Usados só se a consulta à API não for possível.
_FALLBACK_FLASH = "gemini-flash-latest"
_FALLBACK_LITE = "gemini-flash-lite-latest"

_lock = threading.Lock()
_cache: dict[str, str] = {}


def _api_key() -> str:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))["gemini_api_key"]


def _versao(nome: str) -> tuple:
    """Ordena por número de versão: 3.6 vem antes de 3.5, que vem antes de 2.5."""
    m = re.search(r"gemini-(\d+)(?:\.(\d+))?", nome)
    if not m:
        return (0, 0)
    return (int(m.group(1)), int(m.group(2) or 0))


def _listar() -> list[str]:
    """Nomes de modelos que a chave pode usar para generateContent."""
    from google import genai

    # O cliente precisa ficar vivo em uma variável durante toda a iteração:
    # models.list() devolve um pager preguiçoso, e um cliente temporário é
    # coletado antes de a paginação terminar, resultando em
    # "Cannot send a request, as the client has been closed".
    cliente = genai.Client(api_key=_api_key())
    modelos = list(cliente.models.list())

    disponiveis = []
    for m in modelos:
        acoes = set(getattr(m, "supported_actions", None) or [])
        if "generateContent" in acoes:
            disponiveis.append((m.name or "").replace("models/", ""))
    return disponiveis


def _escolher(lite: bool) -> str:
    modelos = _listar()

    # "lite" é a variante barata e rápida; sem ela, serve qualquer flash.
    def elegivel(nome: str) -> bool:
        if "flash" not in nome:
            return False
        # Previews e modelos de nicho (imagem, tts, thinking) não servem aqui.
        if any(t in nome for t in ("image", "tts", "audio", "thinking", "preview")):
            return False
        return ("lite" in nome) if lite else ("lite" not in nome)

    candidatos = [n for n in modelos if elegivel(n)]
    if not candidatos and lite:
        candidatos = [n for n in modelos if "flash" in n and "preview" not in n]
    if not candidatos:
        candidatos = [n for n in modelos if "flash" in n]

    if not candidatos:
        raise RuntimeError("nenhum modelo flash disponível para esta chave")

    # Mais novo primeiro; nomes sem sufixo de data ganham dos snapshots.
    candidatos.sort(key=lambda n: (_versao(n), -len(n)), reverse=True)
    return candidatos[0]


def _resolver(chave_cache: str, lite: bool, fallback: str) -> str:
    if chave_cache in _cache:
        return _cache[chave_cache]

    with _lock:
        if chave_cache in _cache:      # outra thread resolveu enquanto esperávamos
            return _cache[chave_cache]
        try:
            escolhido = _escolher(lite)
            print(f"[Gemini] Modelo {chave_cache}: {escolhido}")
        except Exception as e:
            escolhido = fallback
            print(f"[Gemini] Não consegui listar os modelos ({e}). Usando {escolhido}.")
        _cache[chave_cache] = escolhido
        return escolhido


def flash() -> str:
    """O melhor modelo flash que esta chave pode usar."""
    return _resolver("flash", lite=False, fallback=_FALLBACK_FLASH)


def flash_lite() -> str:
    """A variante leve, para tarefas curtas de classificação."""
    return _resolver("flash-lite", lite=True, fallback=_FALLBACK_LITE)
