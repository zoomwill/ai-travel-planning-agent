import { expect, test, type Page } from "@playwright/test";
import process from "node:process";

const fingerprint = "a".repeat(64);
const userId = "22222222-2222-4222-8222-222222222222";
const threadId = "11111111-1111-4111-8111-111111111111";

const emptyDraft = { origin: null, destination: null, start_date: null, end_date: null, duration_days: null, budget: null, currency: null, travelers: null, preferences: [] };
const completeDraft = { origin: "Cleveland", destination: "Tokyo", start_date: "2027-10-12", end_date: "2027-10-16", duration_days: 5, budget: "3000.00", currency: "USD", travelers: 1, preferences: ["photography", "quiet neighborhoods"] };
const plan = {
  requirements: { origin: "Cleveland", destination: "Tokyo", start_date: "2027-10-12", end_date: "2027-10-16", budget: "3000.00", currency: "USD", travelers: 1, preferences: ["photography", "quiet neighborhoods"] },
  flight: { flight_number: "MK318", airline: "Mock Pacific", origin: "Cleveland", destination: "Tokyo", departure_time: "2027-10-12T08:30:00Z", arrival_time: "2027-10-12T20:30:00Z", duration_minutes: 720, price: "900.00", currency: "USD", segments: [], stops: 0, provider_offer_id: null, expires_at: null, data_source: "demo" },
  hotel: { name: "Tokyo Quiet Hotel", city: "Tokyo", rating: 4.6, review_score: null, price_per_night: "180.00", currency: "USD", distance_to_center_km: 2.1, amenities: ["Wi-Fi", "breakfast"], provider_hotel_id: null, provider_search_result_id: null, data_source: "demo" },
  daily_itinerary: [{ day_number: 1, date: "2027-10-12", title: "Arrival and quiet Tokyo", activities: ["Hotel check-in", "Photography walk"], estimated_cost: "120.00", currency: "USD" }],
  total_cost: "1810.00", currency: "USD", budget_warning: null, markdown: "# Tokyo",
  data_sources: { flights: "duffel_test", hotels: "liteapi_sandbox", attractions: "demo", weather: "demo", route: "demo" },
};

// Fake browser payloads exercise mixed provenance without contacting either provider.
plan.flight.data_source = "duffel_test";
const mixedPlan = { ...plan, hotel: { ...plan.hotel, data_source: "liteapi_sandbox",
  total_stay_price: "501.01", price_per_night: "100.20", stay_nights: 5, room_name: "Standard Room",
  board_name: "Room Only", has_excluded_fees: true } };

function conversation(status: "collecting" | "awaiting_confirmation", complete: boolean) {
  return {
    thread_id: threadId, user_id: userId, status,
    assistant_message: complete ? "Your trip is ready to review." : "What dates, budget, and party size work for you?",
    draft: complete ? completeDraft : { ...emptyDraft, destination: "Tokyo", preferences: ["photography", "quiet neighborhoods"] },
    missing_fields: complete ? [] : ["origin", "start_date", "end_date", "budget", "currency", "travelers"], invalid_fields: [], can_confirm: complete,
    draft_fingerprint: fingerprint, turn_count: complete ? 2 : 1, version: complete ? 2 : 1, plan_available: false,
    messages: complete ? [
      { message_id: "msg_111111111111111111111111", role: "user", content: "I want to visit Tokyo and love photography.", created_at: "2026-08-27T12:00:00Z" },
      { message_id: "msg_222222222222222222222222", role: "assistant", content: "What dates, budget, and party size work for you?", created_at: "2026-08-27T12:00:01Z" },
      { message_id: "msg_333333333333333333333333", role: "user", content: "Cleveland, October 12 for five days, one traveler, 3000 USD.", created_at: "2026-08-27T12:01:00Z" },
      { message_id: "msg_444444444444444444444444", role: "assistant", content: "Your trip is ready to review.", created_at: "2026-08-27T12:01:01Z" },
    ] : [
      { message_id: "msg_111111111111111111111111", role: "user", content: "I want to visit Tokyo and love photography.", created_at: "2026-08-27T12:00:00Z" },
      { message_id: "msg_222222222222222222222222", role: "assistant", content: "What dates, budget, and party size work for you?", created_at: "2026-08-27T12:00:01Z" },
    ],
  };
}

function event(eventType: string, data: object, sequence: number, node = "agent_runtime") {
  return { event_id: sequence, sequence, thread_id: threadId, timestamp: "2026-08-27T12:00:00Z", node, status: eventType === "search_started" || eventType === "run_started" ? "started" : "completed", event_type: eventType, message: `${eventType} message`, data };
}

async function installRoutes(page: Page): Promise<void> {
  await page.addInitScript(({ userIdValue, threadIdValue }) => {
    localStorage.setItem("travel-planner:user-id", userIdValue);
    localStorage.setItem("travel-planner:thread-id", threadIdValue);
  }, { userIdValue: userId, threadIdValue: threadId });
  let messages = 0;
  let planned = false;
  await page.route("**/health", (route) => route.fulfill({ status: 200, json: { status: "ok", service: "ai-travel-planner" } }));
  await page.route("**/api/v1/agents/threads/*/conversation?user_id=*", (route) => {
    if (messages === 0) return route.fulfill({ status: 404, json: { detail: { code: "not_found" } } });
    const body = conversation("awaiting_confirmation", messages > 1);
    return route.fulfill({
      status: 200,
      json: planned
        ? { ...body, status: "planned", can_confirm: false, plan_available: true }
        : body,
    });
  });
  await page.route("**/api/v1/agents/threads/*/conversation/messages", async (route) => {
    messages += 1;
    await route.fulfill({ status: 200, json: conversation(messages > 1 ? "awaiting_confirmation" : "collecting", messages > 1) });
  });
  await page.route("**/api/v1/agents/threads/*/conversation/confirm/stream", async (route) => {
    const request = route.request().postDataJSON() as { draft_fingerprint: string };
    expect(request.draft_fingerprint).toBe(fingerprint);
    const events = [
      event("run_started", { backend_mode: "direct", persistent: true }, 1),
      event("node_started", {}, 2, "memory_context"),
      event("node_completed", {}, 3, "memory_context"),
      event("node_started", {}, 4, "advanced_retriever"),
      event("retrieval_completed", { returned_parent_count: 1, query_variant_count: 3, cache_status: "miss", metadata_filter_applied: false, metadata_filter_fallback_used: false }, 5, "advanced_retriever"),
      event("node_completed", {}, 6, "advanced_retriever"),
      ...(["flights", "hotels", "attractions", "weather", "route"] as const).flatMap((kind, index) => [event("search_started", { search_kind: kind }, 7 + index * 2, "travel_search"), event("search_completed", { search_kind: kind, status: "ok", result_count: 1, source: plan.data_sources[kind] }, 8 + index * 2, "travel_search")]),
      event("node_started", {}, 17, "planner"),
      event("node_completed", {}, 18, "planner"),
      event("review_completed", { review_round: 1, decision: "accept", scores: { completeness: 90, feasibility: 88, personalization: 92, budget_fit: 95, overall_score: 91 }, issue_codes: [], critique: "The plan is ready.", suggested_changes: [] }, 19, "reviewer"),
      event("plan_completed", { travel_plan: mixedPlan, review_status: "accepted", review_rounds: 1, final_score: 91 }, 20, "finalize_plan"),
    ];
    planned = true;
    await route.fulfill({ status: 200, contentType: "text/event-stream", body: events.map((item) => `id: ${item.event_id}\nevent: ${item.event_type}\ndata: ${JSON.stringify(item)}\n\n`).join("") });
  });
}

test("mock two-turn chat confirms through POST SSE and renders the itinerary", async ({ page }, testInfo) => {
  await installRoutes(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Where do you want to go?" })).toBeVisible();
  await page.getByLabel("Describe your trip").fill("I want to visit Tokyo and love photography.");
  await page.getByLabel("Send message").click();
  await expect(page.getByText("What dates, budget, and party size work for you?")).toBeVisible();
  await page.getByLabel("Describe your trip").fill("Cleveland, October 12 for five days, one traveler, 3000 USD.");
  await page.getByLabel("Send message").click();
  await page.reload();
  await expect(page.getByText("Your trip is ready to review.")).toBeVisible();
  const confirm = page.getByRole("button", { name: /Confirm & Build My Trip/ });
  if (!(await confirm.isVisible())) await page.getByRole("button", { name: "Trip details" }).click();
  await expect(confirm).toBeVisible();
  await confirm.click();
  await expect(page.getByRole("heading", { name: /Cleveland.*Tokyo/ })).toBeVisible();
  await expect(page.getByText("Tokyo Quiet Hotel")).toBeVisible();
  await expect(page.getByText("LiteAPI Sandbox", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Duffel Test · Test data", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Demo", { exact: true }).first()).toBeVisible();
  await expect(page.getByText(/Additional property fees/)).toBeVisible();
  await expect(page.getByRole("button", { name: /book|reserve|pay|checkout/i })).toHaveCount(0);
  await expect(page.getByText(/not live booking inventory/)).toBeVisible();
  if (process.env.CAPTURE_UI_SCREENSHOTS === "1") {
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: testInfo.outputPath("final-itinerary.png"), fullPage: true });
  }
});
