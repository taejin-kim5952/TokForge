"""RAG — LangChain 기반 문서 청킹·검색.

프로젝트별로 분리된 FAISS 인덱스를 사용합니다:
  storage/rag_index/global/     — project_id=None (기존 글로벌)
  storage/rag_index/project_1/  — project_id=1
  storage/rag_index/project_2/  — project_id=2
  ...
"""

import pickle
from pathlib import Path

import faiss
import numpy as np
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter


# 설정
RAG_BASE_DIR = Path(__file__).parent.parent.parent / "storage" / "rag_index"
EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50
TOP_K = 5

# 공유 임베딩 모델 (한 번만 로드)
_shared_embeddings: HuggingFaceEmbeddings | None = None


def _get_embeddings() -> HuggingFaceEmbeddings:
    global _shared_embeddings
    if _shared_embeddings is None:
        _shared_embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
    return _shared_embeddings


def _rag_dir(project_id: int | None) -> Path:
    if project_id is None:
        return RAG_BASE_DIR / "global"
    return RAG_BASE_DIR / f"project_{project_id}"


class RAGStore:
    """LangChain FAISS 기반 문서 저장소 (프로젝트별 격리)."""

    def __init__(self, project_id: int | None = None):
        self.project_id = project_id
        self.rag_dir = _rag_dir(project_id)
        self.embeddings = _get_embeddings()
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
        )
        self.store: FAISS | None = self._load_or_create()

    def _load_or_create(self) -> FAISS | None:
        """Windows 한글 경로 우회 — LangChain save_local/load_local 대신 수동 직렬화."""
        faiss_path = self.rag_dir / "index.faiss"
        pkl_path = self.rag_dir / "index.pkl"

        if not (faiss_path.exists() and pkl_path.exists()):
            return None

        data = np.frombuffer(faiss_path.read_bytes(), dtype=np.uint8)
        index = faiss.deserialize_index(data)

        with open(pkl_path, "rb") as f:
            docstore, index_to_docstore_id = pickle.load(f)

        return FAISS(
            embedding_function=self.embeddings,
            index=index,
            docstore=docstore,
            index_to_docstore_id=index_to_docstore_id,
        )

    def _save(self) -> None:
        """Windows 한글 경로 우회 — faiss.write_index 대신 serialize."""
        if self.store is None:
            # 모든 문서가 삭제된 경우 파일 제거
            (self.rag_dir / "index.faiss").unlink(missing_ok=True)
            (self.rag_dir / "index.pkl").unlink(missing_ok=True)
            return

        self.rag_dir.mkdir(parents=True, exist_ok=True)
        (self.rag_dir / "index.faiss").write_bytes(
            faiss.serialize_index(self.store.index).tobytes()
        )
        with open(self.rag_dir / "index.pkl", "wb") as f:
            pickle.dump((self.store.docstore, self.store.index_to_docstore_id), f)

    def add_document(self, source: str, text: str) -> int:
        """문서 → 청킹 → 인덱스 추가."""
        chunks = self.splitter.split_text(text)
        if not chunks:
            return 0

        docs = [
            Document(page_content=chunk, metadata={"source": source})
            for chunk in chunks
        ]

        if self.store is None:
            self.store = FAISS.from_documents(docs, self.embeddings)
        else:
            self.store.add_documents(docs)

        self._save()
        return len(chunks)

    def list_sources(self) -> list[dict]:
        """업로드된 문서 소스 목록과 청크 수 반환."""
        if self.store is None:
            return []
        all_docs = list(self.store.docstore._dict.values())
        source_map: dict[str, int] = {}
        for doc in all_docs:
            src = doc.metadata.get("source", "")
            source_map[src] = source_map.get(src, 0) + 1
        return [
            {"source": src, "chunks": count}
            for src, count in sorted(source_map.items())
        ]

    def delete_source(self, source: str) -> int:
        """특정 소스의 모든 청크를 삭제 후 인덱스 재구성.

        FAISS는 개별 벡터 삭제를 지원하지 않으므로 나머지 문서로 인덱스를 재구성합니다.
        """
        if self.store is None:
            return 0

        all_docs = list(self.store.docstore._dict.values())
        remaining = [d for d in all_docs if d.metadata.get("source") != source]
        deleted = len(all_docs) - len(remaining)
        if deleted == 0:
            return 0

        if remaining:
            self.store = FAISS.from_documents(remaining, self.embeddings)
        else:
            self.store = None

        self._save()
        return deleted

    def search(self, query: str, k: int = TOP_K) -> list[dict]:
        """질문과 유사한 chunk 상위 k개 반환."""
        if self.store is None:
            return []

        results = self.store.similarity_search_with_score(query, k=k)
        return [
            {
                "rank": i + 1,
                "score": float(score),
                "source": doc.metadata.get("source", ""),
                "content": doc.page_content,
            }
            for i, (doc, score) in enumerate(results)
        ]

    def stats(self) -> dict:
        if self.store is None:
            return {
                "total_chunks": 0,
                "total_sources": 0,
                "chunk_size": CHUNK_SIZE,
                "chunk_overlap": CHUNK_OVERLAP,
            }
        all_docs = list(self.store.docstore._dict.values())
        sources = {d.metadata.get("source") for d in all_docs}
        return {
            "total_chunks": len(all_docs),
            "total_sources": len(sources),
            "chunk_size": CHUNK_SIZE,
            "chunk_overlap": CHUNK_OVERLAP,
        }


# 프로젝트별 싱글톤 레지스트리
_registry: dict[int | None, RAGStore] = {}


def get_rag(project_id: int | None = None) -> RAGStore:
    if project_id not in _registry:
        _registry[project_id] = RAGStore(project_id)
    return _registry[project_id]


def invalidate_rag(project_id: int | None = None) -> None:
    """업로드/삭제 후 싱글톤을 무효화해 다음 요청 시 재로드."""
    _registry.pop(project_id, None)


def ingest_text_document(project_id: int | None, filename: str, text: str) -> int:
    """텍스트 문서를 청킹·인덱싱. 업로드/삭제 직전 invalidate_rag 호출 권장."""
    invalidate_rag(project_id)
    return get_rag(project_id).add_document(filename, text)
