"""PostgreSQL Store operations for isolated conversational intake state."""

from langgraph.store.base import BaseStore

from app.intake.models import ConversationIntakeState

INTAKE_NAMESPACE = "trip_intake"


def intake_namespace(user_id: str) -> tuple[str, str]:
    """Return the user-isolated Store namespace for intake drafts."""

    return (user_id, INTAKE_NAMESPACE)


async def load_intake_state(
    store: BaseStore,
    *,
    user_id: str,
    thread_id: str,
) -> ConversationIntakeState | None:
    """Load and validate one state without returning Store metadata."""

    item = await store.aget(intake_namespace(user_id), thread_id)
    if item is None:
        return None
    return ConversationIntakeState.model_validate(item.value)


async def save_intake_state(store: BaseStore, state: ConversationIntakeState) -> None:
    """Persist only the strict JSON projection of an intake state."""

    await store.aput(
        intake_namespace(state.user_id),
        state.thread_id,
        state.model_dump(mode="json"),
        index=False,
    )


async def delete_intake_state(
    store: BaseStore,
    *,
    user_id: str,
    thread_id: str,
) -> None:
    """Delete only one user's intake key, leaving graph and memory data untouched."""

    await store.adelete(intake_namespace(user_id), thread_id)
