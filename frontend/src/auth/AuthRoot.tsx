import { Auth0Provider, useAuth0 } from "@auth0/auth0-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import App from "../App";
import { AppError } from "../lib/errors";
import { clearSessionPointers } from "../lib/storage";
import { readFrontendConfig, type FrontendAuthConfig } from "./config";
import { AuthSessionContext } from "./context";

const config = readFrontendConfig(import.meta.env);

/** Gate the workspace; no authentication error/claim is rendered as raw provider text. */
function AuthenticatedWorkspace({ config }: { config: FrontendAuthConfig }) {
  const auth = useAuth0();
  const { getAccessTokenSilently } = auth;
  const [signingOut, setSigningOut] = useState(false);
  const [identity, setIdentity] = useState<{ subject: string; scope: string } | null>(null);
  const subject = auth.user?.sub;
  useEffect(() => {
    let active = true;
    if (auth.isAuthenticated && subject) {
      void crypto.subtle.digest("SHA-256", new TextEncoder().encode(`${config.domain}\0${subject}`))
        .then((bytes) => {
          if (active) setIdentity({ subject, scope: Array.from(new Uint8Array(bytes), (byte) => byte.toString(16).padStart(2, "0")).join("") });
        });
    }
    return () => { active = false; };
  }, [auth.isAuthenticated, subject, config.domain]);
  const getAccessToken = useCallback(async (): Promise<string> => {
    try {
      return await getAccessTokenSilently({
        authorizationParams: { audience: config.audience },
        timeoutInSeconds: 10,
      });
    } catch {
      throw new AppError("Your session has expired. Sign in again.", { code: "authentication_required", status: 401 });
    }
  }, [getAccessTokenSilently, config.audience]);
  const session = useMemo(() => identity === null ? undefined : {
    getAccessToken, storageScope: identity.scope,
  }, [getAccessToken, identity]);

  if (auth.isLoading || signingOut) return <main className="p-10" role="status">Securing your session…</main>;
  if (auth.error || !auth.isAuthenticated) return (
    <main className="mx-auto max-w-2xl p-10">
      <h1 className="text-3xl font-bold">AI Travel Planning Agent</h1>
      <p className="my-6">Create a personal itinerary with clearly labeled test, sandbox and demo travel data. No booking or payment.</p>
      {auth.error && <p role="alert">Sign-in could not be completed. Please try again.</p>}
      <button className="primary-button" onClick={() => void auth.loginWithRedirect().catch(() => undefined)}>Sign in</button>
    </main>
  );
  if (!session || identity?.subject !== subject) return <main role="status">Preparing your workspace…</main>;

  const signOut = (): void => {
    setSigningOut(true);
    clearSessionPointers(session.storageScope);
    void auth.logout({ logoutParams: { returnTo: window.location.origin } }).catch(() => {
      setSigningOut(false);
    });
  };
  return (
    <AuthSessionContext.Provider value={session}>
      <div className="flex justify-end gap-4 bg-slate-950 px-6 py-2 text-white">
        <span>{auth.user?.name ?? "Signed in"}</span>
        <button type="button" onClick={() => void auth.loginWithRedirect().catch(() => undefined)}>Sign in again</button>
        <button type="button" onClick={signOut}>Sign out</button>
      </div>
      <App key={session.storageScope} />
    </AuthSessionContext.Provider>
  );
}

/** Auth0 owns Authorization Code + PKCE and memory token caching; demo stays account-free. */
export function AuthRoot({ configuration = config }: { configuration?: FrontendAuthConfig }) {
  if (configuration.mode === "demo") return <App />;
  return (
    <Auth0Provider domain={configuration.domain} clientId={configuration.clientId} cacheLocation="memory"
      authorizationParams={{ redirect_uri: window.location.origin, audience: configuration.audience }}>
      <AuthenticatedWorkspace config={configuration} />
    </Auth0Provider>
  );
}
