import { z } from "zod";

export const currencies = ["CNY", "USD", "JPY", "EUR"] as const;
export const requirementFields = [
  "origin",
  "destination",
  "start_date",
  "end_date",
  "duration_days",
  "budget",
  "currency",
  "travelers",
  "preferences",
] as const;

const currencySchema = z.enum(currencies);
const requirementFieldSchema = z.enum(requirementFields);
const dateSchema = z.string().regex(/^\d{4}-\d{2}-\d{2}$/);
const decimalSchema = z.string().min(1);

export const partialTripRequirementsSchema = z
  .object({
    origin: z.string().min(1).nullable(),
    destination: z.string().min(1).nullable(),
    start_date: dateSchema.nullable(),
    end_date: dateSchema.nullable(),
    duration_days: z.number().int().positive().nullable(),
    budget: decimalSchema.nullable(),
    currency: currencySchema.nullable(),
    travelers: z.number().int().positive().nullable(),
    preferences: z.array(z.string().min(1)),
  })
  .strict();

export const tripRequirementsSchema = z
  .object({
    origin: z.string().min(1),
    destination: z.string().min(1),
    start_date: dateSchema,
    end_date: dateSchema,
    budget: decimalSchema,
    currency: currencySchema,
    travelers: z.number().int().positive(),
    preferences: z.array(z.string()),
  })
  .strict();

const flightSchema = z
  .object({
    flight_number: z.string().min(1),
    airline: z.string().min(1),
    origin: z.string().min(1),
    destination: z.string().min(1),
    departure_time: z.string().min(1),
    arrival_time: z.string().min(1),
    duration_minutes: z.number().int().positive(),
    price: decimalSchema,
    currency: currencySchema,
  })
  .strict();

const hotelSchema = z
  .object({
    name: z.string().min(1),
    city: z.string().min(1),
    rating: z.number().min(0).max(5),
    price_per_night: decimalSchema,
    currency: currencySchema,
    distance_to_center_km: z.number().nonnegative(),
    amenities: z.array(z.string()),
  })
  .strict();

const dailyItinerarySchema = z
  .object({
    day_number: z.number().int().positive(),
    date: dateSchema,
    title: z.string().min(1),
    activities: z.array(z.string().min(1)).min(1),
    estimated_cost: decimalSchema,
    currency: currencySchema,
  })
  .strict();

export const travelPlanSchema = z
  .object({
    requirements: tripRequirementsSchema,
    flight: flightSchema,
    hotel: hotelSchema,
    daily_itinerary: z.array(dailyItinerarySchema).min(1),
    total_cost: decimalSchema,
    currency: currencySchema,
    budget_warning: z.string().nullable(),
    markdown: z.string(),
  })
  .strict();

const conversationMessageSchema = z
  .object({
    message_id: z.string().min(1),
    role: z.enum(["user", "assistant"]),
    content: z.string().min(1).max(4000),
    created_at: z.string().min(1),
  })
  .strict();

export const conversationResponseSchema = z
  .object({
    thread_id: z.string().min(1),
    user_id: z.string().min(1),
    status: z.enum(["collecting", "awaiting_confirmation", "planning", "planned"]),
    assistant_message: z.string().min(1),
    draft: partialTripRequirementsSchema,
    missing_fields: z.array(requirementFieldSchema),
    invalid_fields: z.array(requirementFieldSchema),
    can_confirm: z.boolean(),
    draft_fingerprint: z.string().regex(/^[0-9a-f]{64}$/),
    messages: z.array(conversationMessageSchema),
    turn_count: z.number().int().nonnegative(),
    version: z.number().int().nonnegative(),
    plan_available: z.boolean(),
  })
  .strict();

export const conversationMessageRequestSchema = z
  .object({
    user_id: z.string().min(1).max(64),
    message: z.string().trim().min(1).max(4000),
    start_new_trip: z.boolean().default(false),
  })
  .strict();

export const confirmRequestSchema = z
  .object({
    user_id: z.string().min(1).max(64),
    draft_fingerprint: z.string().regex(/^[0-9a-f]{64}$/),
    remember_preferences: z.array(z.string().min(1).max(300)).max(50),
  })
  .strict();

const baseEventFields = {
  event_id: z.number().int().positive(),
  thread_id: z.string().min(1),
  sequence: z.number().int().positive(),
  timestamp: z.string().min(1),
  node: z.string().min(1),
  status: z.enum(["started", "completed", "failed"]),
  message: z.string().min(1),
};

const searchKindSchema = z.enum(["flights", "hotels", "attractions", "weather", "route"]);
const emptyDataSchema = z.object({}).strict();
const reviewScoresSchema = z
  .object({
    completeness: z.number().min(0).max(100),
    feasibility: z.number().min(0).max(100),
    personalization: z.number().min(0).max(100),
    budget_fit: z.number().min(0).max(100),
    overall_score: z.number().min(0).max(100),
  })
  .strict();

const runStartedEventSchema = z
  .object({
    ...baseEventFields,
    event_type: z.literal("run_started"),
    data: z
      .object({ backend_mode: z.enum(["direct", "mcp"]), persistent: z.boolean() })
      .strict(),
  })
  .strict();

const nodeEventSchema = z
  .object({
    ...baseEventFields,
    event_type: z.enum(["node_started", "node_completed"]),
    data: emptyDataSchema,
  })
  .strict();

const searchStartedEventSchema = z
  .object({
    ...baseEventFields,
    event_type: z.literal("search_started"),
    data: z.object({ search_kind: searchKindSchema }).strict(),
  })
  .strict();

const searchCompletedEventSchema = z
  .object({
    ...baseEventFields,
    event_type: z.literal("search_completed"),
    data: z
      .object({
        search_kind: searchKindSchema,
        status: z.literal("ok"),
        result_count: z.number().int().nonnegative(),
      })
      .strict(),
  })
  .strict();

const searchFailedEventSchema = z
  .object({
    ...baseEventFields,
    event_type: z.literal("search_failed"),
    data: z
      .object({
        search_kind: searchKindSchema,
        error_code: z.string().min(1),
        recoverable: z.boolean(),
      })
      .strict(),
  })
  .strict();

const retrievalEventSchema = z
  .object({
    ...baseEventFields,
    event_type: z.literal("retrieval_completed"),
    data: z
      .object({
        returned_parent_count: z.number().int().nonnegative().optional(),
        query_variant_count: z.number().int().nonnegative().optional(),
        cache_status: z.string().optional(),
        metadata_filter_applied: z.boolean().optional(),
        metadata_filter_fallback_used: z.boolean().optional(),
        error_code: z.string().optional(),
      })
      .strict(),
  })
  .strict();

const reviewEventSchema = z
  .object({
    ...baseEventFields,
    event_type: z.literal("review_completed"),
    data: z
      .object({
        review_round: z.number().int().positive(),
        decision: z.enum(["accept", "revise", "forced_finalize"]),
        scores: reviewScoresSchema,
        issue_codes: z.array(z.string()),
        critique: z.string(),
        suggested_changes: z.array(z.string()),
        review_status: z.string().optional(),
        finalization_reason: z.string().optional(),
      })
      .strict(),
  })
  .strict();

const revisionEventSchema = z
  .object({
    ...baseEventFields,
    event_type: z.literal("revision_started"),
    data: z
      .object({
        review_round: z.number().int().positive(),
        issue_codes: z.array(z.string()),
        suggested_changes: z.array(z.string()),
      })
      .strict(),
  })
  .strict();

const planCompletedEventSchema = z
  .object({
    ...baseEventFields,
    event_type: z.literal("plan_completed"),
    data: z
      .object({
        travel_plan: travelPlanSchema,
        review_status: z.string().optional(),
        review_rounds: z.number().int().nonnegative().optional(),
        final_score: z.number().min(0).max(100).optional(),
        finalization_reason: z.string().optional(),
      })
      .strict(),
  })
  .strict();

const errorEventSchema = z
  .object({
    ...baseEventFields,
    event_type: z.literal("error"),
    data: z
      .object({
        error_code: z.string().min(1),
        safe_message: z.string().min(1),
        recoverable: z.boolean(),
      })
      .strict(),
  })
  .strict();

export const streamBusinessEventSchema = z.discriminatedUnion("event_type", [
  runStartedEventSchema,
  nodeEventSchema,
  searchStartedEventSchema,
  searchCompletedEventSchema,
  searchFailedEventSchema,
  retrievalEventSchema,
  reviewEventSchema,
  revisionEventSchema,
  planCompletedEventSchema,
  errorEventSchema,
]);

export const knownStreamEventTypes = new Set([
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
]);

export const healthResponseSchema = z
  .object({ status: z.literal("ok"), service: z.string().min(1) })
  .passthrough();

export const threadStateResponseSchema = z
  .object({
    thread_id: z.string().min(1),
    status: z.enum(["empty", "running", "complete", "error"]),
    travel_plan: travelPlanSchema.nullable(),
    review_round: z.number().int().nonnegative(),
    final_score: z.number().min(0).max(100).nullable(),
  })
  .passthrough();
