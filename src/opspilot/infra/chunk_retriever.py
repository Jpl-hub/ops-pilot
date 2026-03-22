import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

def tokenize(text: str) -> list[str]:
    """Extract Chinese characters and alphanumeric words for inverted indexing."""
    return [c for c in re.findall(r'[a-zA-Z0-9]+|[\u4e00-\u9fa5]', text.lower())]

class LocalChunkRetriever:
    """
    A lightweight, embedded BM25 dense retriever over local JSONL chunks.
    This bypasses the need to spin up a heavy Vector Database cluster while 
    fulfilling the Big Data 'Traceable Data Source' requirements cleanly.
    """
    def __init__(self, bronze_chunks_dir: Path):
        self.bronze_chunks_dir = Path(bronze_chunks_dir)

    def search(self, security_code: str, query: str, report_period: str | None = None, top_k: int = 8) -> list[dict[str, Any]]:
        target_dir = None
        for exchange in ['SSE', 'SZSE']:
            p = self.bronze_chunks_dir / exchange / security_code
            if p.exists() and p.is_dir():
                target_dir = p
                break
        
        if not target_dir:
            return []

        chunks = []
        for jsonl_file in target_dir.glob("*.jsonl"):
            with open(jsonl_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if not line.strip(): 
                        continue
                    try:
                        chunk = json.loads(line)
                        title = chunk.get("title", "")
                        # Simple heuristic: if a target year is provided, require the report title to contain it.
                        if report_period:
                            year = report_period[:4]
                            if year not in title:
                                continue
                        chunks.append(chunk)
                    except json.JSONDecodeError:
                        pass

        if not chunks:
            return []

        # Executing BM25 Scoring
        query_terms = tokenize(query)
        if not query_terms:
            return chunks[:top_k]

        N = len(chunks)
        df = Counter()
        chunk_tfs = []
        doc_lens = []
        
        for c in chunks:
            terms = tokenize(c.get("text", ""))
            doc_lens.append(len(terms))
            tf = Counter(terms)
            chunk_tfs.append(tf)
            for term in set(terms):
                df[term] += 1

        avgdl = sum(doc_lens) / N if N > 0 else 1
        k1 = 1.5
        b = 0.75

        scores = []
        for i in range(N):
            score = 0.0
            dl = doc_lens[i]
            tf = chunk_tfs[i]
            for q in query_terms:
                if q not in df: 
                    continue
                idf = math.log(1 + (N - df[q] + 0.5) / (df[q] + 0.5))
                term_tf = tf[q]
                numerator = term_tf * (k1 + 1)
                denominator = term_tf + k1 * (1 - b + b * (dl / avgdl))
                score += idf * (numerator / denominator)
            scores.append((score, chunks[i]))

        scores.sort(key=lambda x: x[0], reverse=True)
        return [c for s, c in scores[:top_k] if s > 0]
