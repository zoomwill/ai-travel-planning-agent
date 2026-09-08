import { useCallback, useEffect, useReducer, useRef } from "react";

import {
  getConversation,
  getThreadState,
  resetConversation,
  sendConversationMessage,
} from "../api/conversation";
import { AppError, isAbortError, toAppError } from "../lib/errors";
import { useAuthSession } from "../auth/context";
import { appReducer, initialAppState, type AppAction, type AppState } from "../state/appReducer";

/** Restore and mutate only the current backend-owned conversation. */
export function useConversation(
  userId: string,
  threadId: string,
  updateTitle: (title: string) => void,
): {
  state: AppState;
  dispatch: React.Dispatch<AppAction>;
  reload: () => Promise<void>;
  send: (message: string) => Promise<void>;
  reset: () => Promise<void>;
} {
  const [state, dispatch] = useReducer(appReducer, initialAppState);
  const getAccessToken = useAuthSession()?.getAccessToken;
  const activeRequest = useRef<AbortController | null>(null);

  const reload = useCallback(async () => {
    activeRequest.current?.abort();
    const controller = new AbortController();
    activeRequest.current = controller;
    dispatch({ type: "LOAD_START" });
    try {
      const conversation = await getConversation(threadId, userId, controller.signal, getAccessToken);
      dispatch({ type: "CONVERSATION_RECEIVED", conversation });
      if (conversation.draft.destination !== null) updateTitle(conversation.draft.destination);
      if (conversation.plan_available) {
        const snapshot = await getThreadState(threadId, controller.signal, getAccessToken);
        if (snapshot.travel_plan !== null) dispatch({ type: "PLAN_RESTORED", plan: snapshot.travel_plan });
      }
    } catch (error) {
      if (isAbortError(error)) return;
      const appError = toAppError(error);
      if (appError instanceof AppError && appError.status === 404) dispatch({ type: "LOAD_EMPTY" });
      else dispatch({ type: "SHOW_ERROR", error: appError });
    } finally {
      if (activeRequest.current === controller) activeRequest.current = null;
    }
  }, [threadId, updateTitle, userId, getAccessToken]);

  useEffect(() => {
    void reload();
    return () => activeRequest.current?.abort();
  }, [reload]);

  const send = useCallback(
    async (message: string) => {
      const trimmed = message.trim();
      if (trimmed.length === 0 || trimmed.length > 4000) return;
      const controller = new AbortController();
      activeRequest.current = controller;
      dispatch({ type: "SEND_START", message: trimmed });
      try {
        const conversation = await sendConversationMessage(
          threadId,
          { user_id: userId, message: trimmed, start_new_trip: false },
          controller.signal,
          getAccessToken,
        );
        dispatch({ type: "CONVERSATION_RECEIVED", conversation });
        if (conversation.draft.destination !== null) updateTitle(conversation.draft.destination);
      } catch (error) {
        if (!isAbortError(error)) {
          dispatch({ type: "SEND_FAILED", message: trimmed, error: toAppError(error) });
        }
      } finally {
        if (activeRequest.current === controller) activeRequest.current = null;
      }
    },
    [threadId, updateTitle, userId, getAccessToken],
  );

  const reset = useCallback(async () => {
    const controller = new AbortController();
    activeRequest.current = controller;
    try {
      if (state.conversation === null) {
        dispatch({ type: "CLEAR_TRIP" });
        return;
      }
      const conversation = await resetConversation(threadId, userId, controller.signal, getAccessToken);
      dispatch({ type: "CLEAR_TRIP" });
      dispatch({ type: "CONVERSATION_RECEIVED", conversation });
      updateTitle("New trip");
    } catch (error) {
      if (!isAbortError(error)) dispatch({ type: "SHOW_ERROR", error: toAppError(error) });
    } finally {
      if (activeRequest.current === controller) activeRequest.current = null;
    }
  }, [state.conversation, threadId, updateTitle, userId, getAccessToken]);

  return { state, dispatch, reload, send, reset };
}
