import logging
from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)

class VectorStore:
    """
    PostgreSQL + pgvector implementation for Semantic RAG.
    Stores and queries document chunks using text-embedding-3-small vectors.
    """
    def __init__(self, dsn: str):
        # We replace the asyncio driver (+asyncpg) string if present with standard psycopg for sync ops
        if dsn.startswith("postgresql+asyncpg"):
            dsn = dsn.replace("postgresql+asyncpg", "postgresql+psycopg")
        self.engine = create_engine(dsn)
        self._init_db()

    def _init_db(self):
        try:
            with self.engine.begin() as conn:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
                conn.execute(text("""
                CREATE TABLE IF NOT EXISTS chunk_embeddings (
                    id SERIAL PRIMARY KEY,
                    company_id VARCHAR(50),
                    report_period VARCHAR(50),
                    title TEXT,
                    content TEXT,
                    embedding vector(1536)
                );
                """))
                # Build an HNSW index for ultra-fast cosine distance vector queries
                conn.execute(text("""
                CREATE INDEX IF NOT EXISTS chunk_emb_idx ON chunk_embeddings 
                USING hnsw (embedding vector_cosine_ops);
                """))
        except Exception as e:
            logger.error(f"Failed to initialize pgvector database: {e}")

    def add_chunks(self, company_id: str, report_period: str, chunks: list[dict]):
        """
        chunks should be a list of dictionaries with keys: 'title', 'text', 'embedding'
        """
        with self.engine.begin() as conn:
            for c in chunks:
                if not c.get("embedding"):
                    continue
                # Ensure embedding is properly stringified for pgvector
                emb_str = f"[{','.join(map(str, c['embedding']))}]"
                conn.execute(
                    text("""
                    INSERT INTO chunk_embeddings (company_id, report_period, title, content, embedding)
                    VALUES (:cid, :rp, :t, :c, :e)
                    """),
                    {"cid": company_id, "rp": report_period or "unknown", "t": c.get("title", ""), "c": c.get("text", ""), "e": emb_str}
                )

    def has_records(self, company_id: str, report_period: str | None = None) -> bool:
        """
        Check if any chunk vectors exist for a given company and period.
        """
        sql = "SELECT 1 FROM chunk_embeddings WHERE company_id = :cid"
        params = {"cid": company_id}
        if report_period:
            sql += " AND report_period = :rp"
            params["rp"] = report_period
        sql += " LIMIT 1"
        with self.engine.connect() as conn:
            return bool(conn.execute(text(sql), params).fetchone())

    def search(self, company_id: str, query_embedding: list[float], report_period: str | None = None, top_k: int = 5) -> list[dict]:
        """
        Retrieves the top_k most semantically relevant chunks for a given query embedding using cosine similarity.
        """
        emb_str = f"[{','.join(map(str, query_embedding))}]"
        query_sql = str("""
            SELECT title, content, 1 - (embedding <=> :q) as similarity
            FROM chunk_embeddings
            WHERE company_id = :cid
        """)
        
        params = {"q": emb_str, "cid": company_id, "k": top_k}
        if report_period:
            query_sql += " AND title LIKE :rp"
            params["rp"] = f"%{report_period[:4]}%"  # Match year in title roughly
            
        query_sql += " ORDER BY embedding <=> :q LIMIT :k"

        with self.engine.connect() as conn:
            rows = conn.execute(text(query_sql), params).fetchall()
            return [{"title": r[0], "text": r[1], "score": float(r[2])} for r in rows]
