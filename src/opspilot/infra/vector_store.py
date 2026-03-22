from __future__ import annotations

import logging
from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)


class VectorStore:
    """
    PostgreSQL + pgvector implementation for Semantic RAG.

    Schema hardening (2026 edition):
    - chunk_id UNIQUE  : stable deduplication key, matches bronze chunk_id
    - page_start       : enables evidence page-level traceability
    - report_period    : exact-match filter (no more LIKE title heuristic)
    - UPSERT semantics : ON CONFLICT (chunk_id) DO NOTHING — safe for re-ingest
    """

    def __init__(self, dsn: str) -> None:
        if dsn.startswith("postgresql+asyncpg"):
            dsn = dsn.replace("postgresql+asyncpg", "postgresql+psycopg")
        self.engine = create_engine(dsn, pool_pre_ping=True)
        self._init_db()

    # ------------------------------------------------------------------
    #  Schema init / migration
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        try:
            with self.engine.begin() as conn:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))

                # Create table with full schema if it doesn't exist yet
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS chunk_embeddings (
                        id            SERIAL PRIMARY KEY,
                        chunk_id      VARCHAR(300),
                        company_id    VARCHAR(50),
                        report_period VARCHAR(50),
                        title         TEXT,
                        content       TEXT,
                        page_start    INT DEFAULT 0,
                        embedding     vector(1536)
                    );
                """))

                # Migrate existing tables that were created before this schema
                for col_sql in [
                    "ALTER TABLE chunk_embeddings ADD COLUMN IF NOT EXISTS chunk_id   VARCHAR(300);",
                    "ALTER TABLE chunk_embeddings ADD COLUMN IF NOT EXISTS page_start INT DEFAULT 0;",
                ]:
                    conn.execute(text(col_sql))

                # Back-fill chunk_id for legacy rows so UNIQUE can be applied
                conn.execute(text("""
                    UPDATE chunk_embeddings
                    SET chunk_id = 'legacy-' || id::text
                    WHERE chunk_id IS NULL;
                """))

                # Add UNIQUE constraint only if it doesn't exist
                conn.execute(text("""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM pg_constraint
                            WHERE conname = 'uq_chunk_id'
                              AND conrelid = 'chunk_embeddings'::regclass
                        ) THEN
                            ALTER TABLE chunk_embeddings
                                ADD CONSTRAINT uq_chunk_id UNIQUE (chunk_id);
                        END IF;
                    END $$;
                """))

                # HNSW index for cosine distance vector queries
                conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS chunk_emb_hnsw_idx
                    ON chunk_embeddings
                    USING hnsw (embedding vector_cosine_ops);
                """))

                # Compound index for company + period lookups
                conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS chunk_period_idx
                    ON chunk_embeddings (company_id, report_period);
                """))

        except Exception as exc:
            logger.error("Failed to initialize pgvector database: %s", exc)

    # ------------------------------------------------------------------
    #  Write
    # ------------------------------------------------------------------

    def add_chunks(self, company_id: str, report_period: str, chunks: list[dict]) -> int:
        """
        Upsert chunks into the vector store.

        Each chunk dict should have:
            chunk_id  : stable identifier from the bronze layer
            text      : raw text content
            title     : document title
            page_start: starting page number
            embedding : list[float] of length 1536

        Returns the count of newly inserted rows (existing chunk_ids are skipped).
        """
        inserted = 0
        with self.engine.begin() as conn:
            for c in chunks:
                if not c.get("embedding"):
                    continue
                chunk_id = (
                    c.get("chunk_id")
                    or f"{company_id}-{report_period}-{c.get('title', '')[:60]}"
                )
                emb_str = f"[{','.join(map(str, c['embedding']))}]"
                result = conn.execute(
                    text("""
                        INSERT INTO chunk_embeddings
                            (chunk_id, company_id, report_period, title, content, page_start, embedding)
                        VALUES
                            (:chunk_id, :cid, :rp, :t, :c, :pg, :e::vector)
                        ON CONFLICT (chunk_id) DO NOTHING
                    """),
                    {
                        "chunk_id": chunk_id,
                        "cid": company_id,
                        "rp": report_period or "unknown",
                        "t": c.get("title", ""),
                        "c": c.get("text", ""),
                        "pg": c.get("page_start", 0),
                        "e": emb_str,
                    },
                )
                inserted += result.rowcount
        return inserted

    # ------------------------------------------------------------------
    #  Read
    # ------------------------------------------------------------------

    def has_records(self, company_id: str, report_period: str | None = None) -> bool:
        """Return True if any embeddings exist for the given company (and period)."""
        sql = "SELECT 1 FROM chunk_embeddings WHERE company_id = :cid"
        params: dict = {"cid": company_id}
        if report_period:
            sql += " AND report_period = :rp"
            params["rp"] = report_period
        sql += " LIMIT 1"
        with self.engine.connect() as conn:
            return bool(conn.execute(text(sql), params).fetchone())

    def search(
        self,
        company_id: str,
        query_embedding: list[float],
        report_period: str | None = None,
        top_k: int = 5,
    ) -> list[dict]:
        """
        Cosine-similarity ANN search via pgvector HNSW.

        Returns dicts with keys: chunk_id, title, text, page_start, score.
        Uses exact report_period column match (not a LIKE title heuristic).
        """
        emb_str = f"[{','.join(map(str, query_embedding))}]"
        sql = """
            SELECT chunk_id, title, content, page_start,
                   1 - (embedding <=> CAST(:q AS vector)) AS similarity
            FROM chunk_embeddings
            WHERE company_id = :cid
        """
        params: dict = {"q": emb_str, "cid": company_id, "k": top_k}
        if report_period:
            sql += " AND report_period = :rp"
            params["rp"] = report_period
        sql += " ORDER BY embedding <=> CAST(:q AS vector) LIMIT :k"

        with self.engine.connect() as conn:
            rows = conn.execute(text(sql), params).fetchall()

        return [
            {
                "chunk_id": r[0],
                "title": r[1],
                "text": r[2],
                "page_start": r[3],
                "score": float(r[4]),
            }
            for r in rows
        ]
