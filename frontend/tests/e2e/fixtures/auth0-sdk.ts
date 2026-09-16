import { useSyncExternalStore, type ReactNode } from "react";

// Browser-only fixture loaded by Playwright interception, never by application imports.
// Let Vite resolve React: optimized dependency URLs/hashes are not a public contract.
type Account = "a" | "b" | null;
let account: Account = "a";
const listeners = new Set<() => void>();

function snapshot() {
  return {
    isAuthenticated: account !== null,
    isLoading: false,
    error: null,
    user: account ? { sub: `auth0|fixture-${account}`, name: "Local test account" } : undefined,
    getAccessTokenSilently: () => Promise.resolve(`fixture:${account}`),
    loginWithRedirect: () => { changeAccount("a"); return Promise.resolve(); },
    logout: () => { changeAccount(null); return Promise.resolve(); },
  };
}

let state = snapshot();

function changeAccount(next: Account): void {
  account = next;
  state = snapshot();
  for (const notify of listeners) notify();
}

window.addEventListener("p19-account", (event) => {
  const next: unknown = (event as CustomEvent<unknown>).detail;
  if (next === "a" || next === "b" || next === null) changeAccount(next);
});

function subscribe(notify: () => void): () => void {
  listeners.add(notify);
  return () => { listeners.delete(notify); };
}

/** Keep the actual AuthRoot wrapper without creating a real Auth0 client. */
export function Auth0Provider({ children }: { children: ReactNode }): ReactNode {
  return children;
}

/** Expose stable fake SDK snapshots for the browser's A/B account-switch test. */
export function useAuth0(): ReturnType<typeof snapshot> {
  return useSyncExternalStore(subscribe, () => state);
}
