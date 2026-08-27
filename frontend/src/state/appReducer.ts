import type {
  ConversationResponse,
  PublicReview,
  SearchKind,
  StreamBusinessEvent,
  TravelPlan,
} from "../api/types";
import type { AppError } from "../lib/errors";

export type UiPhase =
  | "booting"
  | "collecting"
  | "awaiting_confirmation"
  | "planning"
  | "planned"
  | "error";
export type ProgressStatus = "pending" | "running" | "completed" | "failed";

export interface PlanningProgress {
  stages: Record<
    "understanding" | "knowledge" | "search" | "drafting" | "reviewing" | "finalizing",
    ProgressStatus
  >;
  searches: Record<SearchKind, ProgressStatus>;
  reviews: PublicReview[];
  revisionRound: number | null;
  latestMessage: string;
  publicEvents: string[];
}

export interface AppState {
  phase: UiPhase;
  conversation: ConversationResponse | null;
  optimisticMessage: string | null;
  failedMessage: string | null;
  finalPlan: TravelPlan | null;
  progress: PlanningProgress;
  error: AppError | null;
}

export type AppAction =
  | { type: "LOAD_START" }
  | { type: "LOAD_EMPTY" }
  | { type: "CONVERSATION_RECEIVED"; conversation: ConversationResponse }
  | { type: "PLAN_RESTORED"; plan: TravelPlan }
  | { type: "SEND_START"; message: string }
  | { type: "SEND_FAILED"; message: string; error: AppError }
  | { type: "PLAN_START" }
  | { type: "STREAM_EVENT"; event: StreamBusinessEvent }
  | { type: "STOPPED" }
  | { type: "SHOW_ERROR"; error: AppError }
  | { type: "CLEAR_ERROR" }
  | { type: "CLEAR_TRIP" };

const stageNames = [
  "understanding",
  "knowledge",
  "search",
  "drafting",
  "reviewing",
  "finalizing",
] as const;
const searchKinds: SearchKind[] = ["flights", "hotels", "attractions", "weather", "route"];

export function freshProgress(): PlanningProgress {
  return {
    stages: Object.fromEntries(stageNames.map((name) => [name, "pending"])) as PlanningProgress["stages"],
    searches: Object.fromEntries(searchKinds.map((name) => [name, "pending"])) as PlanningProgress["searches"],
    reviews: [],
    revisionRound: null,
    latestMessage: "Waiting to begin.",
    publicEvents: [],
  };
}

export const initialAppState: AppState = {
  phase: "booting",
  conversation: null,
  optimisticMessage: null,
  failedMessage: null,
  finalPlan: null,
  progress: freshProgress(),
  error: null,
};

function phaseForConversation(conversation: ConversationResponse): UiPhase {
  if (conversation.status === "planned") return "planned";
  if (conversation.status === "planning") return "planning";
  return conversation.status;
}

function withStage(
  progress: PlanningProgress,
  stage: keyof PlanningProgress["stages"],
  status: ProgressStatus,
): PlanningProgress {
  return { ...progress, stages: { ...progress.stages, [stage]: status } };
}

function applyStreamEvent(progress: PlanningProgress, event: StreamBusinessEvent): PlanningProgress {
  let next: PlanningProgress = {
    ...progress,
    latestMessage: event.message,
    publicEvents: [...progress.publicEvents, event.event_type].slice(-30),
  };
  if (event.event_type === "run_started") {
    next = withStage(next, "understanding", "running");
  } else if (event.event_type === "retrieval_completed") {
    next = withStage(withStage(next, "understanding", "completed"), "knowledge", "completed");
  } else if (event.event_type === "search_started") {
    next = withStage(next, "search", "running");
    next = {
      ...next,
      searches: { ...next.searches, [event.data.search_kind]: "running" },
    };
  } else if (event.event_type === "search_completed" || event.event_type === "search_failed") {
    const searchStatus = event.event_type === "search_completed" ? "completed" : "failed";
    const searches = { ...next.searches, [event.data.search_kind]: searchStatus };
    const allFinished = Object.values(searches).every(
      (status) => status === "completed" || status === "failed",
    );
    next = {
      ...next,
      searches,
      stages: { ...next.stages, search: allFinished ? "completed" : "running" },
    };
  } else if (event.event_type === "node_started" && event.node === "planner") {
    next = withStage(next, "drafting", "running");
  } else if (event.event_type === "node_completed" && event.node === "planner") {
    next = withStage(next, "drafting", event.status === "failed" ? "failed" : "completed");
  } else if (event.event_type === "review_completed") {
    next = withStage(next, "reviewing", "completed");
    next = {
      ...next,
      reviews: [
        ...next.reviews,
        {
          reviewRound: event.data.review_round,
          decision: event.data.decision,
          scores: event.data.scores,
          critique: event.data.critique,
        },
      ],
    };
  } else if (event.event_type === "revision_started") {
    next = withStage(next, "reviewing", "running");
    next = { ...next, revisionRound: event.data.review_round };
  } else if (event.event_type === "plan_completed") {
    next = withStage(next, "finalizing", "completed");
  } else if (event.event_type === "error") {
    next = withStage(next, "finalizing", "failed");
  }
  return next;
}

/** Keep all browser UI transitions explicit and deterministic. */
export function appReducer(state: AppState, action: AppAction): AppState {
  switch (action.type) {
    case "LOAD_START":
      return { ...state, phase: "booting", error: null, optimisticMessage: null };
    case "LOAD_EMPTY":
      return { ...initialAppState, phase: "collecting", progress: freshProgress() };
    case "CONVERSATION_RECEIVED":
      return {
        ...state,
        conversation: action.conversation,
        phase: phaseForConversation(action.conversation),
        optimisticMessage: null,
        failedMessage: null,
        error: null,
      };
    case "PLAN_RESTORED":
      return { ...state, phase: "planned", finalPlan: action.plan };
    case "SEND_START":
      return {
        ...state,
        optimisticMessage: action.message,
        failedMessage: null,
        error: null,
      };
    case "SEND_FAILED":
      return {
        ...state,
        phase: "error",
        optimisticMessage: null,
        failedMessage: action.message,
        error: action.error,
      };
    case "PLAN_START":
      return {
        ...state,
        phase: "planning",
        finalPlan: null,
        error: null,
        progress: freshProgress(),
      };
    case "STREAM_EVENT": {
      const progress = applyStreamEvent(state.progress, action.event);
      if (action.event.event_type === "plan_completed") {
        return {
          ...state,
          phase: "planned",
          finalPlan: action.event.data.travel_plan,
          progress,
          error: null,
        };
      }
      if (action.event.event_type === "error") {
        return { ...state, phase: "error", progress };
      }
      return { ...state, progress };
    }
    case "STOPPED":
      return {
        ...state,
        phase: state.conversation?.can_confirm === true ? "awaiting_confirmation" : "collecting",
        error: null,
      };
    case "SHOW_ERROR":
      return { ...state, phase: "error", error: action.error };
    case "CLEAR_ERROR":
      return {
        ...state,
        phase: state.conversation === null ? "collecting" : phaseForConversation(state.conversation),
        error: null,
      };
    case "CLEAR_TRIP":
      return { ...initialAppState, phase: "collecting", progress: freshProgress() };
  }
}
