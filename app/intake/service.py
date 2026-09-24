"""Conversation orchestration that never executes the travel-planning graph."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import time
from collections.abc import Callable
from datetime import UTC, date, datetime

from langgraph.store.base import BaseStore

from app.domain.countries import normalize_explicit_country
from app.domain.models import TripRequirements
from app.intake.errors import (
    IntakeConflictError,
    IntakeNotFoundError,
    IntakeUnavailableError,
)
from app.intake.logic import (
    NATIONALITY_CLARIFICATION,
    assistant_message_for,
    draft_fingerprint,
    explicit_nationality_value,
    invalid_requirement_fields,
    merge_requirement_patch,
    missing_requirement_fields,
    require_explicit_nationality,
)
from app.intake.models import (
    ConversationIntakeState,
    ConversationMessage,
    ConversationRole,
    IntakeStatus,
    PartialTripRequirements,
    RequirementField,
    TripRequirementPatch,
    complete_trip_requirements,
    new_intake_state,
)
from app.intake.store import (
    load_intake_state,
    save_intake_state,
)
from app.llm.errors import LLMError
from app.llm.models import IntakePromptInput
from app.llm.protocol import StructuredLLMProvider
from app.observability.context import pseudonymous_ref
from app.observability.logging import log_event, redact_text
from app.observability.metrics import (
    INTAKE_CONFIRMATION_STATUSES,
    INTAKE_TURN_STATUSES,
    REQUIREMENT_FIELDS,
    MetricsRuntime,
    normalize_label,
)

Clock = Callable[[], datetime]
CurrentDate = Callable[[], date]


class ConversationIntakeService:
    """Collect, persist, and explicitly confirm one user's incremental trip draft."""

    def __init__(
        self,
        *,
        store: BaseStore,
        provider: StructuredLLMProvider | None,
        metrics: MetricsRuntime | None = None,
        history_limit: int = 30,
        clock: Clock | None = None,
        current_date: CurrentDate | None = None,
        require_guest_nationality: bool = False,
    ) -> None:
        self._store = store
        self._require_guest_nationality = require_guest_nationality
        self._provider = provider
        self._metrics = metrics
        self._history_limit = history_limit
        self._clock = clock or (lambda: datetime.now(UTC))
        self._current_date = current_date or (lambda: datetime.now(UTC).date())

    async def get_state(self, *, user_id: str, thread_id: str) -> ConversationIntakeState:
        """Return one user-isolated conversation or a stable not-found error."""

        try:
            state = await load_intake_state(
                self._store,
                user_id=user_id,
                thread_id=thread_id,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            raise IntakeUnavailableError("intake_store_unavailable") from None
        if state is None:
            raise IntakeNotFoundError("conversation_not_found")
        return state

    async def process_message(
        self,
        *,
        user_id: str,
        thread_id: str,
        message: str,
        start_new_trip: bool = False,
    ) -> ConversationIntakeState:
        """Extract one strict patch, merge it, then ask a deterministic next question."""

        started = time.monotonic()
        metric_status = "error"
        state: ConversationIntakeState | None
        try:
            if start_new_trip:
                existing = await self._load_optional(user_id=user_id, thread_id=thread_id)
                reset_at = self._utc_now()
                state = new_intake_state(
                    thread_id=thread_id,
                    user_id=user_id,
                    now=reset_at,
                    draft_fingerprint=draft_fingerprint(PartialTripRequirements()),
                ).model_copy(update={"version": (existing.version + 1 if existing else 1)})
                await self._save(state)
            else:
                state = await self._load_optional(user_id=user_id, thread_id=thread_id)

            if state is not None and state.status == IntakeStatus.PLANNED:
                raise IntakeConflictError("trip_already_planned")
            if state is not None and state.status == IntakeStatus.PLANNING:
                raise IntakeConflictError("trip_planning_in_progress")
            if self._provider is None:
                raise IntakeUnavailableError("conversational_intake_requires_llm")

            now = self._utc_now()
            current = state or new_intake_state(
                thread_id=thread_id,
                user_id=user_id,
                now=now,
                draft_fingerprint=draft_fingerprint(PartialTripRequirements()),
            )
            safe_message = redact_text(message)
            asked_fields = list(dict.fromkeys([*current.invalid_fields, *current.missing_fields]))[
                :2
            ]
            nationality_turn = RequirementField.GUEST_NATIONALITY in asked_fields
            nationality_only_turn = asked_fields == [RequirementField.GUEST_NATIONALITY]
            country_answer = explicit_nationality_value(
                safe_message,
                allow_bare_country=nationality_only_turn,
                allow_correction=nationality_only_turn
                or (
                    current.status == IntakeStatus.AWAITING_CONFIRMATION
                    and current.draft.guest_nationality is not None
                ),
            )
            country_code = (
                normalize_explicit_country(country_answer) if country_answer is not None else None
            )
            try:
                if country_answer is not None:
                    # This dedicated answer needs no LLM parsing and cannot fail ISO2 parsing
                    # merely because the user supplied a natural-language country name.
                    patch = (
                        TripRequirementPatch(guest_nationality=country_code)
                        if country_code is not None
                        else TripRequirementPatch()
                    )
                else:
                    extraction = await self._provider.extract_trip_requirements(
                        IntakePromptInput(
                            current_date=self._current_date(),
                            current_draft=current.draft,
                            user_message=safe_message,
                        )
                    )
                    patch = require_explicit_nationality(
                        safe_message, extraction.value.patch, allow_bare_country=False
                    )
            except asyncio.CancelledError:
                raise
            except LLMError as exc:
                raise IntakeUnavailableError(exc.code) from None
            except Exception:
                raise IntakeUnavailableError("llm_provider_error") from None

            try:
                draft = merge_requirement_patch(current.draft, patch)
            except (ArithmeticError, ValueError):
                raise IntakeUnavailableError("llm_schema_validation_failed") from None
            missing = missing_requirement_fields(
                draft, require_guest_nationality=self._require_guest_nationality
            )
            invalid = invalid_requirement_fields(draft)
            if country_code is None and (
                country_answer is not None
                or (
                    RequirementField.GUEST_NATIONALITY in current.invalid_fields
                    and RequirementField.GUEST_NATIONALITY not in patch.clear_fields
                )
            ):
                invalid.append(RequirementField.GUEST_NATIONALITY)
            status = (
                IntakeStatus.AWAITING_CONFIRMATION
                if not missing and not invalid
                else IntakeStatus.COLLECTING
            )
            assistant_message = assistant_message_for(draft, missing, invalid)
            if RequirementField.GUEST_NATIONALITY in invalid or (
                nationality_turn and RequirementField.GUEST_NATIONALITY in missing
            ):
                assistant_message = NATIONALITY_CLARIFICATION
            turn_count = current.turn_count + 1
            messages = [
                *current.messages,
                self._message(
                    thread_id=thread_id,
                    turn_count=turn_count,
                    role=ConversationRole.USER,
                    content=safe_message,
                    created_at=now,
                ),
                self._message(
                    thread_id=thread_id,
                    turn_count=turn_count,
                    role=ConversationRole.ASSISTANT,
                    content=assistant_message,
                    created_at=now,
                ),
            ][-self._history_limit :]
            updated = current.model_copy(
                update={
                    "status": status,
                    "assistant_message": assistant_message,
                    "draft": draft,
                    "missing_fields": missing,
                    "invalid_fields": invalid,
                    "draft_fingerprint": draft_fingerprint(draft),
                    "messages": messages,
                    "turn_count": turn_count,
                    "version": current.version + 1,
                    "plan_available": False,
                    "updated_at": now,
                    "planned_at": None,
                }
            )
            await self._save(updated)
            metric_status = (
                "ready" if status == IntakeStatus.AWAITING_CONFIRMATION else "clarification"
            )
            self._record_clarification([*invalid, *missing])
            log_event(
                "intake_turn_completed",
                "A conversational intake turn completed.",
                component="intake",
                user_ref=pseudonymous_ref(user_id, kind="user"),
                thread_ref=pseudonymous_ref(thread_id, kind="thread"),
                outcome=metric_status,
                turn_count=turn_count,
                missing_field_count=len(missing),
            )
            return updated
        finally:
            self._record_turn(metric_status, max(0.0, time.monotonic() - started))

    async def reset(self, *, user_id: str, thread_id: str) -> ConversationIntakeState:
        """Replace only the selected intake with an empty persisted state."""

        existing = await self._load_optional(user_id=user_id, thread_id=thread_id)
        now = self._utc_now()
        state = new_intake_state(
            thread_id=thread_id,
            user_id=user_id,
            now=now,
            draft_fingerprint=draft_fingerprint(PartialTripRequirements()),
        ).model_copy(update={"version": (existing.version + 1 if existing else 1)})
        await self._save(state)
        return state

    async def begin_confirmation(
        self,
        *,
        user_id: str,
        thread_id: str,
        fingerprint: str,
    ) -> tuple[ConversationIntakeState, TripRequirements]:
        """Validate explicit consent and persist the transient planning status."""

        state = await self.get_state(user_id=user_id, thread_id=thread_id)
        if not hmac.compare_digest(state.draft_fingerprint, fingerprint):
            self.record_confirmation("stale")
            raise IntakeConflictError("stale_draft_fingerprint")
        if state.status == IntakeStatus.PLANNED:
            self.record_confirmation("invalid")
            raise IntakeConflictError("trip_already_planned")
        if state.status == IntakeStatus.PLANNING:
            self.record_confirmation("invalid")
            raise IntakeConflictError("trip_planning_in_progress")
        if state.status != IntakeStatus.AWAITING_CONFIRMATION:
            self.record_confirmation("invalid")
            raise IntakeConflictError("draft_not_ready_for_confirmation")

        if missing_requirement_fields(
            state.draft, require_guest_nationality=self._require_guest_nationality
        ):
            raise IntakeConflictError("draft_not_ready_for_confirmation")

        requirements = complete_trip_requirements(state.draft)
        planning = state.model_copy(
            update={
                "status": IntakeStatus.PLANNING,
                "assistant_message": "Your confirmed trip is being planned.",
                "version": state.version + 1,
                "updated_at": self._utc_now(),
            }
        )
        await self._save(planning)
        return planning, requirements

    async def mark_confirmation_failed(
        self,
        *,
        user_id: str,
        thread_id: str,
        fingerprint: str,
    ) -> None:
        """Keep a confirmed draft retryable after graph failure or disconnect."""

        state = await self._load_optional(user_id=user_id, thread_id=thread_id)
        if (
            state is None
            or state.status != IntakeStatus.PLANNING
            or not hmac.compare_digest(state.draft_fingerprint, fingerprint)
        ):
            return
        await self._save(
            state.model_copy(
                update={
                    "status": IntakeStatus.AWAITING_CONFIRMATION,
                    "assistant_message": (
                        "Planning did not finish. Your draft is preserved and can be "
                        "confirmed again."
                    ),
                    "version": state.version + 1,
                    "updated_at": self._utc_now(),
                }
            )
        )

    async def mark_planned(
        self,
        *,
        user_id: str,
        thread_id: str,
        fingerprint: str,
    ) -> None:
        """Store only a small plan reference after successful graph completion."""

        state = await self.get_state(user_id=user_id, thread_id=thread_id)
        if not hmac.compare_digest(state.draft_fingerprint, fingerprint):
            raise IntakeConflictError("stale_draft_fingerprint")
        now = self._utc_now()
        await self._save(
            state.model_copy(
                update={
                    "status": IntakeStatus.PLANNED,
                    "assistant_message": "Your travel plan is ready.",
                    "version": state.version + 1,
                    "plan_available": True,
                    "updated_at": now,
                    "planned_at": now,
                }
            )
        )
        self.record_confirmation("success")

    def record_confirmation(self, status: str) -> None:
        """Count one bounded confirmation outcome without user-derived labels."""

        if self._metrics is not None:
            label = normalize_label(status, INTAKE_CONFIRMATION_STATUSES)
            self._metrics.intake_confirmations.labels(status=label).inc()

    async def _load_optional(
        self,
        *,
        user_id: str,
        thread_id: str,
    ) -> ConversationIntakeState | None:
        try:
            return await load_intake_state(
                self._store,
                user_id=user_id,
                thread_id=thread_id,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            raise IntakeUnavailableError("intake_store_unavailable") from None

    async def _save(self, state: ConversationIntakeState) -> None:
        try:
            await save_intake_state(self._store, state)
        except asyncio.CancelledError:
            raise
        except Exception:
            raise IntakeUnavailableError("intake_store_unavailable") from None

    def _message(
        self,
        *,
        thread_id: str,
        turn_count: int,
        role: ConversationRole,
        content: str,
        created_at: datetime,
    ) -> ConversationMessage:
        source = (
            f"{thread_id}\x1f{turn_count}\x1f{role.value}\x1f{created_at.isoformat()}\x1f{content}"
        )
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:24]
        return ConversationMessage(
            message_id=f"msg_{digest}",
            role=role,
            content=content,
            created_at=created_at,
        )

    def _record_turn(self, status: str, duration: float) -> None:
        if self._metrics is None:
            return
        label = normalize_label(status, INTAKE_TURN_STATUSES)
        self._metrics.intake_turns.labels(status=label).inc()
        self._metrics.intake_turn_duration.labels(status=label).observe(duration)

    def _record_clarification(self, fields: list[RequirementField]) -> None:
        if self._metrics is None or not fields:
            return
        label = normalize_label(fields[0].value, REQUIREMENT_FIELDS)
        self._metrics.intake_clarifications.labels(field=label).inc()

    def _utc_now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("intake clock must return a timezone-aware datetime")
        return value.astimezone(UTC)
