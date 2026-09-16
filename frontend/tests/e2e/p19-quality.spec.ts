import { expect, test, type Page } from "@playwright/test";
import { createHash } from "node:crypto";
import { resolve } from "node:path";
import process from "node:process";
import { conversationFixture, planFixture } from "../../src/test/fixtures";

test.use({ trace: "off", screenshot: "off", video: "off" });
const thread = "11111111-1111-4111-8111-111111111111";
const forced = { ...planFixture,
  flight: { ...planFixture.flight, data_source: "duffel_test" },
  hotel: { ...planFixture.hotel, data_source: "liteapi_sandbox", total_stay_price: "900.00", stay_nights: 5, has_excluded_fees: true },
  data_sources: { ...planFixture.data_sources, flights: "duffel_test", hotels: "liteapi_sandbox" },
  daily_itinerary: [...planFixture.daily_itinerary,
    { day_number: 3, date: "2027-10-14", title: "Museums and a flexible afternoon", activities: ["Museum visit (Demo)", "Free time"], estimated_cost: "80.00", currency: "USD" },
    { day_number: 4, date: "2027-10-15", title: "Neighborhood photography", activities: ["Quiet streets photography walk (Demo)"], estimated_cost: "70.00", currency: "USD" },
    { day_number: 5, date: "2027-10-16", title: "A relaxed final day", activities: ["Garden walk (Demo)", "Return flight not included"], estimated_cost: "40.00", currency: "USD" }],
  total_cost: "2200.00",
  quality: { review_status: "forced_finalized", review_rounds: 3, final_score: 62.5, finalization_reason: "max_review_rounds_reached", issue_codes: ["noncritical_data_unavailable"] }, warnings: ["route_unavailable", "return_flight_excluded", "excluded_hotel_fees"] };

async function capture(page: Page, number: number, desktop: boolean) {
  if (process.env.CAPTURE_P19_SCREENSHOTS !== "1" || !desktop) return;
  await page.evaluate(() => {
    let label = document.getElementById("fixture-disclosure");
    if (!label) {
      label = document.createElement("div");
      label.id = "fixture-disclosure";
      label.textContent = "Local fixture demonstration · Not cloud acceptance · Test / Sandbox / Demo";
      label.style.cssText = "position:sticky;top:0;z-index:100;background:#0f172a;color:white;padding:10px;text-align:center;font:14px sans-serif";
      document.body.prepend(label);
    }
    window.scrollTo(0, 0);
  });
  await page.screenshot({ path: resolve(process.cwd(), `../docs/images/p19-0${number}.jpg`), type: "jpeg", quality: 80, fullPage: true });
}

test("P19 forced-finalized draft stops, discloses limits and survives refresh", async ({ page }, info) => {
  let starts = 0;
  let planned = false;
  await page.exposeFunction("p19Started", () => { starts += 1; });
  await page.addInitScript(({ threadId, finalPlan }) => {
    localStorage.setItem("travel-planner:user-id", "22222222-2222-4222-8222-222222222222");
    localStorage.setItem("travel-planner:thread-id", threadId);
    const original = window.fetch.bind(window);
    window.fetch = async (input, init) => {
      const url = input instanceof Request ? input.url : input instanceof URL ? input.href : input;
      if (!url.endsWith("/conversation/confirm/stream")) return original(input, init);
      await (window as unknown as { p19Started: () => Promise<void> }).p19Started();
      const events: [string, unknown][] = [
        ["run_started", { backend_mode: "direct", persistent: true }],
        ["retrieval_completed", { returned_parent_count: 1, query_variant_count: 3, cache_status: "miss", metadata_filter_applied: false, metadata_filter_fallback_used: false }],
        ...["flights", "hotels", "attractions", "weather", "route"].map((kind): [string, unknown] => ["search_started", { search_kind: kind }]),
        ...["flights", "hotels", "attractions", "weather"].map((kind): [string, unknown] => ["search_completed", { search_kind: kind, status: "ok", result_count: 1, source: kind === "flights" ? "duffel_test" : kind === "hotels" ? "liteapi_sandbox" : "demo" }]),
        ["search_failed", { search_kind: "route", error_code: "route_unavailable", recoverable: false }],
        ["node_completed", { fixture_node: "planner" }],
        ["review_completed", { review_round: 2, decision: "revise", scores: { completeness: 60, feasibility: 60, personalization: 70, budget_fit: 60, overall_score: 62.5 }, issue_codes: ["noncritical_data_unavailable"], critique: "Some travel data cannot be verified.", suggested_changes: ["Keep explicit limitations."] }],
        ["revision_started", { review_round: 3, issue_codes: ["noncritical_data_unavailable"], suggested_changes: ["Keep explicit limitations."] }],
      ];
      let sequence = 0;
      const encode = (type: string, data: unknown) => {
        sequence += 1;
        const fixtureNode = type === "node_completed" ? (data as { fixture_node: string }).fixture_node : "agent_runtime";
        const event = { event_id: sequence, sequence, thread_id: threadId, timestamp: "2026-09-15T12:00:00Z", node: fixtureNode, status: type.endsWith("started") ? "started" : type === "search_failed" ? "failed" : "completed", event_type: type, message: "Local fixture demonstration", data: type === "node_completed" ? {} : data };
        return new TextEncoder().encode(`id: ${sequence}\nevent: ${type}\ndata: ${JSON.stringify(event)}\n\n`);
      };
      return new Response(new ReadableStream({ start(controller) {
        for (const [type, data] of events) controller.enqueue(encode(type, data));
        window.addEventListener("p19-finish", () => {
          controller.enqueue(encode("review_completed", { review_round: 3, decision: "forced_finalize", scores: { completeness: 60, feasibility: 60, personalization: 70, budget_fit: 60, overall_score: 62.5 }, issue_codes: ["noncritical_data_unavailable"], critique: "Automatic review ended with unresolved travel-data limitations.", suggested_changes: ["Manually verify unavailable travel details."] }));
          controller.enqueue(encode("plan_completed", { travel_plan: finalPlan, review_status: "forced_finalized", review_rounds: 3, final_score: 62.5, finalization_reason: "max_review_rounds_reached" }));
          controller.close();
        }, { once: true });
      } }), { headers: { "Content-Type": "text/event-stream" } });
    };
  }, { threadId: thread, finalPlan: forced });
  await page.route("**/api/v1/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/state")) return route.fulfill({ json: { thread_id: thread, status: "complete", travel_plan: forced, review_round: 3, final_score: 62.5 } });
    const ready = conversationFixture();
    ready.messages = [
      ...ready.messages,
      { ...ready.messages[0], message_id: "msg_333333333333333333333333", content: "Cleveland, October 12–16, 2027. One traveler, 3000 USD; photography and quiet neighborhoods." },
      { ...ready.messages[1], message_id: "msg_444444444444444444444444", content: "Your trip details are ready. Please review and confirm." },
    ];
    return route.fulfill({ json: { ...ready, ...(planned ? { status: "planned", plan_available: true, can_confirm: false } : {}) } });
  });
  await page.route("**/health", (route) => route.fulfill({ json: { status: "ok", service: "ai-travel-planner" } }));
  await page.goto("/");
  const button = page.getByRole("button", { name: /Confirm & Build My Trip/ });
  if (info.project.name === "mobile-chromium") await page.getByRole("button", { name: "Trip details" }).click();
  await expect(button).toBeVisible();
  await capture(page, 1, info.project.name === "desktop-chromium");
  await button.click();
  await expect(page.getByText("Improving your itinerary…")).toBeVisible();
  for (const kind of ["Flights", "Hotels", "Attractions", "Weather", "Route"]) await expect(page.getByText(kind, { exact: true })).toBeVisible();
  await capture(page, 2, info.project.name === "desktop-chromium");
  planned = true;
  await page.evaluate(() => window.dispatchEvent(new Event("p19-finish")));
  await expect(page.getByText("Draft generated — review needed").first()).toBeVisible();
  await expect(page.getByText("Improving your itinerary…")).toHaveCount(0);
  await expect(page.getByLabel("In progress", { exact: true })).toHaveCount(0);
  await expect(page.getByText("62.5", { exact: true })).toHaveCount(2);
  await expect(page.getByText(/No verified intercity/)).toBeVisible();
  await capture(page, 3, info.project.name === "desktop-chromium");
  await page.reload();
  await expect(page.getByText("Draft generated — review needed").first()).toBeVisible();
  await expect(page.getByText("62.5", { exact: true }).first()).toBeVisible();
  expect(starts).toBe(1);
});

test("mock SDK account switching clears private UI and scoped recent metadata", async ({ page }) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  const moduleFailures: string[] = [];
  page.on("response", (response) => {
    if (response.request().resourceType() === "script" && response.status() >= 400) {
      moduleFailures.push(`${response.status()} ${new URL(response.url()).pathname}`);
    }
  });
  // Test-only module interception exercises the actual AuthRoot and App. No Auth0 calls.
  await page.route("**/src/auth/config.ts", (route) => route.fulfill({ contentType: "application/javascript", body: `export function readFrontendConfig(){return {mode:"auth0",domain:"tenant.example",clientId:"fixture",audience:"https://fixture.example",apiBase:""}}` }));
  await page.route("**/@auth0_auth0-react.js*", (route) => route.fulfill({
    contentType: "application/javascript",
    body: 'export { Auth0Provider, useAuth0 } from "/tests/e2e/fixtures/auth0-sdk.ts";',
  }));
  const scopes = ["a", "b"].map((a) => createHash("sha256").update(`tenant.example\0auth0|fixture-${a}`).digest("hex"));
  await page.addInitScript(({ ids, publicId }) => {
    ids.forEach((scope, index) => {
      localStorage.setItem(`travel-planner:thread-id:auth:${scope}`, publicId);
      localStorage.setItem(`travel-planner:recent-threads:auth:${scope}`, JSON.stringify([{ threadId: publicId, createdAt: "2026-09-15T12:00:00Z", title: index ? "Paris private B" : "Tokyo private A" }]));
    });
    // Hold an already received A response, even after its AbortSignal fires.
    // This deliberately tests the stale-response guard, not just fetch cancellation.
    const original = window.fetch.bind(window);
    window.fetch = async (input, init) => {
      const response = await original(input, init);
      const url = input instanceof Request ? input.url : input instanceof URL ? input.href : input;
      if (init?.method === "POST" && new URL(url, location.origin).pathname.startsWith("/api/v1/")) {
        document.documentElement.dataset.p19Pending = "true";
        await new Promise<void>((resolve) => window.addEventListener("p19-deliver-old-response", () => resolve(), { once: true }));
      }
      return response;
    };
  }, { ids: scopes, publicId: thread });
  await page.route("**/api/v1/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    expect([
      `/api/v1/agents/threads/${thread}/conversation`,
      `/api/v1/agents/threads/${thread}/conversation/messages`,
      `/api/v1/agents/threads/${thread}/state`,
    ]).toContain(path);
    const authorization = route.request().headers().authorization;
    expect(["Bearer fixture:a", "Bearer fixture:b"]).toContain(authorization);
    const account = authorization === "Bearer fixture:b" ? "b" : "a";
    const city = account === "a" ? "Tokyo" : "Paris";
    if (path.endsWith("/state")) return route.fulfill({ json: { thread_id: thread, status: "complete", travel_plan: { ...forced, requirements: { ...planFixture.requirements, destination: city }, hotel: { ...planFixture.hotel, name: `Private ${account} hotel` } }, review_round: 3, final_score: 62.5 } });
    const late = route.request().method() === "POST";
    return route.fulfill({ json: conversationFixture({ status: "planned", plan_available: true, can_confirm: false, draft: { ...conversationFixture().draft, destination: late ? "Late private A" : city }, messages: [{ ...conversationFixture().messages[0], content: late ? "Late private A conversation" : `Private ${account} conversation about ${city}` }] }) });
  });
  await page.route("**/health", (route) => route.fulfill({ json: { status: "ok", service: "ai-travel-planner" } }));
  await page.goto("/");
  expect(pageErrors).toEqual([]);
  await expect(page.getByText("Private a hotel")).toBeVisible().catch((error: unknown) => {
    expect({ pageErrors, moduleFailures }).toEqual({ pageErrors: [], moduleFailures: [] });
    throw error;
  });
  await page.getByRole("button", { name: "Conversation", exact: true }).click();
  await expect(page.getByText("Private a conversation about Tokyo")).toBeVisible();
  await page.getByLabel("Describe your trip").fill("Update my private A trip");
  await page.getByRole("button", { name: "Send message", exact: true }).click();
  await expect(page.locator("html")).toHaveAttribute("data-p19-pending", "true");
  await page.evaluate(() => window.dispatchEvent(new CustomEvent("p19-account", { detail: "b" })));
  await expect(page.getByText("Private b hotel")).toBeVisible();
  await expect(page.getByText("Private a hotel")).toHaveCount(0);
  await expect(page.getByText("Tokyo private A")).toHaveCount(0);
  await page.evaluate(async () => {
    window.dispatchEvent(new Event("p19-deliver-old-response"));
    await new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
  });
  await expect(page.getByText("Private b hotel")).toBeVisible();
  await page.getByRole("button", { name: "Conversation", exact: true }).click();
  await expect(page.getByText("Private b conversation about Paris")).toBeVisible();
  await expect(page.getByText("Private a conversation about Tokyo")).toHaveCount(0);
  await expect(page.getByText("Late private A", { exact: false })).toHaveCount(0);
  const bRecent = await page.evaluate((scope) => localStorage.getItem(`travel-planner:recent-threads:auth:${scope}`), scopes[1]);
  expect(bRecent).toContain("Paris");
  expect(bRecent).not.toContain("Tokyo");
  expect(bRecent).not.toContain("Late private A");
  await page.evaluate(() => window.dispatchEvent(new CustomEvent("p19-account", { detail: "a" })));
  await expect(page.getByText("Private a hotel")).toBeVisible();
  await expect(page.getByText("Private b hotel")).toHaveCount(0);
  await page.getByRole("button", { name: "Conversation", exact: true }).click();
  await expect(page.getByText("Private a conversation about Tokyo")).toBeVisible();
  await expect(page.getByText("Private b conversation about Paris")).toHaveCount(0);
  await page.evaluate(() => window.dispatchEvent(new CustomEvent("p19-account", { detail: "b" })));
  await expect(page.getByText("Private b hotel")).toBeVisible();
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("Securing your session");
  await expect(page.getByText("Private b hotel")).toHaveCount(0);
  expect(await page.evaluate((scope) => localStorage.getItem(`travel-planner:recent-threads:auth:${scope}`), scopes[1])).toBeNull();
  expect({ pageErrors, moduleFailures }).toEqual({ pageErrors: [], moduleFailures: [] });
});
