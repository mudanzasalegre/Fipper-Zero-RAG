"""Line-aware chunks for Markdown, reStructuredText, HTML text and source code."""
from __future__ import annotations
from dataclasses import dataclass
import re

@dataclass(frozen=True)
class Chunk:
    content: str
    line_start: int
    line_end: int
    heading: str


def chunk_text(text: str, *, chunk_size: int = 1300, overlap: int = 220) -> list[Chunk]:
    if chunk_size < 200 or not 0 <= overlap < chunk_size:
        raise ValueError("Invalid chunk size/overlap")
    lines = text.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    if not any(line.strip() for line in lines):
        return []
    # Keep code fences and lines intact. Long lines are truncated at ingestion max-size.
    output: list[Chunk] = []
    i = 0
    heading = ""
    while i < len(lines):
        while i < len(lines) and not lines[i].strip():
            i += 1
        if i >= len(lines):
            break
        start = i
        total = 0
        current_heading = heading
        while i < len(lines):
            line = lines[i]
            if total and total + len(line) + 1 > chunk_size:
                break
            if re.match(r"^\s{0,3}#{1,6}\s+", line):
                heading = re.sub(r"^\s*#+\s+", "", line).strip()
                if i > start and total >= chunk_size // 2:
                    break
                current_heading = heading
            total += len(line) + 1
            i += 1
            if total >= chunk_size:
                break
        if i == start:  # a single oversized source line
            i += 1
        snippet = "\n".join(lines[start:i]).strip()
        if snippet:
            output.append(Chunk(snippet[:max(chunk_size * 2, 2000)], start + 1, i, current_heading))
        if i >= len(lines):
            break
        back = 0
        j = i
        while j > start + 1 and back < overlap:
            j -= 1
            back += len(lines[j]) + 1
        i = max(start + 1, j)
    return output
