import { conversationResponseSchema, streamBusinessEventSchema, travelPlanSchema } from "../api/schemas";
import type { ConversationResponse, StreamBusinessEvent, TravelPlan } from "../api/types";

export const fingerprint = "a".repeat(64);

export const planFixture: TravelPlan = travelPlanSchema.parse({
  requirements: {
    origin: "Cleveland",
    destination: "Tokyo",
    start_date: "2027-10-12",
    end_date: "2027-10-16",
    budget: "3000.00",
    currency: "USD",
    travelers: 1,
    preferences: ["photography", "quiet neighborhoods"],
  },
  flight: {
    flight_number: "MK318",
    airline: "Mock Pacific",
    origin: "Cleveland",
    destination: "Tokyo",
    departure_time: "2027-10-12T08:30:00Z",
    arrival_time: "2027-10-12T20:30:00Z",
    duration_minutes: 720,
    price: "900.00",
    currency: "USD",
    segments: [],
    stops: 0,
    provider_offer_id: null,
    expires_at: null,
    data_source: "demo",
  },
  hotel: {
    name: "Tokyo Quiet Hotel",
    city: "Tokyo",
    rating: 4.6,
    review_score: null,
    price_per_night: "180.00",
    currency: "USD",
    distance_to_center_km: 2.1,
    amenities: ["Wi-Fi", "breakfast"],
    provider_hotel_id: null,
    provider_search_result_id: null,
    data_source: "demo",
  },
  daily_itinerary: [
    {
      day_number: 1,
      date: "2027-10-12",
      title: "Arrival and evening walk",
      activities: ["Hotel check-in", "Quiet neighborhood photography walk"],
      estimated_cost: "120.00",
      currency: "USD",
    },
    {
      day_number: 2,
      date: "2027-10-13",
      title: "Old Tokyo photography",
      activities: ["Early Asakusa walk", "Garden visit"],
      estimated_cost: "90.00",
      currency: "USD",
    },
  ],
  total_cost: "1810.00",
  currency: "USD",
  budget_warning: null,
  markdown: "# Cleveland to Tokyo",
  data_sources: {
    flights: "demo",
    hotels: "demo",
    attractions: "demo",
    weather: "demo",
    route: "demo",
  },
});

export function conversationFixture(
  overrides: Partial<ConversationResponse> = {},
): ConversationResponse {
  return conversationResponseSchema.parse({
    thread_id: "11111111-1111-4111-8111-111111111111",
    user_id: "22222222-2222-4222-8222-222222222222",
    status: "awaiting_confirmation",
    assistant_message: "Your trip details are ready to review.",
    draft: {
      origin: "Cleveland",
      destination: "Tokyo",
      start_date: "2027-10-12",
      end_date: "2027-10-16",
      duration_days: 5,
      budget: "3000.00",
      currency: "USD",
      travelers: 1,
      preferences: ["photography", "quiet neighborhoods"],
    },
    missing_fields: [],
    invalid_fields: [],
    can_confirm: true,
    draft_fingerprint: fingerprint,
    messages: [
      {
        message_id: "msg_111111111111111111111111",
        role: "user",
        content: "I want to visit Tokyo.",
        created_at: "2026-08-27T12:00:00Z",
      },
      {
        message_id: "msg_222222222222222222222222",
        role: "assistant",
        content: "What dates and budget work for you?",
        created_at: "2026-08-27T12:00:01Z",
      },
    ],
    turn_count: 1,
    version: 1,
    plan_available: false,
    ...overrides,
  });
}

export function streamEvent(
  eventType: StreamBusinessEvent["event_type"],
  data: unknown,
  sequence = 1,
  node = "agent_runtime",
): StreamBusinessEvent {
  return streamBusinessEventSchema.parse({
    event_id: sequence,
    sequence,
    thread_id: "11111111-1111-4111-8111-111111111111",
    timestamp: "2026-08-27T12:00:00Z",
    node,
    status: eventType === "error" || eventType === "search_failed" ? "failed" : eventType.endsWith("started") ? "started" : "completed",
    event_type: eventType,
    message: `${eventType} message`,
    data,
  });
}
