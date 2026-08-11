"""LangGraph node for explicit, cross-thread user preference memory."""

from langgraph.runtime import Runtime

from app.graphs.context import TravelRuntimeContext
from app.graphs.state import TravelPlanState
from app.memory.preferences import list_user_preferences, upsert_explicit_preferences


async def memory_context_node(
    state: TravelPlanState,
    runtime: Runtime[TravelRuntimeContext],
) -> TravelPlanState:
    """Save explicit preferences and load only the current user's memories."""

    del state
    context = runtime.context
    preferences_to_remember = context.preferences_to_remember if context is not None else ()
    if runtime.store is None:
        if preferences_to_remember:
            return {"remembered_preferences": [], "error": "store_unavailable"}
        return {"remembered_preferences": [], "error": None}

    if context is None:
        return {"remembered_preferences": [], "error": "invalid_user_id"}

    thread_id = runtime.execution_info.thread_id if runtime.execution_info is not None else None
    if preferences_to_remember and not thread_id:
        return {"remembered_preferences": [], "error": "checkpoint_unavailable"}

    try:
        if preferences_to_remember:
            await upsert_explicit_preferences(
                runtime.store,
                user_id=context.user_id,
                source_thread_id=thread_id or "stateless",
                values=preferences_to_remember,
            )
        memories = await list_user_preferences(runtime.store, context.user_id)
    except Exception:
        return {"remembered_preferences": [], "error": "store_unavailable"}

    return {
        "remembered_preferences": [memory.value for memory in memories],
        "error": None,
    }
