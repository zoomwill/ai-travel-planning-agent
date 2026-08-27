import { AlertCircle, RotateCcw, X } from "lucide-react";

import type { AppError } from "../../lib/errors";

interface ErrorBannerProps {
  error: AppError;
  onDismiss: () => void;
  onRetry?: () => void;
  retryLabel?: string;
}

/** Present bounded failure text and an optional explicit retry action. */
export function ErrorBanner({ error, onDismiss, onRetry, retryLabel = "Try again" }: ErrorBannerProps) {
  return (
    <div className="error-banner" role="alert">
      <AlertCircle aria-hidden="true" size={20} />
      <div className="min-w-0 flex-1">
        <p className="font-semibold text-slate-950">We couldn&apos;t complete that</p>
        <p className="mt-1 text-sm text-slate-600">{error.message}</p>
        {error.requestId !== undefined && (
          <p className="mt-2 text-xs text-slate-500">Reference: {error.requestId}</p>
        )}
        {onRetry !== undefined && (
          <button className="button-secondary mt-3" type="button" onClick={onRetry}>
            <RotateCcw aria-hidden="true" size={15} />
            {retryLabel}
          </button>
        )}
      </div>
      <button className="icon-button" type="button" aria-label="Dismiss error" onClick={onDismiss}>
        <X aria-hidden="true" size={18} />
      </button>
    </div>
  );
}
