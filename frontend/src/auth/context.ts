import { createContext, useContext } from "react";

export type AccessTokenProvider = () => Promise<string>;

export interface AuthSession {
  getAccessToken: AccessTokenProvider;
  storageScope: string;
}

export const AuthSessionContext = createContext<AuthSession | undefined>(undefined);

/** SDK-managed token retrieval, injected per React tree rather than global mutable state. */
export function useAuthSession(): AuthSession | undefined {
  return useContext(AuthSessionContext);
}
