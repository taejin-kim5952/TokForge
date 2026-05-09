"""RAG — 문서를 청킹·임베딩·검색."""

import sqlite3
from pathlib import Path

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer


# 설정
RAG_DIR = Path(__file__).parent.parent.parent / "storage"
DB_PATH = RAG_DIR / "rag.db"
INDEX_PATH = RAG_DIR / "rag.faiss"
EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
EMBEDDING_DIM = 384

CHUNK_SIZE = 500       # 한 chunk 의 글자 수
CHUNK_OVERLAP = 50     # chunk 간 겹침 (문맥 유지)
TOP_K = 5              # 검색 시 상위 몇 개를 가져올지


def chunk_text(text: str) -> list[str]:
    """긴 텍스트를 CHUNK_SIZE 단위로 자르기 (overlap 포함)."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + CHUNK_SIZE
        chunks.append(text[start:end])
        start += CHUNK_SIZE - CHUNK_OVERLAP
    return chunks


class RAGStore:
    """문서 chunk 저장 + 검색."""

    def __init__(self):
        RAG_DIR.mkdir(parents=True, exist_ok=True)
        self.model = SentenceTransformer(EMBEDDING_MODEL)
        self._init_db()
        self._init_index()

    def _init_db(self):
        """SQLite 테이블 — chunk 원문 + 출처."""
        conn = sqlite3.connect(DB_PATH)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        conn.close()

    def _init_index(self):
        """FAISS 인덱스 로드 또는 생성. (Windows 한글 경로 우회)"""
        if INDEX_PATH.exists():
            data = np.frombuffer(INDEX_PATH.read_bytes(), dtype=np.uint8)
            self.index = faiss.deserialize_index(data)
        else:
            self.index = faiss.IndexFlatIP(EMBEDDING_DIM)

    def _save_index(self):
        """FAISS 인덱스 저장. (Windows 한글 경로 우회)"""
        INDEX_PATH.write_bytes(faiss.serialize_index(self.index).tobytes())

    def _embed(self, text: str) -> np.ndarray:
        vec = self.model.encode(text, normalize_embeddings=True)
        return vec.astype("float32").reshape(1, -1)

    def add_document(self, source: str, text: str) -> int:
        """문서 → chunk 분할 → SQLite + FAISS 저장. 저장된 chunk 수 반환."""
        chunks = chunk_text(text)
        if not chunks:
            return 0

        conn = sqlite3.connect(DB_PATH)
        for chunk in chunks:
            conn.execute(
                "INSERT INTO chunks (source, content) VALUES (?, ?)",
                (source, chunk),
            )
            vec = self._embed(chunk)
            self.index.add(vec)
        conn.commit()
        conn.close()

        self._save_index()
        return len(chunks)

    def search(self, query: str, k: int = TOP_K) -> list[dict]:
        """질문과 유사한 chunk 상위 k 개 반환."""
        if self.index.ntotal == 0:
            return []
        vec = self._embed(query)
        distances, indices = self.index.search(vec, k=min(k, self.index.ntotal))

        conn = sqlite3.connect(DB_PATH)
        results = []
        for rank, (idx, score) in enumerate(zip(indices[0], distances[0])):
            row_id = int(idx) + 1
            cursor = conn.execute(
                "SELECT source, content FROM chunks WHERE id = ?", (row_id,)
            )
            row = cursor.fetchone()
            if row:
                results.append({
                    "rank": rank + 1,
                    "score": float(score),
                    "source": row[0],
                    "content": row[1],
                })
        conn.close()
        return results

    def stats(self) -> dict:
        """RAG 통계."""
        conn = sqlite3.connect(DB_PATH)
        chunk_count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        source_count = conn.execute(
            "SELECT COUNT(DISTINCT source) FROM chunks"
        ).fetchone()[0]
        conn.close()
        return {
            "total_chunks": chunk_count,
            "total_sources": source_count,
            "index_size": self.index.ntotal,
            "chunk_size": CHUNK_SIZE,
            "chunk_overlap": CHUNK_OVERLAP,
        }


# 싱글톤
_rag: RAGStore | None = None


def get_rag() -> RAGStore:
    global _rag
    if _rag is None:
        _rag = RAGStore()
    return _rag
