import { Check, Circle, CloudSun, Hotel, Landmark, LoaderCircle, Map, Plane, X } from "lucide-react";

import type { SearchKind } from "../../api/types";
import type { PlanningProgress, ProgressStatus } from "../../state/appReducer";

const stages = [
  ["understanding", "Understanding preferences"],
  ["knowledge", "Finding travel knowledge"],
  ["search", "Comparing travel options"],
  ["drafting", "Building your itinerary"],
  ["reviewing", "Reviewing plan quality"],
  ["finalizing", "Finalizing your trip"],
] as const;
const searchLabels: Record<SearchKind, string> = {
  flights: "Flights",
  hotels: "Hotels",
  attractions: "Attractions",
  weather: "Weather",
  route: "Route",
};
const searchIcons = { flights: Plane, hotels: Hotel, attractions: Landmark, weather: CloudSun, route: Map };

function StatusIcon({ status }: { status: ProgressStatus }) {
  if (status === "completed") return <Check className="text-emerald-600" aria-label="Completed" size={16} />;
  if (status === "failed") return <X className="text-rose-600" aria-label="Failed" size={16} />;
  if (status === "running") return <LoaderCircle className="animate-spin text-indigo-600" aria-label="In progress" size={16} />;
  return <Circle className="text-slate-300" aria-label="Pending" size={15} />;
}

/** Translate public workflow events into calm, non-technical progress. */
export function ProgressPanel({ progress, onStop }: { progress: PlanningProgress; onStop?: () => void }) {
  const latestReview = progress.reviews.at(-1);
  return (
    <section className="progress-panel" aria-labelledby="progress-heading">
      <div className="flex items-start justify-between gap-3">
        <div><p className="eyebrow">Agent progress</p><h2 id="progress-heading" className="text-xl font-bold text-slate-950">Planning your trip</h2></div>
        {onStop !== undefined && <button className="button-secondary" type="button" onClick={onStop}>Stop</button>}
      </div>
      <p className="sr-only" aria-live="polite">{progress.latestMessage}</p>
      <ol className="mt-6 space-y-3">
        {stages.map(([key, label]) => (
          <li className="progress-row" key={key}><StatusIcon status={progress.stages[key]} /><span>{label}</span></li>
        ))}
      </ol>

      <div className="search-card">
        <p className="draft-label">Travel searches</p>
        <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
          {(Object.keys(searchLabels) as SearchKind[]).map((kind) => {
            const Icon = searchIcons[kind];
            return <div className="search-row" key={kind}><Icon aria-hidden="true" size={16} /><span className="flex-1">{searchLabels[kind]}</span><StatusIcon status={progress.searches[kind]} /></div>;
          })}
        </div>
      </div>

      {latestReview !== undefined && (
        <div className="review-card">
          <div className="flex items-center justify-between"><p className="font-semibold text-slate-900">Review round {latestReview.reviewRound}</p><span className="status-chip">{latestReview.decision.replace("_", " ")}</span></div>
          <div className="mt-4 space-y-3">
            {Object.entries(latestReview.scores).map(([name, value]) => (
              <div key={name}>
                <div className="mb-1 flex justify-between text-xs text-slate-500"><span>{name.replaceAll("_", " ")}</span><span>{Math.round(value)}</span></div>
                <div className="score-track"><span style={{ width: `${value}%` }} /></div>
              </div>
            ))}
          </div>
          <p className="mt-4 text-sm leading-6 text-slate-600">{latestReview.critique}</p>
          {progress.revisionRound !== null && <p className="mt-3 font-medium text-indigo-700">Improving your itinerary…</p>}
        </div>
      )}

      <details className="developer-details">
        <summary>Developer details</summary>
        <p>Public event types: {progress.publicEvents.join(" → ") || "None yet"}</p>
      </details>
    </section>
  );
}
