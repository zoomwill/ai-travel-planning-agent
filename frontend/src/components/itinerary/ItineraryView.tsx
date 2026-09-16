import { AlertTriangle, ArrowRight, Building2, CalendarDays, Clock, Plane, Star, Users, Wallet } from "lucide-react";
import { useEffect, useRef } from "react";

import type { TravelPlan } from "../../api/types";
import { formatDate, formatDateTime, formatDuration, formatMoney } from "../../lib/formatters";

type DataSource = TravelPlan["data_sources"][keyof TravelPlan["data_sources"]];

const sourceLabels: Record<DataSource, string> = {
  demo: "Demo",
  duffel_test: "Duffel Test · Test data",
  duffel_live: "Duffel Live",
  liteapi_sandbox: "LiteAPI Sandbox",
  liteapi_production: "LiteAPI Production",
  demo_fallback: "Demo Fallback",
};

const warningLabels: Record<TravelPlan["warnings"][number], string> = {
  route_unavailable: "Route information unavailable. No verified intercity or local transit duration is provided.",
  historical_route_unverified: "Historical route information is unverified. Do not rely on saved transit times; this record has not been rewritten.",
  attractions_unavailable: "Attraction information unavailable. Verify visits independently.",
  weather_unavailable: "Weather information unavailable. Check a current forecast before travel.",
  return_flight_excluded: "Return flight excluded from the estimate.",
  excluded_hotel_fees: "Excluded hotel fees may be payable separately.",
};

const issueLabels: Record<NonNullable<TravelPlan["quality"]>["issue_codes"][number], string> = {
  missing_required_content: "Required information is missing.",
  budget_overrun: "The estimate exceeds the budget.",
  itinerary_too_dense: "The itinerary may be too dense.",
  personalization_missing: "Preferences are not fully reflected.",
  noncritical_data_unavailable: "Some non-critical travel data is unavailable.",
  inconsistent_dates: "Dates need checking.",
  invalid_cost_breakdown: "The cost breakdown needs checking.",
  general_quality_issue: "The reviewer identified a remaining quality issue.",
};

function SourceBadge({ source }: { source: DataSource }) {
  return <span className={`source-badge source-${source}`}>{sourceLabels[source]}</span>;
}

/** Render the validated structured plan without injecting HTML or recalculating prices. */
export function ItineraryView({ plan }: { plan: TravelPlan }) {
  const headingRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => headingRef.current?.focus(), [plan]);
  const sourceRows = Object.entries(plan.data_sources) as [string, DataSource][];
  const hasExternal = sourceRows.some(([, source]) => source.startsWith("duffel_") || source.startsWith("liteapi_"));
  const hasLiteAPISandbox = sourceRows.some(([, source]) => source === "liteapi_sandbox");
  const hasDuffelTest = sourceRows.some(([, source]) => source === "duffel_test");
  const hasFallback = sourceRows.some(([, source]) => source === "demo_fallback");
  const flightSegments = plan.flight.segments.length > 0 ? plan.flight.segments : null;
  const quality = plan.quality;
  const outcome = quality?.review_status === "accepted" ? "Reviewer accepted — verify travel details"
    : quality?.review_status === "forced_finalized" ? "Draft generated — review needed"
    : "Saved draft — historical review unavailable";
  const warnings = [...plan.warnings];
  if (quality === null && !warnings.includes("historical_route_unverified") && !warnings.includes("route_unavailable")) warnings.push("historical_route_unverified");
  // The current backend contract treats both trip dates as inclusive hotel nights.
  const checkout = new Date(`${plan.requirements.end_date}T00:00:00Z`);
  checkout.setUTCDate(checkout.getUTCDate() + 1);
  const checkoutDate = checkout.toISOString().slice(0, 10);
  const nights = plan.hotel.stay_nights ?? Math.round((checkout.getTime() - Date.parse(`${plan.requirements.start_date}T00:00:00Z`)) / 86_400_000);

  return (
    <section className="results-view" aria-labelledby="trip-results-heading">
      <div className="results-hero">
        <div>
          <p className="eyebrow text-indigo-200">{outcome}</p>
          <h1 id="trip-results-heading" ref={headingRef} tabIndex={-1} className="mt-2 text-3xl font-bold tracking-tight text-white sm:text-4xl">
            {plan.requirements.origin} <ArrowRight className="inline" aria-hidden="true" /> {plan.requirements.destination}
          </h1>
          <div className="mt-5 flex flex-wrap gap-4 text-sm text-indigo-100">
            <span className="hero-detail"><CalendarDays size={16} />{formatDate(plan.requirements.start_date)} – {formatDate(plan.requirements.end_date)}</span>
            <span className="hero-detail"><Users size={16} />{plan.requirements.travelers} traveler{plan.requirements.travelers === 1 ? "" : "s"}</span>
            <span className="hero-detail"><Wallet size={16} />{formatMoney(plan.total_cost, plan.currency)} estimated</span>
          </div>
        </div>
        <SourceBadge source={plan.data_sources.flights} />
      </div>

      {plan.budget_warning !== null && <div className="budget-warning" role="status"><AlertTriangle aria-hidden="true" size={20} /><div><p className="font-semibold">Budget note</p><p>{plan.budget_warning}</p></div></div>}

      <section className="review-summary" aria-label="Final review summary"><div><p className="eyebrow">Workflow ended · not a factual guarantee</p><h2 className="mt-1 text-xl font-bold text-slate-950">Final review summary</h2><p>{outcome}</p>
        {quality?.review_status === "forced_finalized" && <p>Maximum review rounds reached. Automatic improvement has stopped; check the unresolved issues before using this draft.</p>}
        {quality !== null && quality.review_rounds > 0 && <p>Review round {quality.review_rounds}</p>}
        {quality !== null && quality.issue_codes.length > 0 && <ul aria-label="Review issues">{quality.issue_codes.map((issue) => <li key={issue}>{issueLabels[issue]}</li>)}</ul>}
        {warnings.length > 0 && <ul aria-label="Travel limitations">{warnings.map((warning) => <li key={warning}>{warningLabels[warning]}</li>)}</ul>}
      </div><div className="review-score"><span>{quality?.final_score ?? "Unknown"}</span><small>{quality?.final_score == null ? "score unavailable" : "/ 100"}</small></div></section>

      <section className="source-summary" aria-labelledby="data-sources-heading">
        <div><p className="eyebrow">Data Sources</p><h2 id="data-sources-heading" className="mt-1 text-lg font-bold text-slate-950">Mixed-source disclosure</h2></div>
        <dl>{sourceRows.map(([kind, source]) => <div key={kind}><dt>{kind.charAt(0).toUpperCase() + kind.slice(1)}</dt><dd><SourceBadge source={source} /></dd></div>)}</dl>
      </section>

      <div className="result-card-grid">
        <article className="result-card">
          <div className="result-card-icon"><Plane aria-hidden="true" size={20} /></div>
          <div className="flex-1">
            <p className="eyebrow">Flight <SourceBadge source={plan.flight.data_source} /></p>
            <p className="mt-2 text-sm text-slate-500">Outbound one-way fare. Return flight is not included in this estimate.</p>
            <h2 className="mt-1 text-lg font-bold text-slate-950">{plan.flight.airline} {plan.flight.flight_number}</h2>
            <p className="mt-2 text-sm text-slate-500">{plan.flight.origin} → {plan.flight.destination} · {plan.flight.stops === 0 ? "Nonstop" : `${plan.flight.stops} stop${plan.flight.stops === 1 ? "" : "s"}`}</p>
            {flightSegments !== null && <ol className="segment-list" aria-label="Flight segments">{flightSegments.map((segment, index) => <li key={`${segment.flight_number}-${index}`}><strong>{segment.airline} · {segment.flight_number}</strong><span>{segment.origin_iata_code} → {segment.destination_iata_code}</span><small>{formatDateTime(segment.departure_time)} – {formatDateTime(segment.arrival_time)}</small></li>)}</ol>}
            <div className="mt-4 grid grid-cols-2 gap-3 text-sm"><div><p className="text-slate-400">Departure</p><p className="font-medium">{formatDateTime(plan.flight.departure_time)}</p></div><div><p className="text-slate-400">Arrival</p><p className="font-medium">{formatDateTime(plan.flight.arrival_time)}</p></div><div><p className="text-slate-400">Duration</p><p className="font-medium">{formatDuration(plan.flight.duration_minutes)}</p></div><div><p className="text-slate-400">Price</p><p className="font-medium">{formatMoney(plan.flight.price, plan.flight.currency)}</p></div></div>
          </div>
        </article>
        <article className="result-card">
          <div className="result-card-icon"><Building2 aria-hidden="true" size={20} /></div>
          <div className="flex-1">
            <p className="eyebrow">Hotel <SourceBadge source={plan.hotel.data_source} /></p>
            <h2 className="mt-1 text-lg font-bold text-slate-950">{plan.hotel.name}</h2>
            <p className="mt-2 text-sm text-slate-500">Check-in {formatDate(plan.requirements.start_date)} · Check-out {formatDate(checkoutDate)} · {nights} nights (trip end date included)</p>
            <p className="mt-2 flex items-center gap-1 text-sm text-amber-600"><Star aria-hidden="true" size={15} fill={plan.hotel.rating === null ? "none" : "currentColor"} /> {plan.hotel.rating === null ? "Rating unavailable" : `${plan.hotel.rating.toFixed(1)} stars`}{plan.hotel.distance_to_center_km === null ? "" : ` · ${plan.hotel.distance_to_center_km} km from center`}</p>
            {plan.hotel.review_score !== null && <p className="mt-1 text-sm text-slate-500">Guest review score: {plan.hotel.review_score.toFixed(1)} / 10</p>}
            <p className="mt-4 text-lg font-bold text-slate-950">{formatMoney(plan.hotel.price_per_night, plan.hotel.currency)} <span className="text-sm font-normal text-slate-400">/ night</span></p>
            {plan.hotel.total_stay_price !== null && <p>Total stay quote: {formatMoney(plan.hotel.total_stay_price, plan.hotel.currency)}{plan.hotel.stay_nights !== null ? ` · ${plan.hotel.stay_nights} nights` : ""}</p>}
            {plan.hotel.room_name !== null && <p>{plan.hotel.room_name}</p>}
            {plan.hotel.board_name !== null && <p>{plan.hotel.board_name}</p>}
            {plan.hotel.refundable !== null && <p>{plan.hotel.refundable ? "Refundable rate (conditions apply)" : "Non-refundable rate"}</p>}
            {plan.hotel.has_excluded_fees && <p className="budget-warning" role="status">Additional property fees may be payable at the hotel. These are not included in the displayed total.</p>}
            <div className="mt-3 flex flex-wrap gap-2">{plan.hotel.amenities.map((amenity) => <span className="preference-chip" key={amenity}>{amenity}</span>)}</div>
          </div>
        </article>
      </div>

      <div className="mt-8">
        <p className="eyebrow">Daily itinerary</p>
        <h2 className="mt-1 text-2xl font-bold text-slate-950">Day by day</h2>
        <div className="mt-5 space-y-4">
          {plan.daily_itinerary.map((day) => (
            <article className="day-card" key={day.day_number}>
              <div className="day-number"><span>Day</span>{day.day_number}</div>
              <div className="min-w-0 flex-1"><div className="flex flex-wrap items-baseline justify-between gap-2"><div><p className="text-sm text-slate-400">{formatDate(day.date)}</p><h3 className="mt-1 text-lg font-bold text-slate-950">{day.title}</h3></div><p className="font-semibold text-indigo-700">{formatMoney(day.estimated_cost, day.currency)}</p></div><ol className="activity-list">{day.activities.map((activity, index) => <li key={`${day.day_number}-${index}`}><Clock aria-hidden="true" size={15} /><span>{activity}</span></li>)}</ol></div>
            </article>
          ))}
        </div>
      </div>

      <p className="demo-disclosure">
        Displayed results are not live booking inventory, and this app has no booking capability.{" "}
        {hasFallback ? "External search failed and an explicitly enabled demo fallback was used. " : ""}
        {hasExternal ? "External provider results are search results only. " : "Demo flights and hotels are deterministic sample data. "}
        {hasLiteAPISandbox ? "LiteAPI Sandbox hotel data is not production inventory. " : ""}
        {hasDuffelTest ? "Duffel Test prices are test data, not live production prices. " : ""}
        Demo attractions, weather, and routes are deterministic sample data. Verify prices, availability, weather, and opening hours independently.
      </p>
    </section>
  );
}
