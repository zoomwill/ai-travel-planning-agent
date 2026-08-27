import { describe, expect, it } from "vitest";

import { parseBusinessEvent } from "../api/streaming";
import { AppError, isAbortError } from "./errors";
import { SseParser, type RawSseEvent } from "./sse";
import { planFixture, streamEvent } from "../test/fixtures";

const encoder = new TextEncoder();

function parseChunks(chunks: Uint8Array[], finish = true): RawSseEvent[] {
  const events: RawSseEvent[] = [];
  const parser = new SseParser((event) => events.push(event));
  chunks.forEach((chunk) => parser.push(chunk));
  if (finish) parser.finish();
  return events;
}

describe("SseParser", () => {
  it("parses one complete event", () => {
    expect(parseChunks([encoder.encode("event: run_started\ndata: {\"ok\":true}\n\n")])).toEqual([
      { event: "run_started", data: '{"ok":true}' },
    ]);
  });

  it("parses two events", () => {
    expect(parseChunks([encoder.encode("data: one\n\ndata: two\n\n")]).map((item) => item.data)).toEqual(["one", "two"]);
  });

  it("handles arbitrary chunk splits", () => {
    expect(parseChunks([encoder.encode("event: se"), encoder.encode("arch_started\nda"), encoder.encode("ta: {}\n\n")])[0]?.event).toBe("search_started");
  });

  it("handles byte-by-byte splits", () => {
    const bytes = encoder.encode("event: message\ndata: tiny\n\n");
    expect(parseChunks([...bytes].map((byte) => Uint8Array.of(byte)))[0]?.data).toBe("tiny");
  });

  it("keeps split Chinese UTF-8 intact", () => {
    const bytes = encoder.encode("data: 东京摄影\n\n");
    const chunks = [...bytes].map((byte) => Uint8Array.of(byte));
    expect(parseChunks(chunks)[0]?.data).toBe("东京摄影");
  });

  it.each(["\n", "\r\n"])("supports %j line endings", (ending) => {
    expect(parseChunks([encoder.encode(`event: note${ending}data: yes${ending}${ending}`)])[0]).toEqual({ event: "note", data: "yes" });
  });

  it("handles CRLF split exactly between carriage return and line feed", () => {
    const chunks = [encoder.encode("event: note\r"), encoder.encode("\ndata: safe\r"), encoder.encode("\n\r"), encoder.encode("\n")];
    expect(parseChunks(chunks)).toEqual([{ event: "note", data: "safe" }]);
  });

  it("joins multiple data lines", () => {
    expect(parseChunks([encoder.encode("data: first\ndata: second\n\n")])[0]?.data).toBe("first\nsecond");
  });

  it("ignores heartbeat and blank comments", () => {
    expect(parseChunks([encoder.encode(": ping\n\n:\n\n")])).toEqual([]);
  });

  it("parses id and event fields", () => {
    expect(parseChunks([encoder.encode("id: 7\nevent: update\ndata: ok\n\n")])[0]).toEqual({ id: "7", event: "update", data: "ok" });
  });

  it("ignores unknown fields", () => {
    expect(parseChunks([encoder.encode("retry: 10\nprivate: no\ndata: safe\n\n")])[0]).toEqual({ event: "message", data: "safe" });
  });

  it("flushes the final buffer without a trailing blank line", () => {
    expect(parseChunks([encoder.encode("event: final\ndata: done")])[0]?.data).toBe("done");
  });

  it("does not dispatch before an event boundary", () => {
    expect(parseChunks([encoder.encode("data: waiting")], false)).toEqual([]);
  });
});

describe("business event parsing", () => {
  it("validates known JSON events", () => {
    const event = streamEvent("plan_completed", { travel_plan: planFixture });
    expect(parseBusinessEvent("plan_completed", JSON.stringify(event))?.event_type).toBe("plan_completed");
  });

  it("rejects malformed JSON safely", () => {
    expect(() => parseBusinessEvent("run_started", "not-json")).toThrow(AppError);
  });

  it("ignores unknown event types", () => {
    expect(parseBusinessEvent("future_event", '{"raw":"ignored"}')).toBeNull();
  });

  it("rejects an event name and payload mismatch", () => {
    const event = streamEvent("plan_completed", { travel_plan: planFixture });
    expect(() => parseBusinessEvent("error", JSON.stringify(event))).toThrow(AppError);
  });

  it("recognizes AbortError without converting it to business error", () => {
    expect(isAbortError(new DOMException("Stopped", "AbortError"))).toBe(true);
  });
});
