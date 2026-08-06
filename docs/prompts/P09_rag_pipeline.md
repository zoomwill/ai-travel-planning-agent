# Prompt P09 — RAG Ingestion and Hybrid Retrieval

Complete only Phase 09 using current official APIs.

Load sample docs; create parent and child chunks; store child embeddings in Chroma with parent_doc_id; store parent text; implement BM25, dense search, RRF from ranks, optional reranking interface, parent-context return, Redis cache, metadata filters and an offline labeled evaluation for Recall@K, Precision@K, MRR and NDCG@K. Never claim improvement percentages unless produced by the script. Integrate only after isolated tests pass. Run all checks and stop.
