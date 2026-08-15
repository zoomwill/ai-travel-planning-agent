"""Local-development HTTP diagnostics for P10 advanced RAG."""

from typing import NoReturn, cast

from fastapi import APIRouter, HTTPException, Request, status

from app.core.resources import AppResources
from app.rag.models import QueryBundle
from app.rag.runtime import AdvancedRagRuntime
from app.schemas.rag import RagSearchRequest, RagSearchResponse, RagStatusResponse

router = APIRouter(prefix="/api/v1/rag", tags=["rag"])


def _raise_rag_error(code: str, message: str) -> NoReturn:
    """Raise a sanitized local RAG error."""

    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"code": code, "message": message},
    )


def _resources(request: Request) -> AppResources:
    """Read lifespan-owned resources or fail without an AttributeError leak."""

    try:
        return cast(AppResources, request.app.state.resources)
    except AttributeError:
        _raise_rag_error("rag_not_initialized", "The RAG runtime is not initialized.")


def _runtime(resources: AppResources) -> AdvancedRagRuntime:
    """Return the optional runtime or a stable not-initialized error."""

    if resources.rag_runtime is None:
        _raise_rag_error("rag_not_initialized", "The RAG runtime is not initialized.")
    return resources.rag_runtime


@router.get("/status", response_model=RagStatusResponse)
async def get_rag_status(request: Request) -> RagStatusResponse:
    """Return index counts and safe cache availability for local development."""

    resources = _resources(request)
    runtime = _runtime(resources)
    try:
        cache_available = await resources.redis_client.ping() is True
    except Exception:
        cache_available = False
    return RagStatusResponse(
        pipeline_version=runtime.pipeline_version,
        indexed=runtime.indexed,
        collection_name=runtime.collection_name,
        child_count=runtime.child_count,
        parent_count=runtime.parent_count,
        corpus_fingerprint=runtime.corpus_fingerprint,
        embedding_model=runtime.embedding_model,
        embedding_dimension=runtime.embedding_dimension,
        bm25_ready=runtime.bm25_ready,
        cache_available=cache_available,
    )


@router.post("/search", response_model=RagSearchResponse)
async def search_rag(payload: RagSearchRequest, request: Request) -> RagSearchResponse:
    """Run one parent-level advanced search without exposing internal candidates."""

    runtime = _runtime(_resources(request))
    if not runtime.indexed:
        _raise_rag_error("rag_not_indexed", "Run the explicit P10 model and index scripts first.")
    try:
        result = await runtime.retriever.retrieve(
            QueryBundle(
                original_query=payload.query,
                destination=payload.destination,
                current_preferences=payload.preferences,
            ),
            top_k=payload.top_k,
        )
    except Exception:
        _raise_rag_error("retrieval_unavailable", "Advanced retrieval could not complete.")
    if result.error is not None:
        _raise_rag_error(result.error, "Advanced retrieval returned no usable context.")
    return RagSearchResponse(
        contexts=result.contexts,
        parent_ids=result.parent_ids,
        diagnostics=result.diagnostics,
    )
