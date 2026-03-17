from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
import json
import re

import fitz

from opspilot.ingest.official_clients import sanitize_filename


WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class PageBlock:
    page: int
    block_index: int
    text: str
    bbox: tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class BronzeChunk:
    chunk_id: str
    page_start: int
    page_end: int
    text: str
    char_count: int
    paragraph_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_text(text: str) -> str:
    normalized = WHITESPACE_RE.sub(" ", text.replace("\u3000", " ").replace("\xa0", " ")).strip()
    return normalized


def extract_page_blocks(pdf_path: Path) -> list[PageBlock]:
    document = fitz.open(pdf_path)
    blocks: list[PageBlock] = []
    try:
        for page_index in range(document.page_count):
            page = document.load_page(page_index)
            raw_blocks = page.get_text("blocks")
            sorted_blocks = sorted(raw_blocks, key=lambda item: (round(item[1], 1), round(item[0], 1)))
            for block_index, block in enumerate(sorted_blocks):
                text = normalize_text(block[4])
                if not text:
                    continue
                blocks.append(
                    PageBlock(
                        page=page_index + 1,
                        block_index=block_index,
                        text=text,
                        bbox=(float(block[0]), float(block[1]), float(block[2]), float(block[3])),
                    )
                )
    finally:
        document.close()
    return blocks


def build_chunks(
    blocks: list[PageBlock],
    *,
    report_id: str,
    target_chars: int = 900,
    min_chars: int = 180,
) -> list[BronzeChunk]:
    chunks: list[BronzeChunk] = []
    buffer: list[PageBlock] = []
    current_chars = 0

    def flush() -> None:
        nonlocal buffer, current_chars
        if not buffer:
            return
        text = "\n".join(item.text for item in buffer)
        chunk = BronzeChunk(
            chunk_id=f"{report_id}-chunk-{len(chunks) + 1:04d}",
            page_start=buffer[0].page,
            page_end=buffer[-1].page,
            text=text,
            char_count=len(text),
            paragraph_count=len(buffer),
        )
        chunks.append(chunk)
        buffer = []
        current_chars = 0

    for block in blocks:
        block_len = len(block.text)
        if buffer and current_chars >= min_chars and current_chars + block_len > target_chars:
            flush()
        buffer.append(block)
        current_chars += block_len

    flush()
    return chunks


def summarize_report(pdf_path: Path, blocks: list[PageBlock], chunks: list[BronzeChunk]) -> dict[str, Any]:
    title = blocks[0].text[:120] if blocks else pdf_path.stem
    pages = max((block.page for block in blocks), default=0)
    total_chars = sum(len(block.text) for block in blocks)
    return {
        "report_id": sanitize_filename(pdf_path.stem),
        "file_name": pdf_path.name,
        "file_path": str(pdf_path),
        "title_guess": title,
        "page_count": pages,
        "block_count": len(blocks),
        "chunk_count": len(chunks),
        "char_count": total_chars,
    }


def write_page_json(path: Path, blocks: list[PageBlock], metadata: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "metadata": metadata,
        "pages": [
            {
                "page": page_number,
                "blocks": [
                    {
                        "block_index": block.block_index,
                        "text": block.text,
                        "bbox": block.bbox,
                    }
                    for block in blocks
                    if block.page == page_number
                ],
            }
            for page_number in sorted({block.page for block in blocks})
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_chunks_jsonl(path: Path, chunks: list[BronzeChunk], metadata: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for chunk in chunks:
            row = {**metadata, **chunk.to_dict()}
            file.write(json.dumps(row, ensure_ascii=False) + "\n")
