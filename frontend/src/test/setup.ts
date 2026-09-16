import "@testing-library/jest-dom/vitest";

// Ordinary unit tests must not inherit the developer's real Auth0 environment.
vi.stubEnv("VITE_AUTH_MODE", "demo");
vi.stubEnv("VITE_API_BASE_URL", "");

afterEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

Object.defineProperty(HTMLElement.prototype, "scrollTo", {
  configurable: true,
  value: vi.fn(),
});
