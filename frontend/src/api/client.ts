import type { z } from "zod";

import { AppError, isAbortError } from "../lib/errors";
import type { AccessTokenProvider } from "../auth/context";
import { readFrontendConfig } from "../auth/config";

const config = readFrontendConfig(import.meta.env);
const API_BASE_URL = config.apiBase;
const DEFAULT_TIMEOUT_MS = 45_000;

interface RequestOptions extends Omit<RequestInit, "body" | "signal"> {
  body?: unknown;
  signal?: AbortSignal | null | undefined;
  timeoutMs?: number;
  retryGet?: boolean;
  getAccessToken?: AccessTokenProvider | undefined;
}

interface SafeErrorBody {
  detail?: unknown;
}

function requestSignal(external: AbortSignal | null | undefined, timeoutMs: number): {
  signal: AbortSignal;
  cleanup: () => void;
} {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort("timeout"), timeoutMs);
  const forwardAbort = (): void => controller.abort(external?.reason);
  external?.addEventListener("abort", forwardAbort, { once: true });
  return {
    signal: controller.signal,
    cleanup: () => {
      window.clearTimeout(timeout);
      external?.removeEventListener("abort", forwardAbort);
    },
  };
}

function userMessageForStatus(status: number, code: string): string {
  if (status === 401) return "Your session has expired. Sign in again.";
  if (status === 403) return "You do not have access to this resource.";
  if (status === 429) return "Daily demo capacity reached. Please try again later.";
  if (status === 409 && code === "stale_draft_fingerprint") {
    return "Your trip details changed. Please review the latest version before confirming.";
  }
  if (status === 503 && code === "conversational_intake_requires_llm") {
    return "AI conversation service is currently unavailable.";
  }
  if (status === 503) return "The planning service is currently unavailable.";
  if (status === 422) return "Some trip details were not accepted. Please review and try again.";
  if (status >= 500) return "The server could not complete this request. Please try again.";
  return "The request could not be completed.";
}

export async function errorFromResponse(response: Response): Promise<AppError> {
  const requestId = response.headers.get("X-Request-ID") ?? undefined;
  let body: SafeErrorBody | undefined;
  try {
    const parsed: unknown = JSON.parse(await response.text());
    if (typeof parsed === "object" && parsed !== null) body = parsed;
  } catch {
    body = undefined;
  }
  const detail = body?.detail;
  const code =
    typeof detail === "object" && detail !== null && "code" in detail
      ? String(detail.code)
      : `http_${response.status}`;
  return new AppError(userMessageForStatus(response.status, code), {
    code,
    requestId,
    status: response.status,
  });
}

async function fetchOnce(path: string, options: RequestOptions): Promise<Response> {
  const { timeoutMs = DEFAULT_TIMEOUT_MS, body, retryGet: _retryGet, getAccessToken, ...requestOptions } = options;
  void _retryGet;
  const { signal, cleanup } = requestSignal(requestOptions.signal, timeoutMs);
  try {
    const protectedPath = path.startsWith("/api/");
    if (protectedPath && config.mode === "auth0" && !getAccessToken) {
      throw new AppError("Your session has expired. Sign in again.", { code: "authentication_required", status: 401 });
    }
    const token = protectedPath && getAccessToken ? await getAccessToken() : undefined;
    if (token !== undefined) {
      requestOptions.signal?.throwIfAborted();
      signal.throwIfAborted();
    }
    return await fetch(`${API_BASE_URL}${path}`, {
      ...requestOptions,
      signal,
      headers: {
        Accept: "application/json",
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
        ...requestOptions.headers,
        ...(token === undefined ? {} : { Authorization: `Bearer ${token}` }),
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
  } catch (error) {
    if (error instanceof AppError) throw error;
    if (isAbortError(error) || requestOptions.signal?.aborted === true) throw error;
    if (signal.aborted) {
      throw new AppError("The request timed out. Please try again.", {
        code: "request_timeout",
        cause: error,
      });
    }
    throw new AppError("Unable to reach the travel planner.", {
      code: "network_error",
      cause: error,
    });
  } finally {
    cleanup();
  }
}

/** Fetch JSON once, with a single retry reserved for safe GET requests. */
export async function requestJson<T>(
  path: string,
  schema: z.ZodType<T>,
  options: RequestOptions = {},
): Promise<T> {
  const method = (options.method ?? "GET").toUpperCase();
  const attempts = method === "GET" && options.retryGet !== false ? 2 : 1;
  let response: Response | undefined;
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    try {
      response = await fetchOnce(path, options);
      break;
    } catch (error) {
      if (attempt + 1 === attempts || isAbortError(error) || (error instanceof AppError && error.status !== undefined)) throw error;
    }
  }
  if (response === undefined) {
    throw new AppError("Unable to reach the travel planner.", { code: "network_error" });
  }
  if (!response.ok) throw await errorFromResponse(response);
  let raw: unknown;
  try {
    raw = JSON.parse(await response.text());
  } catch (error) {
    throw new AppError("The server returned an unreadable response.", {
      code: "response_invalid_json",
      requestId: response.headers.get("X-Request-ID") ?? undefined,
      cause: error,
    });
  }
  const parsed = schema.safeParse(raw);
  if (!parsed.success) {
    throw new AppError("The server returned an unexpected response.", {
      code: "response_schema_invalid",
      requestId: response.headers.get("X-Request-ID") ?? undefined,
      cause: parsed.error,
    });
  }
  return parsed.data;
}

/** Open a streaming POST response without retrying the mutation. */
export async function requestEventStream(
  path: string,
  body: unknown,
  signal: AbortSignal,
  getAccessToken?: AccessTokenProvider,
): Promise<Response> {
  const response = await fetchOnce(path, {
    method: "POST",
    body,
    signal,
    timeoutMs: 10 * 60_000,
    retryGet: false,
    getAccessToken,
    headers: { Accept: "text/event-stream" },
  });
  if (!response.ok) throw await errorFromResponse(response);
  if (!response.headers.get("Content-Type")?.includes("text/event-stream")) {
    throw new AppError("The server did not start a planning stream.", {
      code: "stream_content_type_invalid",
      requestId: response.headers.get("X-Request-ID") ?? undefined,
    });
  }
  if (response.body === null) {
    throw new AppError("The planning stream was empty.", {
      code: "stream_body_missing",
      requestId: response.headers.get("X-Request-ID") ?? undefined,
    });
  }
  return response;
}
