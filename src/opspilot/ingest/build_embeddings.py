"""
build_embeddings.py — Offline incremental embedding builder for Hybrid RAG.

Usage:
    # Embed ALL companies, ALL periods (first-time setup)
    python -m opspilot.ingest.build_embeddings

    # Embed a single company
    python -m opspilot.ingest.build_embeddings --company 600438

    # Embed a specific company + period
    python -m opspilot.ingest.build_embeddings --company 600438 --period 2024Q3

    # Dry run (count chunks without embedding)
    python -m opspilot.ingest.build_embeddings --dry-run

Environment:
    OPS_PILOT_OPENAI_API_KEY  — required
    OPS_PILOT_POSTGRES_DSN    — required (default: localhost postgres)
    OPS_PILOT_BRONZE_DATA_PATH
    OPS_PILOT_SILVER_DATA_PATH
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("build_embeddings")


# ---------------------------------------------------------------------------
#  Period inference (mirrors chunk_retriever._infer_period_from_chunk)
# ---------------------------------------------------------------------------

_PERIOD_KEYWORDS: dict[str, str] = {
    "第一季度": "Q1",
    "半年度": "H1",
    "半年报": "H1",
    "第三季度": "Q3",
    "年度报告": "FY",
    "年报": "FY",
}


def _infer_period(title: str, report_type: str = "") -> str | None:
    text = (report_type or "") + (title or "")
    m = re.search(r"(\d{4})年", text)
    if not m:
        return None
    year = m.group(1)
    for keyword, suffix in _PERIOD_KEYWORDS.items():
        if keyword in text:
            if suffix == "FY" and ("季度" in text or "半年" in text):
                continue
            return f"{year}{suffix}"
    return None


# ---------------------------------------------------------------------------
#  Core logic
# ---------------------------------------------------------------------------

async def embed_company(
    security_code: str,
    chunks_dir: Path,
    vector_store: "VectorStore",  # type: ignore[name-defined]
    period_filter: str | None,
    dry_run: bool,
    batch_size: int = 100,
) -> dict:
    """Embed and upsert all chunks for one company. Returns stats dict."""
    from opspilot.core.llm import get_embeddings

    target_dir: Path | None = None
    for exchange in ("SSE", "SZSE"):
        p = chunks_dir / exchange / security_code
        if p.is_dir():
            target_dir = p
            break
    if target_dir is None:
        logger.warning("No bronze chunks dir for %s", security_code)
        return {"security_code": security_code, "chunks": 0, "inserted": 0, "skipped": 0}

    # Group chunks by (security_code, inferred_period)
    period_chunks: dict[str, list[dict]] = {}
    for jsonl_file in sorted(target_dir.glob("*.jsonl")):
        with open(jsonl_file, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue
                period = _infer_period(chunk.get("title", ""), chunk.get("report_type", ""))
                if period is None:
                    period = "unknown"
                if period_filter and period != period_filter:
                    continue
                period_chunks.setdefault(period, []).append(chunk)

    total_chunks = sum(len(v) for v in period_chunks.values())
    total_inserted = 0

    if dry_run:
        logger.info("[DRY-RUN] %s: %d chunks across periods %s",
                    security_code, total_chunks, list(period_chunks.keys()))
        return {"security_code": security_code, "chunks": total_chunks, "inserted": 0, "skipped": total_chunks}

    for period, chunks in period_chunks.items():
        # Skip if already fully embedded (has_records is approximate)
        if vector_store.has_records(security_code, period):
            logger.info("  %s/%s — already has records, skipping", security_code, period)
            continue

        logger.info("  Embedding %s/%s: %d chunks …", security_code, period, len(chunks))
        t0 = time.perf_counter()

        texts = [c.get("text", "")[:2000] for c in chunks]
        embeddings: list[list[float]] = []
        for i in range(0, len(texts), batch_size):
            batch_emb = await get_embeddings(texts[i : i + batch_size])
            embeddings.extend(batch_emb)
            if i + batch_size < len(texts):
                await asyncio.sleep(0.05)  # respect rate limits

        for chunk, emb in zip(chunks, embeddings):
            chunk["embedding"] = emb

        inserted = vector_store.add_chunks(security_code, period, chunks)
        elapsed = time.perf_counter() - t0
        logger.info("  → inserted %d / %d in %.1fs", inserted, len(chunks), elapsed)
        total_inserted += inserted

    return {
        "security_code": security_code,
        "chunks": total_chunks,
        "inserted": total_inserted,
        "skipped": total_chunks - total_inserted,
    }


async def run(args: argparse.Namespace) -> None:
    from opspilot.config import get_settings
    from opspilot.infra.vector_store import VectorStore

    settings = get_settings()

    if not settings.openai_api_key:
        logger.error("OPS_PILOT_OPENAI_API_KEY is not set — cannot generate embeddings.")
        sys.exit(1)

    chunks_dir = settings.bronze_data_path / "chunks"
    if not chunks_dir.exists():
        logger.error("Bronze chunks directory not found: %s", chunks_dir)
        sys.exit(1)

    vector_store = VectorStore(settings.postgres_dsn)
    logger.info("VectorStore initialised at %s", settings.postgres_dsn)

    # Collect security codes to process
    if args.company:
        security_codes = [args.company]
    else:
        codes: set[str] = set()
        for exchange_dir in chunks_dir.iterdir():
            if exchange_dir.is_dir():
                for code_dir in exchange_dir.iterdir():
                    if code_dir.is_dir():
                        codes.add(code_dir.name)
        security_codes = sorted(codes)

    logger.info("Processing %d company/ies%s",
                len(security_codes),
                f" (period={args.period})" if args.period else "")

    total_stats = {"chunks": 0, "inserted": 0, "skipped": 0}
    for sec_code in security_codes:
        stats = await embed_company(
            security_code=sec_code,
            chunks_dir=chunks_dir,
            vector_store=vector_store,
            period_filter=args.period,
            dry_run=args.dry_run,
        )
        for key in ("chunks", "inserted", "skipped"):
            total_stats[key] += stats[key]

    logger.info(
        "Done. Total: %d chunks, %d newly inserted, %d skipped (already embedded).",
        total_stats["chunks"],
        total_stats["inserted"],
        total_stats["skipped"],
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build embeddings for OpsPilot-X bronze chunks into pgvector."
    )
    parser.add_argument(
        "--company",
        metavar="SECURITY_CODE",
        help="Embed only this security code (e.g. 600438). Default: all companies.",
    )
    parser.add_argument(
        "--period",
        metavar="PERIOD",
        help="Embed only this period (e.g. 2024Q3). Default: all periods.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count chunks only; do not call the embedding API or write to DB.",
    )
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
