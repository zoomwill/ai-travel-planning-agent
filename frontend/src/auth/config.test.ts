import { describe, expect, it } from "vitest";
import { readFrontendConfig } from "./config";

const valid = { VITE_AUTH_MODE: "auth0", VITE_AUTH0_DOMAIN: "tenant.example",
  VITE_AUTH0_CLIENT_ID: "public-spa", VITE_AUTH0_AUDIENCE: "https://api.example",
  VITE_API_BASE_URL: "https://api.example" };

describe("production SPA configuration", () => {
  it("keeps account-free local defaults", () => expect(readFrontendConfig({}).mode).toBe("demo"));
  it("accepts public SPA config", () => expect(readFrontendConfig(valid, true).mode).toBe("auth0"));
  it.each([
    { VITE_AUTH_MODE: "demo" }, { VITE_AUTH0_DOMAIN: "user:password@tenant.example" },
    { VITE_API_BASE_URL: "http://localhost:8000" }, { VITE_AUTH0_CLIENT_ID: "" },
    { VITE_AUTH0_AUDIENCE: "public-spa" }, { VITE_API_BASE_URL: "" },
  ])("rejects unsafe production configuration", (change) => {
    expect(() => readFrontendConfig({ ...valid, ...change }, true)).toThrow();
  });
});
