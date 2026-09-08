import { CircleHelp, Menu, MessageCircle, PanelRight, Sparkles, Wifi, WifiOff } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { checkHealth } from "./api/conversation";
import { ChatPanel } from "./components/chat/ChatPanel";
import { ErrorBanner } from "./components/common/ErrorBanner";
import { ItineraryView } from "./components/itinerary/ItineraryView";
import { Sidebar } from "./components/layout/Sidebar";
import { ProgressPanel } from "./components/progress/ProgressPanel";
import { TripDraftPanel } from "./components/trip/TripDraftPanel";
import { useConversation } from "./hooks/useConversation";
import { useLocalIdentity } from "./hooks/useLocalIdentity";
import { usePlanningStream } from "./hooks/usePlanningStream";
import { useAuthSession } from "./auth/context";

type BackendStatus = "checking" | "connected" | "unavailable";

/** Assemble the P16 browser experience around existing P15/P12 endpoints. */
export default function App() {
  const authSession = useAuthSession();
  const identity = useLocalIdentity();
  const { state, dispatch, reload, send, reset } = useConversation(
    identity.userId,
    identity.threadId,
    identity.updateTitle,
  );
  const planning = usePlanningStream(identity.userId, identity.threadId, dispatch);
  const [backendStatus, setBackendStatus] = useState<BackendStatus>("checking");
  const [showResults, setShowResults] = useState(true);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false);

  const refreshHealth = useCallback(async () => {
    setBackendStatus("checking");
    try {
      await checkHealth();
      setBackendStatus("connected");
    } catch {
      setBackendStatus("unavailable");
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void checkHealth(controller.signal).then(
      () => setBackendStatus("connected"),
      () => {
        if (!controller.signal.aborted) setBackendStatus("unavailable");
      },
    );
    return () => controller.abort();
  }, []);

  const startNewTrip = async (): Promise<void> => {
    const hasDraft = (state.conversation?.messages.length ?? 0) > 0 && state.phase !== "planned";
    if (hasDraft && !window.confirm("Start a new trip? Your current draft is saved.")) return;
    await planning.stopPlanning();
    dispatch({ type: "CLEAR_TRIP" });
    identity.newTrip();
    setShowResults(false);
    setSidebarOpen(false);
  };

  const resetCurrent = async (): Promise<void> => {
    if (!window.confirm("Reset this trip draft? Your user identity and remembered preferences stay unchanged.")) return;
    await planning.stopPlanning();
    await reset();
    setShowResults(false);
  };

  const selectThread = async (threadId: string): Promise<void> => {
    if (threadId === identity.threadId) return;
    await planning.stopPlanning();
    dispatch({ type: "CLEAR_TRIP" });
    identity.selectThread(threadId);
    setShowResults(true);
    setSidebarOpen(false);
  };

  const retryError = state.failedMessage !== null
    ? () => void send(state.failedMessage!)
    : state.conversation?.can_confirm === true
      ? () => void planning.startPlanning(state.conversation!, false)
      : () => void reload();

  return (
    <div className="app-shell">
      <div className={`sidebar-overlay ${sidebarOpen ? "sidebar-overlay-open" : ""}`} onClick={() => setSidebarOpen(false)} aria-hidden="true" />
      <div className={`sidebar-wrap ${sidebarOpen ? "sidebar-wrap-open" : ""}`}>
        <Sidebar currentThreadId={identity.threadId} recentThreads={identity.recentThreads} onNewTrip={() => void startNewTrip()} onReset={() => void resetCurrent()} onSelectThread={(threadId) => void selectThread(threadId)} />
      </div>

      <div className="workspace">
        <header className="app-header">
          <div className="flex min-w-0 items-center gap-3">
            <button className="icon-button lg:hidden" type="button" aria-label="Open trip navigation" onClick={() => setSidebarOpen(true)}><Menu aria-hidden="true" size={20} /></button>
            <div className="min-w-0"><p className="truncate text-lg font-bold tracking-tight text-slate-950">AI Travel Planner</p><p className="hidden truncate text-xs text-slate-500 sm:block">Plan smarter with a multi-agent travel assistant.</p></div>
          </div>
          <button className={`backend-status backend-${backendStatus}`} type="button" onClick={() => void refreshHealth()} aria-label="Check backend connection">
            {backendStatus === "connected" ? <Wifi aria-hidden="true" size={15} /> : <WifiOff aria-hidden="true" size={15} />}
            {backendStatus === "checking" ? "Checking…" : backendStatus === "connected" ? "Connected" : "Unavailable"}
          </button>
        </header>

        <main className="main-grid">
          <div className="center-column">
            {state.error !== null && <ErrorBanner error={state.error} onDismiss={() => dispatch({ type: "CLEAR_ERROR" })} onRetry={retryError} retryLabel={state.error.status === 409 ? "Reload latest draft" : state.phase === "error" && state.conversation?.can_confirm === true ? "Retry planning" : "Try again"} />}

            {state.finalPlan !== null && (
              <div className="view-switcher" role="group" aria-label="Main view">
                <button type="button" className={showResults ? "active" : ""} onClick={() => setShowResults(true)}><Sparkles size={15} /> Trip results</button>
                <button type="button" className={!showResults ? "active" : ""} onClick={() => setShowResults(false)}><MessageCircle size={15} /> Conversation</button>
              </div>
            )}

            {state.finalPlan !== null && showResults ? (
              <ItineraryView
                plan={state.finalPlan}
                {...(state.progress.reviews.at(-1) === undefined
                  ? {}
                  : { review: state.progress.reviews.at(-1)! })}
              />
            ) : (
              <ChatPanel conversation={state.conversation} phase={state.phase} optimisticMessage={state.optimisticMessage} failedMessage={state.failedMessage} onSend={send} />
            )}
          </div>

          <aside className="detail-column" aria-label="Trip details and planning progress">
            <div className={`mobile-detail ${detailsOpen ? "mobile-detail-open" : ""}`}>
              <button
                className="mobile-detail-toggle"
                type="button"
                aria-expanded={detailsOpen}
                onClick={() => setDetailsOpen((open) => !open)}
              >
                <PanelRight aria-hidden="true" size={17} /> Trip details
              </button>
              <div className="detail-content">
                {state.phase === "planning" ? <ProgressPanel progress={state.progress} onStop={() => void planning.stopPlanning()} /> : <TripDraftPanel key={state.conversation?.draft_fingerprint ?? identity.threadId} conversation={state.conversation} planning={false} onConfirm={(remember) => {
                  if (state.conversation !== null) {
                    setShowResults(true);
                    setDetailsOpen(true);
                    void planning.startPlanning(state.conversation, remember).then(() => setDetailsOpen(false));
                  }
                }} />}
                {state.phase === "planned" && state.progress.publicEvents.length > 0 && <div className="mt-5"><ProgressPanel progress={state.progress} /></div>}
              </div>
            </div>
          </aside>
        </main>

        <footer className="app-footer"><CircleHelp aria-hidden="true" size={14} /> {authSession ? "Authenticated demo — test/sandbox travel data, no booking." : "Local demonstration — no authentication or live booking inventory."}</footer>
      </div>
    </div>
  );
}
