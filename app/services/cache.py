"""의미 캐시 — 같은/비슷한 질문은 즉시 응답."""

import hashlib
import json
import sqlite3
from pathlib import Path

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer


# 설정
CACHE_DIR = Path(__file__).parent.parent.parent / "storage"
DB_PATH = CACHE_DIR / "cache.db"
INDEX_PATH = CACHE_DIR / "cache.faiss"
EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
SIMILARITY_THRESHOLD = 0.90   # 0.90 이상이면 캐시 히트
EMBEDDING_DIM = 384


class SemanticCache:
    """임베딩 기반 의미 캐시."""

    def __init__(self):
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self.model = SentenceTransformer(EMBEDDING_MODEL)
        self._init_db()
        self._init_index()

    def _init_db(self):
        """SQLite 테이블 초기화."""
        conn = sqlite3.connect(DB_PATH)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
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
            # 코사인 유사도 = 정규화된 벡터의 내적
            self.index = faiss.IndexFlatIP(EMBEDDING_DIM)

    def _save_index(self):
        """FAISS 인덱스 저장. (Windows 한글 경로 우회)"""
        INDEX_PATH.write_bytes(faiss.serialize_index(self.index).tobytes())

    def _embed(self, text: str) -> np.ndarray:
        """문장을 임베딩 벡터로 변환 (정규화)."""
        vec = self.model.encode(text, normalize_embeddings=True)
        return vec.astype("float32").reshape(1, -1)

    def lookup(self, question: str) -> dict | None:
        """비슷한 질문이 있으면 응답 dict 반환, 없으면 None."""
        if self.index.ntotal == 0:
            return None
        vec = self._embed(question)
        distances, indices = self.index.search(vec, k=1)
        similarity = float(distances[0][0])
        if similarity < SIMILARITY_THRESHOLD:
            return None
        # FAISS index 의 row 가 SQLite id (1-based)
        row_id = int(indices[0][0]) + 1
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.execute("SELECT answer FROM cache WHERE id = ?", (row_id,))
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None
        return json.loads(row[0])

    def save(self, question: str, answer: dict):
        """질문+응답 dict 저장 (JSON 직렬화)."""
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "INSERT INTO cache (question, answer) VALUES (?, ?)",
            (question, json.dumps(answer, ensure_ascii=False)),
        )
        conn.commit()
        conn.close()
        # FAISS 인덱스에 추가
        vec = self._embed(question)
        self.index.add(vec)
        self._save_index()

    def stats(self) -> dict:
        """캐시 통계."""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.execute("SELECT COUNT(*) FROM cache")
        count = cursor.fetchone()[0]
        conn.close()
        return {
            "total_cached": count,
            "index_size": self.index.ntotal,
            "threshold": SIMILARITY_THRESHOLD,
        }


# 싱글톤 (서버 시작 시 1회만 모델 로드)
_cache: SemanticCache | None = None


def get_cache() -> SemanticCache:
    global _cache
    if _cache is None:
        _cache = SemanticCache()
    return _cache
