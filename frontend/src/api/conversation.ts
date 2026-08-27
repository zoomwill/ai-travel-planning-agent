import {
  conversationMessageRequestSchema,
  conversationResponseSchema,
  healthResponseSchema,
  threadStateResponseSchema,
} from "./schemas";
import type {
  ConversationMessageRequest,
  ConversationResponse,
  ThreadStateResponse,
} from "./types";
import { requestJson } from "./client";

function pathFor(threadId: string): string {
  return `/api/v1/agents/threads/${encodeURIComponent(threadId)}/conversation`;
}

export async function getConversation(
  threadId: string,
  userId: string,
  signal?: AbortSignal,
): Promise<ConversationResponse> {
  return requestJson(
    `${pathFor(threadId)}?user_id=${encodeURIComponent(userId)}`,
    conversationResponseSchema,
    { signal },
  );
}

export async function sendConversationMessage(
  threadId: string,
  request: ConversationMessageRequest,
  signal?: AbortSignal,
): Promise<ConversationResponse> {
  const body = conversationMessageRequestSchema.parse(request);
  return requestJson(`${pathFor(threadId)}/messages`, conversationResponseSchema, {
    method: "POST",
    body,
    signal,
    retryGet: false,
  });
}

export async function resetConversation(
  threadId: string,
  userId: string,
  signal?: AbortSignal,
): Promise<ConversationResponse> {
  return requestJson(`${pathFor(threadId)}/reset`, conversationResponseSchema, {
    method: "POST",
    body: { user_id: userId },
    signal,
    retryGet: false,
  });
}

export async function checkHealth(signal?: AbortSignal): Promise<boolean> {
  await requestJson("/health", healthResponseSchema, { signal, timeoutMs: 5_000 });
  return true;
}

export async function getThreadState(
  threadId: string,
  signal?: AbortSignal,
): Promise<ThreadStateResponse> {
  return requestJson(
    `/api/v1/agents/threads/${encodeURIComponent(threadId)}/state`,
    threadStateResponseSchema,
    { signal },
  );
}

export const conversationStreamPath = (threadId: string): string =>
  `${pathFor(threadId)}/confirm/stream`;
