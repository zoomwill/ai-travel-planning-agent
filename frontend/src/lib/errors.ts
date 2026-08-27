/** A safe browser-facing error with optional backend diagnostic metadata. */
export class AppError extends Error {
  readonly code: string;
  readonly requestId?: string;
  readonly status?: number;

  constructor(
    message: string,
    options: {
      code: string;
      requestId?: string | undefined;
      status?: number | undefined;
      cause?: unknown;
    },
  ) {
    super(message, { cause: options.cause });
    this.name = "AppError";
    this.code = options.code;
    if (options.requestId !== undefined) this.requestId = options.requestId;
    if (options.status !== undefined) this.status = options.status;
  }
}

/** Return true only for a deliberate browser fetch cancellation. */
export function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

/** Convert an unknown failure into bounded UI text without leaking raw internals. */
export function toAppError(error: unknown): AppError {
  if (error instanceof AppError) return error;
  return new AppError("Something went wrong. Please try again.", {
    code: "unexpected_error",
    cause: error,
  });
}
