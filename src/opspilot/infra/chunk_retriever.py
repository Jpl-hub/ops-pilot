from __future__ import annotations

import asyncio
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
#  Tokenizer
# ---------------------------------------------------------------------------

def tokenize(text: str) -> list[str]:
    """Extract Chinese characters and ASCII words for BM25 inverted index."""
    return [c for c in re.findall(r'[a-zA-Z0-9]+|[\u4e00-\u9fa5]', text.lower())]


# ---------------------------------------------------------------------------
#  Period helpers
# ---------------------------------------------------------------------------

_PERIOD_KEYWORDS: dict[str, str] = {
    "第一季度": "Q1",
    "半年度": "H1",
    "半年报": "H1",
    "第三季度": "Q3",
    "年度报告": "FY",
    "年报": "FY",
}


def _infer_period_from_chunk(chunk: dict) -> str | None:
    """
    Infer report period from the chunk's title / report_type fields.

    Returns period strings like '2024Q1', '2024H1', '2024Q3', '2024FY', or None.
    """
    # Prefer structured report_type field if available
    report_type: str = chunk.get("report_type", "") or ""
    title: str = chunk.get("title", "") or ""
    text_for_search = report_type + title

    year_match = re.search(r'(\d{4})年', text_for_search)
    if not year_match:
        return None
    year = year_match.group(1)

    for keyword, suffix in _PERIOD_KEYWORDS.items():
        if keyword in text_for_search:
            # Disambiguate FY: "年度报告" must not co-occur with 季度/半年
            if suffix == "FY" and ("季度" in text_for_search or "半年" in text_for_search):
                continue
            return f"{year}{suffix}"
    return None


def _period_matches(chunk: dict, report_period: str) -> bool:
    """Return True if the chunk's inferred period equals report_period."""
    inferred = _infer_period_from_chunk(chunk)
    if inferred is None:
        # Fall back to year-in-title heuristic
        year = report_period[:4]
        return year in (chunk.get("title", "") + chunk.get("report_type", ""))
    return inferred == report_period


# ---------------------------------------------------------------------------
#  LocalChunkRetriever
# ---------------------------------------------------------------------------

class LocalChunkRetriever:
    """
    2-stage Hybrid RAG retriever over the bronze JSONL chunk store.

    Stage 1: BM25 lexical retrieval (from local JSONL files)
    Stage 2: Dense ANN retrieval (from pgvector via VectorStore)
    Fusion:  Reciprocal Rank Fusion (RRF, k=60) on stable chunk_id keys
    Rerank:  LLM Zero-Shot reranker (RankGPT style, top-15 → top-k)
    """

    def __init__(self, bronze_chunks_dir: Path) -> None:
        self.bronze_chunks_dir = Path(bronze_chunks_dir)

    # ------------------------------------------------------------------
    #  Public interface
    # ------------------------------------------------------------------

    def search(
        self,
        security_code: str,
        query: str,
        report_period: str | None = None,
        top_k: int = 8,
    ) -> list[dict[str, Any]]:
        """Pure BM25 search (synchronous, no LLM / vector calls)."""
        chunks = self._load_chunks(security_code, report_period)
        if not chunks:
            return []
        return self._bm25_rank(chunks, query, top_k)

    async def hybrid_search(
        self,
        security_code: str,
        query: str,
        dsn: str,
        report_period: str | None = None,
        top_k: int = 6,
    ) -> list[dict[str, Any]]:
        """
        Full Hybrid RAG pipeline:
          BM25(top-20) ⊕ Dense-ANN(top-20) → RRF → LLM-Rerank(top-k)

        On-demand embedding: if the VectorStore lacks records for this
        (security_code, report_period), embeddings are built and upserted
        before the dense search runs.
        """
        from opspilot.infra.vector_store import VectorStore
        from opspilot.core.llm import get_embedding, get_embeddings, rerank_chunks

        chunks = self._load_chunks(security_code, report_period)
        if not chunks:
            return []

        v_store = VectorStore(dsn)
        period_key = report_period or "all"

        # ---- Stage 0: build embeddings on-demand if missing ----
        if not v_store.has_records(security_code, period_key):
            texts = [c.get("text", "")[:2000] for c in chunks]
            embeddings: list[list[float]] = []
            for i in range(0, len(texts), 100):
                batch = await get_embeddings(texts[i : i + 100])
                embeddings.extend(batch)
                if i + 100 < len(texts):
                    await asyncio.sleep(0.05)

            for c, emb in zip(chunks, embeddings):
                c["embedding"] = emb
            inserted = v_store.add_chunks(security_code, period_key, chunks)
            logger.debug("Upserted %d new embeddings for %s/%s", inserted, security_code, period_key)

        # ---- Stage 1: BM25 lexical retrieval ----
        bm25_results = self._bm25_rank(chunks, query, top_k=20)

        # ---- Stage 2: Dense ANN retrieval ----
        q_emb = await get_embedding(query)
        v_results = v_store.search(
            security_code, q_emb, report_period=period_key, top_k=20
        )

        # ---- Stage 3: Reciprocal Rank Fusion (RRF, k=60) ----
        # Key fix: use stable chunk_id as fusion uid, not text[:100]
        fused_scores: dict[str, float] = {}
        lookup: dict[str, dict] = {}
        k = 60

        for rank, c in enumerate(bm25_results):
            uid = c.get("chunk_id") or c.get("text", "")[:100]
            fused_scores[uid] = fused_scores.get(uid, 0.0) + 1.0 / (k + rank + 1)
            lookup[uid] = c

        for rank, vr in enumerate(v_results):
            # VectorStore.search now returns chunk_id
            uid = vr.get("chunk_id") or vr.get("text", "")[:100]
            fused_scores[uid] = fused_scores.get(uid, 0.0) + 1.0 / (k + rank + 1)
            if uid not in lookup:
                # Reconstruct a chunk-like dict from VectorStore result
                lookup[uid] = {
                    "chunk_id": vr.get("chunk_id", uid),
                    "title": vr.get("title", ""),
                    "text": vr.get("text", ""),
                    "page_start": vr.get("page_start", 0),
                }

        sorted_uids = sorted(fused_scores, key=lambda u: fused_scores[u], reverse=True)
        rrf_top = [lookup[u] for u in sorted_uids[:15]]

        # ---- Stage 4: LLM Zero-Shot Reranker (RankGPT style) ----
        return await rerank_chunks(query, rrf_top, top_k)

    # ------------------------------------------------------------------
    #  Internal helpers
    # ------------------------------------------------------------------

    def _load_chunks(
        self,
        security_code: str,
        report_period: str | None = None,
    ) -> list[dict[str, Any]]:
        """Load bronze JSONL chunks for a given security code and optional period."""
        target_dir: Path | None = None
        for exchange in ("SSE", "SZSE"):
            p = self.bronze_chunks_dir / exchange / security_code
            if p.is_dir():
                target_dir = p
                break
        if target_dir is None:
            return []

        chunks: list[dict[str, Any]] = []
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
                    if report_period and not _period_matches(chunk, report_period):
                        continue
                    chunks.append(chunk)
        return chunks

    def _bm25_rank(
        self,
        chunks: list[dict[str, Any]],
        query: str,
        top_k: int,
    ) -> list[dict[str, Any]]:
        """Classic BM25 ranking (k1=1.5, b=0.75)."""
        query_terms = tokenize(query)
        if not query_terms:
            return chunks[:top_k]

        n = len(chunks)
        df: Counter[str] = Counter()
        chunk_tfs: list[Counter[str]] = []
        doc_lens: list[int] = []

        for c in chunks:
            terms = tokenize(c.get("text", ""))
            doc_lens.append(len(terms))
            tf: Counter[str] = Counter(terms)
            chunk_tfs.append(tf)
            for term in set(terms):
                df[term] += 1

        avgdl = sum(doc_lens) / n if n else 1
        k1, b = 1.5, 0.75
        scores: list[tuple[float, dict]] = []

        for i, (c, tf, dl) in enumerate(zip(chunks, chunk_tfs, doc_lens)):
            score = 0.0
            for q in query_terms:
                if q not in df:
                    continue
                idf = math.log(1 + (n - df[q] + 0.5) / (df[q] + 0.5))
                tf_val = tf[q]
                score += idf * (tf_val * (k1 + 1)) / (tf_val + k1 * (1 - b + b * dl / avgdl))
            scores.append((score, c))

        scores.sort(key=lambda x: x[0], reverse=True)
        result = []
        for rank, (s, c) in enumerate(scores):
            if s <= 0:
                break
            c = dict(c)  # shallow copy to avoid mutating original
            c["bm25_rank"] = rank + 1
            result.append(c)
            if len(result) >= top_k:
                break
        return result


import logging
logger = logging.getLogger(__name__)
