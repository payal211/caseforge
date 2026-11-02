"""Tiny dependency-free document retrieval (TF-IDF over markdown sections).
Swap DocIndex for an embedding/pgvector implementation later; the interface
(search -> list[Citation]) stays the same."""
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .schema import Citation

_TOKEN = re.compile(r"[a-z0-9_\-]+")
_STOP = {"the", "and", "for", "with", "that", "this", "from", "are", "was", "has",
         "have", "not", "but", "any", "all", "its", "into", "than", "then", "when"}


def _tok(text: str) -> list[str]:
    return [w for w in _TOKEN.findall(text.lower()) if len(w) > 2 and w not in _STOP]


@dataclass
class Chunk:
    doc: str
    section: str
    text: str
    tf: Counter
    length: int


class DocIndex:
    def __init__(self, docs_dir: Path):
        self.chunks: list[Chunk] = []
        for path in sorted(Path(docs_dir).glob("*.md")):
            self._load(path)
        n = max(len(self.chunks), 1)
        df: Counter = Counter()
        for c in self.chunks:
            df.update(set(c.tf))
        self.idf = {t: math.log(1 + n / d) for t, d in df.items()}

    def _load(self, path: Path) -> None:
        section, buf = None, []

        def flush():
            if section and buf:
                text = "\n".join(buf).strip()
                toks = _tok(section + " " + text)
                self.chunks.append(Chunk(path.name, section, text, Counter(toks), len(toks) or 1))

        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("## "):
                flush()
                section, buf = line[3:].strip(), []
            elif section is not None:
                buf.append(line)
        flush()

    def search(self, query: str, k: int = 3) -> list[Citation]:
        q = Counter(_tok(query))
        scored = []
        for c in self.chunks:
            s = sum(self.idf.get(t, 0) * c.tf[t] * qn for t, qn in q.items() if t in c.tf)
            s = s / math.sqrt(c.length)
            if s > 0:
                scored.append((s, c))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [Citation(doc=c.doc, section=c.section, excerpt=c.text[:900], score=round(s, 3))
                for s, c in scored[:k]]
