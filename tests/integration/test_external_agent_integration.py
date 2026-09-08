"""ONE opt-in paid persistent SSE path; no supplier data is printed or saved to files."""

import asyncio
import os
import time
from dataclasses import replace
from datetime import date, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.core.config import Settings
from app.core.persistence import create_strict_serializer
from app.core.resources import create_app_resources
from app.domain.models import TravelPlan
from app.main import create_app
from tests.api.test_streaming import parse_sse
from tests.external.acceptance_checks import (
    AcceptanceFailure,
    check_public_tree,
    check_state,
    require,
)


@pytest.mark.external_agent_integration
def test_one_real_mixed_qwen_stream_and_checkpoint(monkeypatch, capsys) -> None:
    """Observe production logic without replacing providers or rerunning the graph."""
    gates = (
        "RUN_EXTERNAL_AGENT_INTEGRATION_TESTS",
        "RUN_DUFFEL_INTEGRATION_TESTS",
        "RUN_LITEAPI_INTEGRATION_TESTS",
        "RUN_LLM_INTEGRATION_TESTS",
    )
    if any(os.getenv(gate) != "1" for gate in gates):
        pytest.skip("enable all four explicit external Agent/provider/LLM gates")
    try:
        settings = Settings(
            travel_data_mode="external",
            travel_search_backend_mode="direct",
            travel_flight_provider="duffel",
            travel_hotel_provider="liteapi",
            duffel_env="test",
            liteapi_env="sandbox",
            agent_reasoning_mode="qwen",
            duffel_allow_demo_fallback=False,
            liteapi_allow_demo_fallback=False,
            qwen_allow_deterministic_fallback=False,
            duffel_max_retries=0,
            liteapi_max_retries=0,
            qwen_max_retries=0,
        )
    except Exception:
        pytest.fail("Invalid external acceptance settings (values hidden)", pytrace=False)
    if settings.external_configuration_error or not settings.qwen_is_configured:
        pytest.skip("required external/Qwen credential is not configured")

    thread_id = "p17-real-" + uuid4().hex
    config = {"configurable": {"thread_id": thread_id}}
    counts = {"graph": 0, "planner": 0, "reviewer": 0}
    intervals = {}
    prompt_counts = []
    output_lines = []

    async def factory(configuration):
        resources = await create_app_resources(configuration)
        bundle = resources.travel_runtime.backend

        def observed(kind, original):
            async def search(requirements):
                require(kind not in intervals, "external branch executed more than once")
                intervals[kind] = [time.monotonic(), None]
                try:
                    return await original(requirements)
                finally:
                    intervals[kind][1] = time.monotonic()

            return search

        resources.search_backend = replace(
            bundle,
            flight_provider=observed("flights", bundle.flight_provider),
            hotel_provider=observed("hotels", bundle.hotel_provider),
        )
        return resources

    async def inspect_history(graph):
        history_count = 0
        async for snapshot in graph.aget_state_history(config):
            check_state(
                snapshot.values, settings.duffel_max_flight_offers, settings.liteapi_max_hotels
            )
            history_count += 1
        return history_count

    async def restore_and_cleanup(expected_plan=None):
        # Only this test's fresh UUID thread can be removed; never touch user threads or volumes.
        async with AsyncPostgresSaver.from_conn_string(
            settings.langgraph_postgres_uri.get_secret_value(), serde=create_strict_serializer()
        ) as saver:
            try:
                if expected_plan is not None:
                    checkpoint = await saver.aget_tuple(config)
                    require(checkpoint is not None, "checkpoint missing on fresh connection")
                    values = checkpoint.checkpoint["channel_values"]
                    check_state(
                        values, settings.duffel_max_flight_offers, settings.liteapi_max_hotels
                    )
                    restored = TravelPlan.model_validate(values["travel_plan"])
                    require(restored == expected_plan, "restored plan differs")
            finally:
                await saver.adelete_thread(thread_id)

    final_plan = None
    checkpoint_cleaned = False
    try:
        with TestClient(create_app(settings=settings, resource_factory=factory)) as web:
            resources = web.app.state.resources
            require(web.get("/ready").status_code == 200, "local readiness failed")
            require(resources.rag_runtime.indexed, "prepared RAG index unavailable")
            graph = web.app.state.persistence.graph
            original_stream = graph.astream

            async def observed_stream(*args, **kwargs):
                counts["graph"] += 1
                require(counts["graph"] == 1, "graph executed more than once")
                async for chunk in original_stream(*args, **kwargs):
                    yield chunk

            async def forbidden_invoke(*args, **kwargs):
                raise AcceptanceFailure("second graph invoke is forbidden")

            monkeypatch.setattr(graph, "astream", observed_stream)
            monkeypatch.setattr(graph, "ainvoke", forbidden_invoke)
            provider = resources.llm_runtime.provider
            require(provider is not None, "Qwen provider unavailable")
            original_plan, original_review = provider.plan, provider.review

            async def observed_plan(prompt):
                counts["planner"] += 1
                require(
                    0 < len(prompt.flights) <= settings.duffel_max_flight_offers,
                    "Planner flight cap",
                )
                require(0 < len(prompt.hotels) <= settings.liteapi_max_hotels, "Planner hotel cap")
                prompt_counts.append((len(prompt.flights), len(prompt.hotels)))
                result = await original_plan(prompt)
                require(
                    result.value.selected_flight_id in {x.candidate_id for x in prompt.flights},
                    "Qwen flight ID",
                )
                require(
                    result.value.selected_hotel_id in {x.candidate_id for x in prompt.hotels},
                    "Qwen hotel ID",
                )
                # Production validate_grounded_decision still runs after this observer.
                return result

            async def observed_review(prompt):
                counts["reviewer"] += 1
                require(counts["reviewer"] <= settings.review_max_rounds, "Reviewer round limit")
                return await original_review(prompt)

            monkeypatch.setattr(provider, "plan", observed_plan)
            monkeypatch.setattr(provider, "review", observed_review)
            start = date.today() + timedelta(days=30)
            response = web.post(
                f"/api/v1/agents/threads/{thread_id}/plans/stream",
                json={
                    "user_id": thread_id,
                    "remember_preferences": [],
                    "requirements": {
                        "origin": "London",
                        "destination": "New York",
                        "start_date": start.isoformat(),
                        "end_date": (start + timedelta(days=1)).isoformat(),
                        "budget": "10000",
                        "currency": "USD",
                        "travelers": 1,
                        "guest_nationality": "US",
                        "preferences": [],
                    },
                },
            )  # US is explicit acceptance-fixture input, not application inference/default.
            require(response.status_code == 200, "pre-stream HTTP failure")
            events, _ = parse_sse(response.text)
            check_public_tree(events)
            types = [event["event_type"] for event in events]
            if "error" in types:
                # The public error model contains a bounded code; do not print its other content.
                code = next(e["data"]["error_code"] for e in events if e["event_type"] == "error")
                require(False, "SSE business failure: " + code)
            require(
                types.count("plan_completed") == 1 and types[-1] == "plan_completed",
                "SSE terminal uniqueness",
            )
            require(counts["graph"] == types.count("run_started") == 1, "SSE graph count")
            require(
                [e["sequence"] for e in events] == list(range(1, len(events) + 1)), "SSE sequence"
            )
            require(
                {e["data"]["search_kind"] for e in events if e["event_type"] == "search_started"}
                == {"flights", "hotels", "attractions", "weather", "route"},
                "Send five branches",
            )
            require(
                "retrieval_completed" in types and "review_completed" in types,
                "RAG or Reviewer missing",
            )
            require(0 < counts["planner"] <= settings.review_max_rounds, "Planner round limit")
            require(0 < counts["reviewer"] <= settings.review_max_rounds, "Reviewer missing")
            expected_sources = {
                "flights": "duffel_test",
                "hotels": "liteapi_sandbox",
                "attractions": "demo",
                "weather": "demo",
                "route": "demo",
            }
            final_plan = TravelPlan.model_validate(events[-1]["data"]["travel_plan"])
            require(
                final_plan.data_sources.model_dump(mode="json") == expected_sources,
                "final provenance",
            )
            require(
                {
                    e["data"]["search_kind"]: e["data"]["source"]
                    for e in events
                    if e["event_type"] == "search_completed"
                }
                == expected_sources,
                "SSE provenance",
            )
            require(
                max(x[0] for x in intervals.values()) < min(x[1] for x in intervals.values()),
                "external branches did not overlap",
            )
            snapshot = web.portal.call(graph.aget_state, config)
            check_state(
                snapshot.values, settings.duffel_max_flight_offers, settings.liteapi_max_hotels
            )
            require(len(snapshot.values["search_tasks"]) == 5, "persisted Send tasks")
            require(
                snapshot.values["retrieval_error"] is None
                and len(snapshot.values["retrieval_query_variants"]) > 0,
                "RAG degraded",
            )
            require(
                all(
                    snapshot.values["search_summary"][kind]["source"] == source
                    for kind, source in expected_sources.items()
                ),
                "checkpoint provenance",
            )
            history_count = web.portal.call(inspect_history, graph)
            require(history_count > 1, "checkpoint history missing")
            # Public SSE deliberately strips ephemeral flight IDs; restore compares internal plan.
            final_plan = TravelPlan.model_validate(snapshot.values["travel_plan"])
            output_lines.extend(
                [
                    "PASS Mixed sources: flights=duffel_test hotels=liteapi_sandbox "
                    "attractions=demo weather=demo route=demo",
                    "PASS Graph/SSE: one execution, Send x 5, concurrent external branches, "
                    "one terminal plan_completed",
                    f"PASS Grounded Qwen: planner_calls={counts['planner']} "
                    f"reviewer_calls={counts['reviewer']} candidate_counts={prompt_counts}",
                    f"PASS RAG and strict checkpoint history: checkpoints={history_count}",
                ]
            )
            for family in web.app.state.metrics.llm_tokens.collect():
                for sample in family.samples:
                    if sample.name.endswith("_total"):
                        output_lines.append(
                            f"INFO Provider-reported Qwen tokens: {sample.labels['direction']}="
                            f"{int(sample.value)}"
                        )
            for family in web.app.state.metrics.external_requests.collect():
                for sample in family.samples:
                    if sample.name.endswith("_total") and sample.value:
                        require(sample.labels["operation"] != "stay_search", "forbidden Stays call")
                        output_lines.append(
                            f"INFO External request count: provider={sample.labels['provider']} "
                            f"operation={sample.labels['operation']} "
                            f"status={sample.labels['status']} count={int(sample.value)}"
                        )
            check_public_tree(web.get(f"/api/v1/agents/threads/{thread_id}/state").json())
            require(
                web.get(f"/api/v1/users/{thread_id}/preferences").json() == [],
                "unexpected preference memory",
            )
        asyncio.run(restore_and_cleanup(final_plan))
        checkpoint_cleaned = True
        final_plan = None
        output_lines.append(
            "PASS Fresh PostgreSQL connection restored identical plan; test-only checkpoint cleaned"
        )
        captured = capsys.readouterr()
        check_public_tree(captured.out + captured.err)
        with capsys.disabled():
            print("\n".join(output_lines))
    except AcceptanceFailure as exc:
        pytest.fail(str(exc), pytrace=False)
    except Exception:
        pytest.fail(
            "Mixed acceptance failed unexpectedly (provider/model details hidden)", pytrace=False
        )
    finally:
        if not checkpoint_cleaned and counts["graph"]:
            try:
                asyncio.run(restore_and_cleanup())
            except Exception:
                pytest.fail("Test checkpoint cleanup failed (details hidden)", pytrace=False)
