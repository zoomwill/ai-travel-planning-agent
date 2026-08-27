import { confirmRequestSchema, knownStreamEventTypes, streamBusinessEventSchema } from "./schemas";
import type { ConfirmRequest, StreamBusinessEvent } from "./types";
import { AppError } from "../lib/errors";
import { SseParser } from "../lib/sse";
import { requestEventStream } from "./client";
import { conversationStreamPath } from "./conversation";

function parseBusinessEvent(eventName: string, data: string): StreamBusinessEvent | null {
  if (!knownStreamEventTypes.has(eventName)) return null;
  let value: unknown;
  try {
    value = JSON.parse(data);
  } catch (error) {
    throw new AppError("The planning stream sent unreadable progress data.", {
      code: "stream_invalid_json",
      cause: error,
    });
  }
  const parsed = streamBusinessEventSchema.safeParse(value);
  if (!parsed.success || parsed.data.event_type !== eventName) {
    throw new AppError("The planning stream sent unexpected progress data.", {
      code: "stream_schema_invalid",
      cause: parsed.success ? undefined : parsed.error,
    });
  }
  if (parsed.data.event_id !== parsed.data.sequence) {
    throw new AppError("The planning stream sequence was invalid.", {
      code: "stream_sequence_invalid",
    });
  }
  return parsed.data;
}

/** Consume the POST SSE response through EOF so backend terminal cleanup can finish. */
export async function streamConfirmedConversation(
  threadId: string,
  request: ConfirmRequest,
  signal: AbortSignal,
  onEvent: (event: StreamBusinessEvent) => void,
): Promise<void> {
  const body = confirmRequestSchema.parse(request);
  const response = await requestEventStream(conversationStreamPath(threadId), body, signal);
  const reader = response.body!.getReader();
  let previousSequence = 0;
  let terminal: "plan_completed" | "error" | null = null;
  let parserError: unknown;
  const parser = new SseParser((raw) => {
    if (parserError !== undefined) return;
    try {
      const event = parseBusinessEvent(raw.event, raw.data);
      if (event === null) return;
      if (terminal !== null) {
        throw new AppError("The planning stream continued after its final event.", {
          code: "stream_after_terminal",
        });
      }
      if (event.sequence !== previousSequence + 1) {
        throw new AppError("The planning stream sequence was not continuous.", {
          code: "stream_sequence_invalid",
        });
      }
      previousSequence = event.sequence;
      onEvent(event);
      if (event.event_type === "plan_completed" || event.event_type === "error") {
        terminal = event.event_type;
      }
    } catch (error) {
      parserError = error;
    }
  });

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      parser.push(value);
      if (parserError !== undefined) {
        throw parserError instanceof Error
          ? parserError
          : new AppError("The planning stream could not be parsed.", { code: "stream_parse_failed" });
      }
    }
    parser.finish();
    if (parserError !== undefined) {
      throw parserError instanceof Error
        ? parserError
        : new AppError("The planning stream could not be parsed.", { code: "stream_parse_failed" });
    }
    if (terminal === null) {
      throw new AppError("The planning stream disconnected before it finished.", {
        code: "stream_disconnected",
      });
    }
  } catch (error) {
    try {
      await reader.cancel();
    } catch {
      // The original bounded stream error is more useful than cancel cleanup failure.
    }
    throw error;
  } finally {
    reader.releaseLock();
  }
}

export { parseBusinessEvent };
