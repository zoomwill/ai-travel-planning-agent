import { Compass, History, Plus, RotateCcw } from "lucide-react";

import type { RecentThread } from "../../lib/storage";

interface SidebarProps {
  currentThreadId: string;
  recentThreads: RecentThread[];
  onNewTrip: () => void;
  onReset: () => void;
  onSelectThread: (threadId: string) => void;
}

/** Local navigation stores thread pointers only; the backend owns conversation content. */
export function Sidebar({
  currentThreadId,
  recentThreads,
  onNewTrip,
  onReset,
  onSelectThread,
}: SidebarProps) {
  return (
    <aside className="sidebar" aria-label="Trip navigation">
      <div className="flex items-center gap-3 px-2">
        <span className="brand-mark"><Compass aria-hidden="true" size={22} /></span>
        <div>
          <p className="font-bold tracking-tight text-slate-950">Travel Planner</p>
          <p className="text-xs text-slate-500">Local workspace</p>
        </div>
      </div>

      <button className="button-primary mt-7 w-full" type="button" onClick={onNewTrip}>
        <Plus aria-hidden="true" size={18} />
        New Trip
      </button>

      <div className="mt-8 min-h-0 flex-1">
        <div className="mb-3 flex items-center gap-2 px-2 text-xs font-bold uppercase tracking-widest text-slate-400">
          <History aria-hidden="true" size={14} />
          Recent trips
        </div>
        <nav className="space-y-1" aria-label="Recent trips">
          {recentThreads.map((thread) => (
            <button
              className={`recent-trip ${thread.threadId === currentThreadId ? "recent-trip-active" : ""}`}
              type="button"
              key={thread.threadId}
              aria-current={thread.threadId === currentThreadId ? "page" : undefined}
              onClick={() => onSelectThread(thread.threadId)}
            >
              <span className="truncate font-medium">{thread.title}</span>
              <span className="mt-0.5 block text-xs text-slate-400">
                {new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(
                  new Date(thread.createdAt),
                )}
              </span>
            </button>
          ))}
        </nav>
      </div>

      <button className="button-ghost mt-5 w-full" type="button" onClick={onReset}>
        <RotateCcw aria-hidden="true" size={16} />
        Reset current trip
      </button>
      <p className="mt-4 px-2 text-xs leading-5 text-slate-400">
        Demo identity only — this is not authentication.
      </p>
    </aside>
  );
}
