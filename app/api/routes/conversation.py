"""HTTP and SSE boundaries for conversational trip requirement intake."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import aclosing
from dataclasses import dataclass
from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.sse import EventSourceResponse, ServerSentEvent

from app.api.routes.persistence import (
    _get_persistence,
    _PreparedPlanStream,
    _validate_thread_id,
    execute_thread_plan,
    prepare_thread_plan_stream,
)
from app.auth.dependencies import request_user_id
from app.intake.errors import (
    IntakeConflictError,
    IntakeError,
    IntakeNotFoundError,
)
from app.intake.service import ConversationIntakeService
from app.schemas.intake import (
    ConversationConfirmRequest,
    ConversationMessageRequest,
    ConversationResetRequest,
    ConversationResponse,
)
from app.schemas.persistence import ThreadPlanRequest, ThreadPlanResponse
from app.streaming.models import StreamEventType, StreamHeartbeat

router = APIRouter(tags=["conversation"])


@dataclass(slots=True)
class _PreparedConfirmationStream:
    """All validation completed before FastAPI commits SSE response headers."""

    prepared: _PreparedPlanStream
    service: ConversationIntakeService
    user_id: str
    thread_id: str
    fingerprint: str
    terminal_recorded: bool = False
    cleanup_recorded: bool = False


def _service(request: Request) -> ConversationIntakeService:
    """Build a request-scoped coordinator around application-owned resources."""

    persistence = _get_persistence(request)
    try:
        provider = request.app.state.resources.llm_runtime.provider
    except AttributeError:
        provider = None
    return ConversationIntakeService(
        store=persistence.store,
        provider=provider,
        metrics=request.app.state.metrics,
        history_limit=request.app.state.settings.intake_history_limit,
        require_guest_nationality=request.app.state.settings.requires_guest_nationality,
    )


def _raise_intake_http_error(error: IntakeError) -> NoReturn:
    """Map stable service codes to bounded responses without exception details."""

    if isinstance(error, IntakeNotFoundError):
        http_status = status.HTTP_404_NOT_FOUND
        message = "No conversational intake exists for this user and thread."
    elif isinstance(error, IntakeConflictError):
        http_status = status.HTTP_409_CONFLICT
        messages = {
            "stale_draft_fingerprint": (
                "The draft changed; review it and confirm the current fingerprint."
            ),
            "trip_already_planned": (
                "This trip is already planned; reset or start a new trip first."
            ),
            "trip_planning_in_progress": "Planning is already in progress for this draft.",
            "draft_not_ready_for_confirmation": "The draft still has missing or invalid fields.",
        }
        message = messages.get(error.code, "The intake state conflicts with this request.")
    else:
        http_status = status.HTTP_503_SERVICE_UNAVAILABLE
        if error.code == "conversational_intake_requires_llm":
            message = "Conversational intake requires configured Qwen mode."
        elif error.code == "intake_store_unavailable":
            message = "The conversational intake store is unavailable."
        else:
            message = "The structured intake provider could not complete this turn."
    raise HTTPException(
        status_code=http_status,
        detail={"code": error.code, "message": message},
    )


@router.post(
    "/api/v1/agents/threads/{thread_id}/conversation/messages",
    response_model=ConversationResponse,
)
async def create_conversation_message(
    thread_id: str,
    payload: ConversationMessageRequest,
    request: Request,
) -> ConversationResponse:
    """Merge one natural-language turn without running the planning graph."""

    validated_thread_id = _validate_thread_id(thread_id)
    validated_user_id = request_user_id(request, payload.user_id)
    try:
        state = await _service(request).process_message(
            user_id=validated_user_id,
            thread_id=validated_thread_id,
            message=payload.message,
            start_new_trip=payload.start_new_trip,
        )
    except IntakeError as exc:
        _raise_intake_http_error(exc)
    return ConversationResponse.from_state(state)


@router.get(
    "/api/v1/agents/threads/{thread_id}/conversation",
    response_model=ConversationResponse,
)
async def get_conversation(
    thread_id: str,
    request: Request,
    user_id: str | None = Query(default=None, min_length=1, max_length=64),
) -> ConversationResponse:
    """Return the safe persisted conversation for one explicit user namespace."""

    validated_thread_id = _validate_thread_id(thread_id)
    validated_user_id = request_user_id(request, user_id)
    try:
        state = await _service(request).get_state(
            user_id=validated_user_id,
            thread_id=validated_thread_id,
        )
    except IntakeError as exc:
        _raise_intake_http_error(exc)
    return ConversationResponse.from_state(state)


@router.post(
    "/api/v1/agents/threads/{thread_id}/conversation/reset",
    response_model=ConversationResponse,
)
async def reset_conversation(
    thread_id: str,
    payload: ConversationResetRequest,
    request: Request,
) -> ConversationResponse:
    """Reset only one user's intake while retaining graph history and long-term memory."""

    validated_thread_id = _validate_thread_id(thread_id)
    validated_user_id = request_user_id(request, payload.user_id)
    try:
        state = await _service(request).reset(
            user_id=validated_user_id,
            thread_id=validated_thread_id,
        )
    except IntakeError as exc:
        _raise_intake_http_error(exc)
    return ConversationResponse.from_state(state)


@router.post(
    "/api/v1/agents/threads/{thread_id}/conversation/confirm",
    response_model=ThreadPlanResponse,
)
async def confirm_conversation(
    thread_id: str,
    payload: ConversationConfirmRequest,
    request: Request,
) -> ThreadPlanResponse:
    """Run the existing persistent planning graph once after explicit current consent."""

    validated_thread_id = _validate_thread_id(thread_id)
    validated_user_id = request_user_id(request, payload.user_id)
    service = _service(request)
    try:
        _, requirements_value = await service.begin_confirmation(
            user_id=validated_user_id,
            thread_id=validated_thread_id,
            fingerprint=payload.draft_fingerprint,
        )
        requirements = requirements_value
    except IntakeError as exc:
        _raise_intake_http_error(exc)

    plan_payload = ThreadPlanRequest(
        user_id=validated_user_id,
        requirements=requirements,
        remember_preferences=payload.remember_preferences,
    )
    try:
        response = await execute_thread_plan(validated_thread_id, plan_payload, request)
        await service.mark_planned(
            user_id=validated_user_id,
            thread_id=validated_thread_id,
            fingerprint=payload.draft_fingerprint,
        )
        return response
    except asyncio.CancelledError:
        await _restore_retryable(
            service,
            user_id=validated_user_id,
            thread_id=validated_thread_id,
            fingerprint=payload.draft_fingerprint,
        )
        service.record_confirmation("disconnect")
        raise
    except IntakeError as exc:
        await _restore_retryable(
            service,
            user_id=validated_user_id,
            thread_id=validated_thread_id,
            fingerprint=payload.draft_fingerprint,
        )
        service.record_confirmation("planning_error")
        _raise_intake_http_error(exc)
    except Exception:
        await _restore_retryable(
            service,
            user_id=validated_user_id,
            thread_id=validated_thread_id,
            fingerprint=payload.draft_fingerprint,
        )
        service.record_confirmation("planning_error")
        raise


async def _prepare_confirmation_stream(
    thread_id: str,
    payload: ConversationConfirmRequest,
    request: Request,
) -> AsyncIterator[_PreparedConfirmationStream]:
    """Validate consent, Store, and backend readiness before opening SSE."""

    validated_thread_id = _validate_thread_id(thread_id)
    validated_user_id = request_user_id(request, payload.user_id)
    service = _service(request)
    try:
        _, requirements_value = await service.begin_confirmation(
            user_id=validated_user_id,
            thread_id=validated_thread_id,
            fingerprint=payload.draft_fingerprint,
        )
        requirements = requirements_value
        prepared = await prepare_thread_plan_stream(
            validated_thread_id,
            ThreadPlanRequest(
                user_id=validated_user_id,
                requirements=requirements,
                remember_preferences=payload.remember_preferences,
            ),
            request,
        )
    except IntakeError as exc:
        _raise_intake_http_error(exc)
    except Exception:
        await _restore_retryable(
            service,
            user_id=validated_user_id,
            thread_id=validated_thread_id,
            fingerprint=payload.draft_fingerprint,
        )
        service.record_confirmation("planning_error")
        raise
    result = _PreparedConfirmationStream(
        prepared=prepared,
        service=service,
        user_id=validated_user_id,
        thread_id=validated_thread_id,
        fingerprint=payload.draft_fingerprint,
    )
    try:
        yield result
    finally:
        if not result.terminal_recorded and not result.cleanup_recorded:
            await _restore_retryable(
                result.service,
                user_id=result.user_id,
                thread_id=result.thread_id,
                fingerprint=result.fingerprint,
            )
            result.service.record_confirmation("disconnect")
            result.cleanup_recorded = True


@router.post(
    "/api/v1/agents/threads/{thread_id}/conversation/confirm/stream",
    response_class=EventSourceResponse,
    responses={503: {"description": "Intake, persistence, or search backend unavailable"}},
)
async def stream_confirmed_conversation(
    prepared: Annotated[_PreparedConfirmationStream, Depends(_prepare_confirmation_stream)],
) -> AsyncIterator[ServerSentEvent]:
    """Reuse the P12 stream and mark planned only after its success terminal."""

    try:
        async with aclosing(prepared.prepared.stream.stream()) as stream:
            async for item in stream:
                if isinstance(item, StreamHeartbeat):
                    yield ServerSentEvent(comment=item.comment)
                    continue
                event = item
                yield ServerSentEvent(
                    id=str(event.event_id),
                    event=event.event_type.value,
                    data=event.model_dump(mode="json"),
                )
                if event.event_type == StreamEventType.PLAN_COMPLETED:
                    try:
                        await prepared.service.mark_planned(
                            user_id=prepared.user_id,
                            thread_id=prepared.thread_id,
                            fingerprint=prepared.fingerprint,
                        )
                    except IntakeError:
                        await _restore_retryable(
                            prepared.service,
                            user_id=prepared.user_id,
                            thread_id=prepared.thread_id,
                            fingerprint=prepared.fingerprint,
                        )
                        prepared.service.record_confirmation("planning_error")
                        prepared.terminal_recorded = True
                        prepared.cleanup_recorded = True
                        return
                    prepared.terminal_recorded = True
                elif event.event_type == StreamEventType.ERROR:
                    await _restore_retryable(
                        prepared.service,
                        user_id=prepared.user_id,
                        thread_id=prepared.thread_id,
                        fingerprint=prepared.fingerprint,
                    )
                    prepared.service.record_confirmation("planning_error")
                    prepared.terminal_recorded = True
    finally:
        if not prepared.terminal_recorded and not prepared.cleanup_recorded:
            await _restore_retryable(
                prepared.service,
                user_id=prepared.user_id,
                thread_id=prepared.thread_id,
                fingerprint=prepared.fingerprint,
            )
            prepared.service.record_confirmation("disconnect")
            prepared.cleanup_recorded = True


async def _restore_retryable(
    service: ConversationIntakeService,
    *,
    user_id: str,
    thread_id: str,
    fingerprint: str,
) -> None:
    """Finish the small Store rollback even when the request task was cancelled."""

    cleanup = asyncio.create_task(
        service.mark_confirmation_failed(
            user_id=user_id,
            thread_id=thread_id,
            fingerprint=fingerprint,
        )
    )
    try:
        await asyncio.shield(cleanup)
    except asyncio.CancelledError:
        try:
            await cleanup
        except IntakeError:
            pass
        raise
    except IntakeError:
        return
