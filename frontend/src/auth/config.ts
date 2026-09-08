/** Public SPA configuration only; no backend secrets belong here. */
export interface FrontendAuthConfig {
  mode: "demo" | "auth0";
  domain: string;
  clientId: string;
  audience: string;
  apiBase: string;
}

function exactHttpsOrigin(value: string): boolean {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && url.origin === value && !url.username && !url.password;
  } catch { return false; }
}

export function readFrontendConfig(
  env: Record<string, string | boolean | undefined>,
  cloudProduction = false,
): FrontendAuthConfig {
  const mode = env.VITE_AUTH_MODE ?? "demo";
  if (mode !== "demo" && mode !== "auth0") throw new Error("Invalid frontend auth mode.");
  const domain = String(env.VITE_AUTH0_DOMAIN ?? "");
  const clientId = String(env.VITE_AUTH0_CLIENT_ID ?? "");
  const audience = String(env.VITE_AUTH0_AUDIENCE ?? "");
  const apiBase = String(env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");
  if (cloudProduction && mode !== "auth0") throw new Error("Cloud production requires Auth0.");
  if (mode === "auth0" && (
    !exactHttpsOrigin(`https://${domain}`) || !clientId || !audience || audience === clientId
    || (apiBase !== "" && !exactHttpsOrigin(apiBase))
  )) throw new Error("Auth0 requires a valid domain, SPA client ID, API audience and HTTPS API origin.");
  if (cloudProduction && !exactHttpsOrigin(apiBase)) throw new Error("Cloud API must use HTTPS.");
  return { mode, domain, clientId, audience, apiBase };
}
