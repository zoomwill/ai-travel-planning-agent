import { CalendarDays, Check, Circle, MapPin, Sparkles, Users, Wallet } from "lucide-react";
import { useState } from "react";

import type { ConversationResponse } from "../../api/types";
import { formatDate, formatMoney } from "../../lib/formatters";

const labels: Record<string, string> = {
  origin: "Origin",
  destination: "Destination",
  start_date: "Departure date",
  end_date: "Return date",
  duration_days: "Duration",
  budget: "Budget",
  currency: "Currency",
  travelers: "Travelers",
  preferences: "Preferences",
};

interface TripDraftPanelProps {
  conversation: ConversationResponse | null;
  planning: boolean;
  onConfirm: (rememberPreferences: boolean) => void;
}

/** Show backend-extracted fields and require an explicit confirmation click. */
export function TripDraftPanel({ conversation, planning, onConfirm }: TripDraftPanelProps) {
  const [remember, setRemember] = useState(false);
  const draft = conversation?.draft;
  const missing = new Set(conversation?.missing_fields ?? []);
  const invalid = conversation?.invalid_fields ?? [];

  return (
    <section className="trip-draft" aria-labelledby="draft-heading">
      <div className="panel-heading px-0 pt-0">
        <div>
          <p className="eyebrow">Trip draft</p>
          <h2 id="draft-heading" className="text-xl font-bold text-slate-950">Your details</h2>
        </div>
        <span className="draft-count">
          {conversation === null ? 0 : 9 - conversation.missing_fields.length}/9
        </span>
      </div>

      <div className="draft-route">
        <span>{draft?.origin ?? "Not set"}</span>
        <span className="route-line" aria-hidden="true" />
        <MapPin aria-hidden="true" size={16} />
        <span>{draft?.destination ?? "Not set"}</span>
      </div>

      <dl className="draft-grid">
        <div><dt><CalendarDays size={15} /> Dates</dt><dd>{draft === undefined ? "Not set" : `${formatDate(draft.start_date)} — ${formatDate(draft.end_date)}`}</dd></div>
        <div><dt><Sparkles size={15} /> Duration</dt><dd>{draft?.duration_days === null || draft?.duration_days === undefined ? "Not set" : `${draft.duration_days} days`}</dd></div>
        <div><dt><Users size={15} /> Travelers</dt><dd>{draft?.travelers ?? "Not set"}</dd></div>
        <div><dt><Wallet size={15} /> Budget</dt><dd>{draft === undefined ? "Not set" : formatMoney(draft.budget, draft.currency)}</dd></div>
      </dl>

      <div className="mt-5">
        <p className="draft-label">Preferences</p>
        <div className="mt-2 flex flex-wrap gap-2">
          {draft !== undefined && draft.preferences.length > 0 ? draft.preferences.map((item) => (
            <span className="preference-chip" key={item}>{item}</span>
          )) : <span className="text-sm text-slate-400">Not set</span>}
        </div>
      </div>

      <div className="mt-6 border-t border-slate-100 pt-5">
        <p className="draft-label">Still needed</p>
        <div className="mt-3 grid gap-2">
          {conversation === null || conversation.missing_fields.length > 0 ? (
            Object.entries(labels).map(([key, label]) => {
              const isMissing = conversation === null || missing.has(key as never);
              return (
                <span className={`requirement-row ${isMissing ? "text-slate-500" : "text-emerald-700"}`} key={key}>
                  {isMissing ? <Circle aria-hidden="true" size={14} /> : <Check aria-hidden="true" size={15} />}
                  {label}
                </span>
              );
            })
          ) : (
            <span className="requirement-row text-emerald-700"><Check aria-hidden="true" size={15} /> All required details are ready</span>
          )}
        </div>
      </div>

      {invalid.length > 0 && (
        <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900" role="status">
          <p className="font-semibold">Needs correction</p>
          <p className="mt-1">{invalid.map((field) => labels[field]).join(", ")}</p>
        </div>
      )}

      {conversation?.can_confirm === true && (
        <div className="confirm-card">
          <p className="eyebrow text-indigo-600">Ready to plan</p>
          <h3 className="mt-1 text-lg font-bold text-slate-950">Review, then build your trip</h3>
          <p className="mt-2 text-sm leading-6 text-slate-600">
            Planning starts only after you confirm this exact draft.
          </p>
          {draft !== undefined && draft.preferences.length > 0 && (
            <label className="remember-row">
              <input type="checkbox" checked={remember} onChange={(event) => setRemember(event.target.checked)} />
              <span>Remember selected preferences for future trips</span>
            </label>
          )}
          <button className="button-primary mt-4 w-full" type="button" disabled={planning} onClick={() => onConfirm(remember)}>
            <Sparkles aria-hidden="true" size={17} />
            Confirm &amp; Build My Trip
          </button>
          <button className="button-ghost mt-2 w-full" type="button" onClick={() => document.querySelector<HTMLTextAreaElement>("#trip-message")?.focus()}>
            Keep editing
          </button>
        </div>
      )}
    </section>
  );
}
