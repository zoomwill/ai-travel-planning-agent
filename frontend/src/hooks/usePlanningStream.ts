import { useCallback, useEffect, useRef } from "react";

import { getConversation } from "../api/conversation";
import { streamConfirmedConversation } from "../api/streaming";
import type { ConversationResponse } from "../api/types";
import { AppError, isAbortError, toAppError } from "../lib/errors";
import type { AppAction } from "../state/appReducer";
import { useAuthSession } from "../auth/context";

/** Own exactly one active confirmation stream and its cancellation cleanup. */
export function usePlanningStream(
  userId: string,
  threadId: string,
  dispatch: React.Dispatch<AppAction>,
): {
  startPlanning: (conversation: ConversationResponse, remember: boolean) => Promise<void>;
  stopPlanning: () => Promise<void>;
} {
  const controllerRef = useRef<AbortController | null>(null);
  const getAccessToken = useAuthSession()?.getAccessToken;
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const activePromiseRef = useRef<Promise<void> | null>(null);

  const resync = useCallback(async () => {
    if (!mounted.current) return;
    try {
      const conversation = await getConversation(threadId, userId, undefined, getAccessToken);
      dispatch({ type: "CONVERSATION_RECEIVED", conversation });
    } catch {
      // The original bounded error remains the useful user-facing result.
    }
  }, [dispatch, threadId, userId, getAccessToken]);

  const startPlanning = useCallback(
    (conversation: ConversationResponse, remember: boolean): Promise<void> => {
      if (controllerRef.current !== null) return activePromiseRef.current ?? Promise.resolve();
      const controller = new AbortController();
      controllerRef.current = controller;
      const activePromise = (async () => {
        dispatch({ type: "PLAN_START" });
        let terminalError: AppError | null = null;
        try {
          await streamConfirmedConversation(
            threadId,
            {
              user_id: userId,
              draft_fingerprint: conversation.draft_fingerprint,
              remember_preferences: remember ? conversation.draft.preferences : [],
            },
            controller.signal,
            (event) => {
              dispatch({ type: "STREAM_EVENT", event });
              if (event.event_type === "error") {
                terminalError = new AppError(event.data.safe_message, {
                  code: event.data.error_code,
                });
              }
            },
            getAccessToken,
          );
          await resync();
          if (terminalError !== null) dispatch({ type: "SHOW_ERROR", error: terminalError });
        } catch (error) {
          if (isAbortError(error) || controller.signal.aborted) {
            await resync();
            dispatch({ type: "STOPPED" });
          } else {
            const appError = toAppError(error);
            if (appError.status === 409) await resync();
            dispatch({ type: "SHOW_ERROR", error: appError });
          }
        } finally {
          if (controllerRef.current === controller) {
            controllerRef.current = null;
            activePromiseRef.current = null;
          }
        }
      })();
      activePromiseRef.current = activePromise;
      return activePromise;
    },
    [dispatch, resync, threadId, userId, getAccessToken],
  );

  const stopPlanning = useCallback(async () => {
    const activePromise = activePromiseRef.current;
    controllerRef.current?.abort();
    if (activePromise !== null) await activePromise;
  }, []);
  useEffect(
    () => () => {
      void stopPlanning();
    },
    [stopPlanning, threadId],
  );

  return {
    startPlanning,
    stopPlanning,
  };
}
