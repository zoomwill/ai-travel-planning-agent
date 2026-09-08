"""Application-owned Prometheus registry and low-cardinality metrics."""

from __future__ import annotations

from dataclasses import dataclass

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram
from prometheus_client.gc_collector import GCCollector
from prometheus_client.platform_collector import PlatformCollector
from prometheus_client.process_collector import ProcessCollector

BACKENDS = frozenset({"direct", "mcp"})
STATUSES = frozenset({"success", "error", "cancelled", "unavailable"})
HTTP_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"})
SEARCH_KINDS = frozenset({"flights", "hotels", "attractions", "weather", "route"})
MCP_TOOLS = frozenset(
    {"search_flights", "search_hotels", "search_attractions", "get_weather", "get_route"}
)
GRAPH_NODES = frozenset(
    {
        "memory_context",
        "router",
        "retriever",
        "prepare_search_tasks",
        "search_worker",
        "aggregate_search_results",
        "initialize_review_cycle",
        "planner",
        "reviewer",
        "finalize_plan",
    }
)
SSE_EVENT_TYPES = frozenset(
    {
        "run_started",
        "node_started",
        "node_completed",
        "search_started",
        "search_completed",
        "search_failed",
        "retrieval_completed",
        "review_completed",
        "revision_started",
        "plan_completed",
        "error",
    }
)
DEPENDENCIES = frozenset(
    {"postgresql", "redis", "chroma", "mcp_http", "mcp_stdio", "qwen", "duffel", "liteapi"}
)
EXTERNAL_OPERATIONS = frozenset(
    {"flight_offer_request", "stay_search", "stay_rates", "location_lookup", "hotel_rates"}
)
EXTERNAL_STATUSES = frozenset({"success", "error", "timeout", "rate_limited", "access_denied"})
TRAVEL_DATA_SOURCES = frozenset(
    {"demo", "duffel_test", "duffel_live", "liteapi_sandbox", "liteapi_production", "demo_fallback"}
)
CACHE_STATUSES = frozenset({"hit", "miss", "disabled", "unavailable"})
REVIEW_STATUSES = frozenset({"accepted", "forced_finalized", "failed", "pending"})
FINALIZATION_REASONS = frozenset(
    {"threshold_reached", "max_review_rounds_reached", "reviewer_failure", "unknown"}
)
SSE_TERMINAL_STATUSES = frozenset({"success", "error", "disconnect", "cancelled"})
LLM_ROLES = frozenset({"planner", "reviewer", "query_expander", "intake"})
LLM_STATUSES = frozenset({"success", "error", "timeout", "invalid_response", "fallback"})
LLM_TOKEN_DIRECTIONS = frozenset({"input", "output"})
INTAKE_TURN_STATUSES = frozenset({"clarification", "ready", "error"})
INTAKE_CONFIRMATION_STATUSES = frozenset(
    {"success", "stale", "invalid", "planning_error", "disconnect"}
)
REQUIREMENT_FIELDS = frozenset(
    {
        "origin",
        "destination",
        "start_date",
        "end_date",
        "duration_days",
        "budget",
        "currency",
        "travelers",
        "guest_nationality",
        "preferences",
    }
)


def normalize_label(value: object, allowed: frozenset[str]) -> str:
    """Return only a documented label value; collapse everything else."""

    normalized = str(value)
    return normalized if normalized in allowed else "unknown"


@dataclass(slots=True)
class MetricsRuntime:
    """All metrics registered exactly once in one application's registry."""

    registry: CollectorRegistry
    http_requests: Counter
    http_duration: Histogram
    http_in_progress: Gauge
    graph_runs: Counter
    graph_duration: Histogram
    graph_node_duration: Histogram
    review_rounds: Histogram
    plan_finalizations: Counter
    rag_searches: Counter
    rag_duration: Histogram
    rag_contexts: Histogram
    rag_cache_events: Counter
    search_tasks: Counter
    search_duration: Histogram
    mcp_calls: Counter
    mcp_duration: Histogram
    sse_active: Gauge
    sse_connections: Counter
    sse_duration: Histogram
    sse_events: Counter
    sse_disconnects: Counter
    llm_requests: Counter
    llm_duration: Histogram
    llm_tokens: Counter
    intake_turns: Counter
    intake_turn_duration: Histogram
    intake_confirmations: Counter
    intake_clarifications: Counter
    dependency_ready: Gauge
    external_requests: Counter
    external_duration: Histogram
    search_sources: Counter

    @classmethod
    def create(cls, registry: CollectorRegistry | None = None) -> MetricsRuntime:
        """Create an isolated registry suitable for one app or one unit test."""

        owned_registry = registry or CollectorRegistry(auto_describe=True)
        if registry is None:
            GCCollector(registry=owned_registry)
            ProcessCollector(registry=owned_registry)
            PlatformCollector(registry=owned_registry)
        http_buckets = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30)
        workflow_buckets = (0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30)
        return cls(
            registry=owned_registry,
            http_requests=Counter(
                "travel_planner_http_requests",
                "Completed HTTP requests.",
                ("method", "route", "status_code"),
                registry=owned_registry,
            ),
            http_duration=Histogram(
                "travel_planner_http_request_duration_seconds",
                "Full HTTP response-body duration.",
                ("method", "route"),
                buckets=http_buckets,
                registry=owned_registry,
            ),
            http_in_progress=Gauge(
                "travel_planner_http_requests_in_progress",
                "HTTP requests whose response body is not complete.",
                ("method",),
                registry=owned_registry,
            ),
            graph_runs=Counter(
                "travel_planner_graph_runs",
                "Real LangGraph executions.",
                ("backend", "status"),
                registry=owned_registry,
            ),
            graph_duration=Histogram(
                "travel_planner_graph_run_duration_seconds",
                "Real LangGraph execution duration.",
                ("backend", "status"),
                buckets=workflow_buckets,
                registry=owned_registry,
            ),
            graph_node_duration=Histogram(
                "travel_planner_graph_node_duration_seconds",
                "LangGraph node duration.",
                ("node", "status"),
                buckets=workflow_buckets,
                registry=owned_registry,
            ),
            review_rounds=Histogram(
                "travel_planner_review_rounds",
                "Actual review rounds in a finalized run.",
                ("final_status",),
                buckets=(0, 1, 2, 3, 4, 5, 8, 13),
                registry=owned_registry,
            ),
            plan_finalizations=Counter(
                "travel_planner_plan_finalizations",
                "Final plan outcomes.",
                ("review_status", "reason"),
                registry=owned_registry,
            ),
            rag_searches=Counter(
                "travel_planner_rag_searches",
                "Advanced RAG searches.",
                ("status", "cache_status"),
                registry=owned_registry,
            ),
            rag_duration=Histogram(
                "travel_planner_rag_search_duration_seconds",
                "Advanced RAG search duration.",
                ("status",),
                buckets=workflow_buckets,
                registry=owned_registry,
            ),
            rag_contexts=Histogram(
                "travel_planner_rag_contexts_returned",
                "Safe parent-context count.",
                buckets=(0, 1, 2, 3, 4, 6, 8, 12, 20),
                registry=owned_registry,
            ),
            rag_cache_events=Counter(
                "travel_planner_rag_cache_events",
                "RAG cache outcomes.",
                ("cache_status",),
                registry=owned_registry,
            ),
            search_tasks=Counter(
                "travel_planner_search_tasks",
                "Domain search tasks.",
                ("kind", "backend", "status"),
                registry=owned_registry,
            ),
            search_duration=Histogram(
                "travel_planner_search_task_duration_seconds",
                "Domain search task duration.",
                ("kind", "backend", "status"),
                buckets=workflow_buckets,
                registry=owned_registry,
            ),
            mcp_calls=Counter(
                "travel_planner_mcp_tool_calls",
                "Logical MCP tool calls after bounded retry.",
                ("tool", "status"),
                registry=owned_registry,
            ),
            mcp_duration=Histogram(
                "travel_planner_mcp_tool_duration_seconds",
                "Logical MCP tool call duration.",
                ("tool", "status"),
                buckets=workflow_buckets,
                registry=owned_registry,
            ),
            sse_active=Gauge(
                "travel_planner_sse_connections_active",
                "Currently active SSE connections.",
                registry=owned_registry,
            ),
            sse_connections=Counter(
                "travel_planner_sse_connections",
                "Completed SSE connections.",
                ("terminal_status",),
                registry=owned_registry,
            ),
            sse_duration=Histogram(
                "travel_planner_sse_connection_duration_seconds",
                "Full SSE connection duration.",
                ("terminal_status",),
                buckets=http_buckets,
                registry=owned_registry,
            ),
            sse_events=Counter(
                "travel_planner_sse_events",
                "Public SSE business events; heartbeat comments are excluded.",
                ("event_type",),
                registry=owned_registry,
            ),
            sse_disconnects=Counter(
                "travel_planner_sse_disconnects",
                "SSE consumer disconnects.",
                registry=owned_registry,
            ),
            llm_requests=Counter(
                "travel_planner_llm_requests",
                "Structured LLM request outcomes.",
                ("role", "status"),
                registry=owned_registry,
            ),
            llm_duration=Histogram(
                "travel_planner_llm_request_duration_seconds",
                "Structured LLM request duration.",
                ("role", "status"),
                buckets=workflow_buckets,
                registry=owned_registry,
            ),
            llm_tokens=Counter(
                "travel_planner_llm_tokens",
                "Provider-reported LLM tokens; missing usage is never estimated.",
                ("direction",),
                registry=owned_registry,
            ),
            intake_turns=Counter(
                "travel_planner_intake_turns",
                "Conversational intake turn outcomes.",
                ("status",),
                registry=owned_registry,
            ),
            intake_turn_duration=Histogram(
                "travel_planner_intake_turn_duration_seconds",
                "Conversational intake turn duration.",
                ("status",),
                buckets=workflow_buckets,
                registry=owned_registry,
            ),
            intake_confirmations=Counter(
                "travel_planner_intake_confirmations",
                "Explicit conversational planning confirmation outcomes.",
                ("status",),
                registry=owned_registry,
            ),
            intake_clarifications=Counter(
                "travel_planner_intake_clarifications",
                "First deterministic clarification field requested.",
                ("field",),
                registry=owned_registry,
            ),
            dependency_ready=Gauge(
                "travel_planner_dependency_ready",
                "Last real readiness result (1 ready, 0 not ready).",
                ("dependency",),
                registry=owned_registry,
            ),
            external_requests=Counter(
                "travel_planner_external_requests",
                "External provider HTTP attempts.",
                ("provider", "operation", "status"),
                registry=owned_registry,
            ),
            external_duration=Histogram(
                "travel_planner_external_request_duration_seconds",
                "External provider HTTP-attempt duration.",
                ("provider", "operation", "status"),
                buckets=workflow_buckets,
                registry=owned_registry,
            ),
            search_sources=Counter(
                "travel_planner_search_source",
                "Completed search branches by truthful data source.",
                ("kind", "source", "status"),
                registry=owned_registry,
            ),
        )
