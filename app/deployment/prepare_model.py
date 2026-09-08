"""Explicit image-build download of the existing model at a pinned revision."""

from app.rag.embeddings import SentenceTransformerEmbeddingBackend

MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
REVISION = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"


def main() -> int:
    """Prepare weights once during image build, without loading application secrets."""

    try:
        model = SentenceTransformerEmbeddingBackend.load(
            MODEL,
            device="cpu",
            normalize_embeddings=True,
            local_files_only=False,
            revision=REVISION,
        )
    except Exception:
        print("FAIL explicit model preparation")
        return 1
    print(f"PASS prepared pinned RAG model: dimension={model.dimensions}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
