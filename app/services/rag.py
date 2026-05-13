"""RAG — LangChain 기반 문서 청킹·검색."""

import pickle
from pathlib import Path

import faiss
import numpy as np
from langchain_community.vectorstores import FAISS
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document


# 설정
RAG_DIR = Path(__file__).parent.parent.parent / "storage" / "rag_index"
EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50
TOP_K = 5


class RAGStore:
    """LangChain FAISS 기반 문서 저장소."""

    def __init__(self):
        self.embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
        )
        self.store = self._load_or_create()

    def _load_or_create(self) -> FAISS:
        """Windows 한글 경로 우회 — LangChain save_local/load_local 대신 수동 직렬화."""
        faiss_path = RAG_DIR / "index.faiss"
        pkl_path = RAG_DIR / "index.pkl"

        if not (faiss_path.exists() and pkl_path.exists()):
            return None  # 첫 add 시 생성

        # FAISS 인덱스 로드 (bytes → deserialize)
        data = np.frombuffer(faiss_path.read_bytes(), dtype=np.uint8)
        index = faiss.deserialize_index(data)

        # docstore + 매핑 로드 (pickle)
        with open(pkl_path, "rb") as f:
            docstore, index_to_docstore_id = pickle.load(f)

        return FAISS(
            embedding_function=self.embeddings,
            index=index,
            docstore=docstore,
            index_to_docstore_id=index_to_docstore_id,
        )

    def _save(self):
        """Windows 한글 경로 우회 — faiss.write_index 대신 serialize."""
        RAG_DIR.mkdir(parents=True, exist_ok=True)

        faiss_path = RAG_DIR / "index.faiss"
        pkl_path = RAG_DIR / "index.pkl"

        # FAISS 인덱스 저장
        faiss_path.write_bytes(faiss.serialize_index(self.store.index).tobytes())

        # docstore + 매핑 저장
        with open(pkl_path, "wb") as f:
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

    def search(self, query: str, k: int = TOP_K) -> list[dict]:
        """질문과 유사한 chunk 상위 k 개 반환."""
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


# 싱글톤
_rag: RAGStore | None = None


def get_rag() -> RAGStore:
    global _rag
    if _rag is None:
        _rag = RAGStore()
    return _rag
