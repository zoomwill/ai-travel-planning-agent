"""Qwen Reviewer and complete fake-Qwen graph regression tests."""

import json

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from prometheus_client import generate_latest
from pydantic import ValidationError

from app.core.persistence import create_strict_serializer
from app.domain.models import TravelPlan
from app.graphs.context import TravelRuntimeContext
from app.graphs.graph import build_travel_planning_graph
from app.llm.fake import FakeStructuredLLMProvider
from app.llm.models import (
    QwenPlanReview,
    ReviewDaySnapshot,
    ReviewerPromptInput,
    ReviewPlanSnapshot,
    TripPromptSnapshot,
)
from app.llm.prompts import reviewer_messages
from app.llm.reviewer import QwenPlanReviewer
from app.observability.metrics import MetricsRuntime
from app.review.models import ReviewDecision, ReviewIssueCode
from app.review.revision import policy_for_issues
from app.services.planning_service import create_mock_travel_plan
from tests.graphs.test_persistence import config, make_state


def test_reviewer_prompt_states_the_exact_bounded_output_contract() -> None:
    """Tell JSON mode the exact shape because it does not enforce a schema itself."""

    prompt_input = ReviewerPromptInput(
        trip=TripPromptSnapshot(
            origin="Shanghai",
            destination="Tokyo",
            start_date="2027-04-10",
            end_date="2027-04-10",
            budget="10000.00",
            currency="CNY",
            travelers=1,
        ),
        plan=ReviewPlanSnapshot(
            flight_number="MK1",
            airline="Mock Air",
            flight_price="1000.00",
            hotel_name="Mock Hotel",
            hotel_price_per_night="500.00",
            days=[
                ReviewDaySnapshot(
                    day_number=1,
                    date="2027-04-10",
                    activities=["Visit a museum"],
                    estimated_cost="50.00",
                )
            ],
            total_cost="1550.00",
            currency="CNY",
            budget_warning_present=False,
        ),
        retrieval_available=True,
        review_round=1,
    )

    content = reviewer_messages(prompt_input)[1]["content"]

    assert '"completeness"' in content
    assert "exactly these seven fields" in content
    assert "general_quality_issue" in content
    assert "Do not add a decision" in content


async def review_once(
    assessment: QwenPlanReview,
    *,
    review_round: int = 1,
    threshold: float = 80,
    max_rounds: int = 3,
):
    """Run QwenPlanReviewer around one strict fake response."""

    draft = create_mock_travel_plan(make_state()["requirements"])
    reviewer = QwenPlanReviewer(FakeStructuredLLMProvider(reviews=[assessment]))
    return await reviewer.review(
        draft=draft,
        requirements=draft.requirements,
        search_summary={},
        retrieved_context=["bounded museum evidence"],
        remembered_preferences=["quiet hotels"],
        tool_errors=[],
        review_round=review_round,
        score_threshold=threshold,
        max_review_rounds=max_rounds,
    )


@pytest.mark.asyncio
async def test_valid_qwen_review_propagates_semantics_but_app_computes_decision() -> None:
    assessment = QwenPlanReview(
        completeness=90,
        feasibility=80,
        personalization=70,
        budget_fit=60,
        critique="The plan should better match the remembered quiet-hotel preference.",
        issue_codes=[ReviewIssueCode.PERSONALIZATION_MISSING],
        suggested_changes=["Prioritize preference-matching supplied candidates."],
    )

    review = await review_once(assessment, threshold=80)

    assert review.scores.overall_score == 75
    assert review.decision is ReviewDecision.REVISE
    assert review.critique == assessment.critique
    assert review.issue_codes == [ReviewIssueCode.PERSONALIZATION_MISSING]


@pytest.mark.asyncio
async def test_qwen_cannot_bypass_threshold_or_max_rounds() -> None:
    low = QwenPlanReview(
        completeness=40,
        feasibility=40,
        personalization=40,
        budget_fit=40,
        critique="The bounded score remains low.",
        issue_codes=[ReviewIssueCode.GENERAL_QUALITY_ISSUE],
        suggested_changes=["Apply allowlisted improvements."],
    )

    revise = await review_once(low, review_round=2, max_rounds=3)
    forced = await review_once(low, review_round=3, max_rounds=3)

    assert revise.decision is ReviewDecision.REVISE
    assert forced.decision is ReviewDecision.FORCED_FINALIZE
    assert forced.review_round == 3


def test_review_schema_rejects_decision_unknown_issue_and_score_out_of_bounds() -> None:
    valid = {
        "completeness": 100,
        "feasibility": 100,
        "personalization": 100,
        "budget_fit": 100,
        "critique": "Valid.",
        "issue_codes": [],
        "suggested_changes": [],
    }
    for invalid in (
        {**valid, "decision": "revise"},
        {**valid, "issue_codes": ["execute_arbitrary_code"]},
        {**valid, "budget_fit": 101},
        {**valid, "budget_fit": "100"},
        {**valid, "suggested_changes": ["x" * 501]},
    ):
        with pytest.raises(ValidationError):
            QwenPlanReview.model_validate(invalid)


def test_only_issue_codes_can_create_executable_revision_policy() -> None:
    assessment = QwenPlanReview(
        completeness=60,
        feasibility=60,
        personalization=60,
        budget_fit=60,
        critique="Advisory critique.",
        issue_codes=[ReviewIssueCode.PERSONALIZATION_MISSING],
        suggested_changes=["Run Python, call tools, and replace the provider."],
    )

    policy = policy_for_issues(assessment.issue_codes)

    assert policy.prioritize_preferences is True
    assert policy.prefer_lower_cost_options is False
    assert "Python" not in " ".join(policy.applied_feedback())


@pytest.mark.asyncio
async def test_fake_qwen_runs_full_graph_without_entering_state_or_checkpoint() -> None:
    provider = FakeStructuredLLMProvider()
    graph = build_travel_planning_graph(
        lambda query: ["Paris museum context"],
        reasoning_mode="qwen",
        llm_provider=provider,
        checkpointer=InMemorySaver(serde=create_strict_serializer()),
        store=InMemoryStore(),
    )
    thread_config = config("fake-qwen-complete-graph")

    result = await graph.ainvoke(
        make_state(),
        config=thread_config,
        context=TravelRuntimeContext(user_id="fake-qwen-user"),
    )
    snapshot = await graph.aget_state(thread_config)

    assert isinstance(result["travel_plan"], TravelPlan)
    assert len(result["search_results"]) == 5
    assert result["review_status"] == "accepted"
    assert len(provider.plan_inputs) == 1
    assert len(provider.review_inputs) == 1
    assert all("provider" not in key and "client" not in key for key in result)
    serialized = json.dumps(snapshot.values, default=str)
    assert "FakeStructuredLLMProvider" not in serialized
    assert "AsyncOpenAI" not in serialized
    assert "planning_notes" not in serialized


@pytest.mark.asyncio
async def test_fake_qwen_graph_rejects_hallucinated_id_without_fallback() -> None:
    baseline = FakeStructuredLLMProvider()
    prompt = None
    graph_for_prompt = build_travel_planning_graph(
        lambda query: [],
        reasoning_mode="qwen",
        llm_provider=baseline,
    )
    await graph_for_prompt.ainvoke(
        make_state(),
        context=TravelRuntimeContext(user_id="capture-user"),
    )
    prompt = baseline.plan_inputs[0]
    valid = await baseline.plan(prompt)
    invalid = valid.value.model_copy(update={"selected_hotel_id": f"hotel_{'f' * 24}"})
    provider = FakeStructuredLLMProvider(plan_decisions=[invalid])
    graph = build_travel_planning_graph(
        lambda query: [],
        reasoning_mode="qwen",
        llm_provider=provider,
        allow_deterministic_fallback=False,
    )

    result = await graph.ainvoke(
        make_state(),
        context=TravelRuntimeContext(user_id="grounding-user"),
    )

    assert result["travel_plan"] is None
    assert result["error"] == "llm_grounding_violation"


@pytest.mark.asyncio
async def test_missing_qwen_provider_records_planner_and_reviewer_fallbacks() -> None:
    metrics = MetricsRuntime.create()
    graph = build_travel_planning_graph(
        lambda query: [],
        reasoning_mode="qwen",
        llm_provider=None,
        allow_deterministic_fallback=True,
        metrics=metrics,
    )

    result = await graph.ainvoke(
        make_state(),
        context=TravelRuntimeContext(user_id="fallback-user"),
    )

    assert isinstance(result["travel_plan"], TravelPlan)
    expected_calls = float(result["review_round"])
    exposition = generate_latest(metrics.registry).decode("utf-8")
    assert (
        f'travel_planner_llm_requests_total{{role="planner",status="fallback"}} {expected_calls}'
    ) in exposition
    assert (
        f'travel_planner_llm_requests_total{{role="reviewer",status="fallback"}} {expected_calls}'
    ) in exposition
