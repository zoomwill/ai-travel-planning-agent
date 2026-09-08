import type { ReactNode } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const auth = vi.hoisted(() => ({
  isAuthenticated: false, isLoading: false, error: undefined,
  user: { sub: "auth0|unit-user", name: "Test user" },
  loginWithRedirect: vi.fn().mockResolvedValue(undefined),
  logout: vi.fn().mockResolvedValue(undefined),
  getAccessTokenSilently: vi.fn().mockResolvedValue("synthetic-token"),
}));
vi.mock("@auth0/auth0-react", () => ({
  Auth0Provider: ({ children }: { children: ReactNode }) => children,
  useAuth0: () => auth,
}));
vi.mock("../App", () => ({ default: () => <div>Protected workspace</div> }));
import { AuthRoot } from "./AuthRoot";

const configuration = { mode: "auth0" as const, domain: "tenant.example",
  clientId: "spa", audience: "https://api.example", apiBase: "https://api.example" };

beforeEach(() => {
  auth.isAuthenticated = false;
  auth.isLoading = false;
  auth.error = undefined;
  vi.stubGlobal("crypto", { subtle: { digest: () => Promise.resolve(new Uint8Array(32).buffer) } });
});

describe("Auth0 workspace gate", () => {
  it("does not show a protected workspace before login", () => {
    render(<AuthRoot configuration={configuration} />);
    expect(screen.queryByText("Protected workspace")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(auth.loginWithRedirect).toHaveBeenCalledTimes(1);
  });
  it("shows loading without private data", () => {
    auth.isLoading = true;
    render(<AuthRoot configuration={configuration} />);
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.queryByText("Protected workspace")).not.toBeInTheDocument();
  });
  it("unmounts private workspace before logout redirects", async () => {
    auth.isAuthenticated = true;
    render(<AuthRoot configuration={configuration} />);
    await waitFor(() => expect(screen.getByText("Protected workspace")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(screen.queryByText("Protected workspace")).not.toBeInTheDocument();
    expect(auth.logout).toHaveBeenCalledWith({ logoutParams: { returnTo: window.location.origin } });
  });
});
