import { AlertTriangle, ArrowRight, Building2, CalendarDays, Clock, Plane, Star, Users, Wallet } from "lucide-react";
import { useEffect, useRef } from "react";

import type { PublicReview, TravelPlan } from "../../api/types";
import { formatDate, formatDateTime, formatDuration, formatMoney } from "../../lib/formatters";

/** Render the validated structured plan without injecting HTML or recalculating prices. */
export function ItineraryView({ plan, review }: { plan: TravelPlan; review?: PublicReview }) {
  const headingRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => headingRef.current?.focus(), [plan]);
  return (
    <section className="results-view" aria-labelledby="trip-results-heading">
      <div className="results-hero">
        <div>
          <p className="eyebrow text-indigo-200">Your trip is ready</p>
          <h1 id="trip-results-heading" ref={headingRef} tabIndex={-1} className="mt-2 text-3xl font-bold tracking-tight text-white sm:text-4xl">
            {plan.requirements.origin} <ArrowRight className="inline" aria-hidden="true" /> {plan.requirements.destination}
          </h1>
          <div className="mt-5 flex flex-wrap gap-4 text-sm text-indigo-100">
            <span className="hero-detail"><CalendarDays size={16} />{formatDate(plan.requirements.start_date)} – {formatDate(plan.requirements.end_date)}</span>
            <span className="hero-detail"><Users size={16} />{plan.requirements.travelers} traveler{plan.requirements.travelers === 1 ? "" : "s"}</span>
            <span className="hero-detail"><Wallet size={16} />{formatMoney(plan.total_cost, plan.currency)} estimated</span>
          </div>
        </div>
        <span className="demo-badge">Demo travel data</span>
      </div>

      {plan.budget_warning !== null && <div className="budget-warning" role="status"><AlertTriangle aria-hidden="true" size={20} /><div><p className="font-semibold">Budget note</p><p>{plan.budget_warning}</p></div></div>}

      <div className="result-card-grid">
        <article className="result-card">
          <div className="result-card-icon"><Plane aria-hidden="true" size={20} /></div>
          <div className="flex-1"><p className="eyebrow">Flight · Demo data</p><h2 className="mt-1 text-lg font-bold text-slate-950">{plan.flight.airline} {plan.flight.flight_number}</h2><p className="mt-2 text-sm text-slate-500">{plan.flight.origin} → {plan.flight.destination}</p><div className="mt-4 grid grid-cols-2 gap-3 text-sm"><div><p className="text-slate-400">Departure</p><p className="font-medium">{formatDateTime(plan.flight.departure_time)}</p></div><div><p className="text-slate-400">Arrival</p><p className="font-medium">{formatDateTime(plan.flight.arrival_time)}</p></div><div><p className="text-slate-400">Duration</p><p className="font-medium">{formatDuration(plan.flight.duration_minutes)}</p></div><div><p className="text-slate-400">Price</p><p className="font-medium">{formatMoney(plan.flight.price, plan.flight.currency)}</p></div></div></div>
        </article>
        <article className="result-card">
          <div className="result-card-icon"><Building2 aria-hidden="true" size={20} /></div>
          <div className="flex-1"><p className="eyebrow">Hotel · Demo data</p><h2 className="mt-1 text-lg font-bold text-slate-950">{plan.hotel.name}</h2><p className="mt-2 flex items-center gap-1 text-sm text-amber-600"><Star aria-hidden="true" size={15} fill="currentColor" /> {plan.hotel.rating.toFixed(1)} · {plan.hotel.distance_to_center_km} km from center</p><p className="mt-4 text-lg font-bold text-slate-950">{formatMoney(plan.hotel.price_per_night, plan.hotel.currency)} <span className="text-sm font-normal text-slate-400">/ night</span></p><div className="mt-3 flex flex-wrap gap-2">{plan.hotel.amenities.map((amenity) => <span className="preference-chip" key={amenity}>{amenity}</span>)}</div></div>
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

      {review !== undefined && <section className="review-summary"><div><p className="eyebrow">Quality review</p><h2 className="mt-1 text-xl font-bold text-slate-950">Final review summary</h2><p className="mt-2 text-sm leading-6 text-slate-600">{review.critique}</p></div><div className="review-score"><span>{Math.round(review.scores.overall_score)}</span><small>/ 100</small></div></section>}

      <p className="demo-disclosure">
        Travel options in this demo use deterministic sample data and are not live booking inventory. Verify prices, availability, weather, and opening hours independently.
      </p>
    </section>
  );
}
