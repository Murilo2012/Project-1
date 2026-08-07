"""O vault: memória de longo prazo em markdown puro.

Sem banco de dados, de propósito. Três razões:
  1. Você consegue ler e editar tudo que o APEX sabe, com qualquer editor.
  2. Abre direto no Obsidian — os links [[assim]] viram um grafo.
  3. Se este projeto morrer amanhã, sua memória continua sendo uma pasta.

    raw/YYYY-MM-DD/*.md   tudo que foi capturado, cru
    wiki/*.md             conhecimento destilado, o que vale reter
    outputs/*.md          tudo que o APEX entrega

A busca é grep com pontuação, não embeddings. Para um vault pessoal (centenas
de notas, não milhões) isso é rápido, previsível e não precisa de índice.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_STOPWORDS = {
    "a", "o", "e", "de", "da", "do", "em", "um", "uma", "para", "com", "que",
    "no", "na", "os", "as", "dos", "das", "por", "se", "ao", "mais", "meu",
    "minha", "eu", "the", "of", "to", "is",
}


def slugify(text: str, max_length: int = 60) -> str:
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    slug = _SLUG_RE.sub("-", text).strip("-")
    return slug[:max_length] or "nota"


@dataclass
class SearchHit:
    path: str
    title: str
    score: int
    excerpt: str


class Vault:
    def __init__(self, root: Path, max_results: int = 12, max_note_chars: int = 8000):
        self.root = Path(root).expanduser()
        self.max_results = max_results
        self.max_note_chars = max_note_chars
        for section in ("raw", "wiki", "outputs"):
            (self.root / section).mkdir(parents=True, exist_ok=True)

    # -- resolução de caminho ---------------------------------------------

    def resolve(self, relative: str) -> Path:
        """Resolve um caminho relativo ao vault, barrando escape de diretório.

        O modelo escolhe esses caminhos. Sem essa checagem, um '../../..' numa
        alucinação escreve fora do vault.
        """
        candidate = (self.root / relative.lstrip("/\\")).resolve()
        root = self.root.resolve()
        if not candidate.is_relative_to(root):
            raise ValueError(f"caminho fora do vault: {relative}")
        if candidate.suffix == "":
            candidate = candidate.with_suffix(".md")
        return candidate

    def relative(self, path: Path) -> str:
        return path.resolve().relative_to(self.root.resolve()).as_posix()

    # -- escrita ----------------------------------------------------------

    def capture(self, text: str, tags: list[str] | None = None, source: str = "voz") -> str:
        """Joga algo em raw/ com data e hora. É o inbox: captura primeiro,
        organiza depois."""
        now = datetime.now()
        day_dir = self.root / "raw" / now.strftime("%Y-%m-%d")
        day_dir.mkdir(parents=True, exist_ok=True)

        first_line = text.strip().splitlines()[0] if text.strip() else "captura"
        filename = f"{now.strftime('%H%M%S')}-{slugify(first_line, 40)}.md"
        path = day_dir / filename

        front = [
            "---",
            f"data: {now.isoformat(timespec='seconds')}",
            f"fonte: {source}",
        ]
        if tags:
            front.append(f"tags: [{', '.join(tags)}]")
        front.append("---")
        front.append("")

        path.write_text("\n".join(front) + text.strip() + "\n", encoding="utf-8")
        return self.relative(path)

    def write(self, relative: str, content: str, append: bool = False) -> str:
        path = self.resolve(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        if append and path.exists():
            existing = path.read_text(encoding="utf-8").rstrip()
            content = f"{existing}\n\n{content.strip()}\n"
        else:
            content = content.strip() + "\n"
        path.write_text(content, encoding="utf-8")
        return self.relative(path)

    def append_daily_log(self, line: str) -> str:
        """Anexa uma linha ao log do dia. É como o APEX registra o que fez."""
        today = datetime.now()
        path = self.root / "raw" / today.strftime("%Y-%m-%d") / "_log.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(f"# Log de {today.strftime('%d/%m/%Y')}\n\n", encoding="utf-8")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"- {today.strftime('%H:%M')} — {line.strip()}\n")
        return self.relative(path)

    # -- leitura ----------------------------------------------------------

    def read(self, relative: str) -> str:
        path = self.resolve(relative)
        if not path.exists():
            raise FileNotFoundError(f"nota não encontrada: {relative}")
        content = path.read_text(encoding="utf-8-sig", errors="replace")
        if len(content) > self.max_note_chars:
            content = content[: self.max_note_chars] + "\n\n[...nota truncada...]"
        return content

    def list_notes(self, section: str = "", limit: int = 60) -> list[str]:
        base = self.resolve(section) if section else self.root
        if base.suffix == ".md" and not base.is_dir():
            base = base.with_suffix("")
        if not base.exists():
            return []
        notes = sorted(
            base.rglob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True
        )
        return [self.relative(p) for p in notes[:limit]]

    def search(self, query: str) -> list[SearchHit]:
        """Busca por termos. Título vale mais que corpo; nota recente desempata."""
        terms = [
            t for t in re.findall(r"[\wáàâãéêíóôõúüç]+", query.lower())
            if len(t) > 2 and t not in _STOPWORDS
        ]
        if not terms:
            return []

        hits: list[SearchHit] = []
        for path in self.root.rglob("*.md"):
            try:
                content = path.read_text(encoding="utf-8-sig", errors="replace")
            except OSError:
                continue

            lowered = content.lower()
            name = path.stem.lower()

            score = 0
            for term in terms:
                score += lowered.count(term)
                if term in name:
                    score += 8
            if score == 0:
                continue

            hits.append(
                SearchHit(
                    path=self.relative(path),
                    title=self._title_of(content, path),
                    score=score,
                    excerpt=self._excerpt(content, terms),
                )
            )

        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[: self.max_results]

    @staticmethod
    def _title_of(content: str, path: Path) -> str:
        for line in content.splitlines():
            if line.startswith("# "):
                return line[2:].strip()
        return path.stem.replace("-", " ")

    @staticmethod
    def _excerpt(content: str, terms: list[str], width: int = 160) -> str:
        lowered = content.lower()
        for term in terms:
            index = lowered.find(term)
            if index >= 0:
                start = max(0, index - width // 2)
                snippet = content[start: start + width].replace("\n", " ")
                return ("..." if start > 0 else "") + snippet.strip() + "..."
        return content[:width].replace("\n", " ").strip()

    # -- estatística (usada pelo HUD) --------------------------------------

    def stats(self) -> dict[str, int]:
        return {
            section: len(list((self.root / section).rglob("*.md")))
            for section in ("raw", "wiki", "outputs")
        }
