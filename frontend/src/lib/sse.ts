/** One parsed SSE record before its JSON payload is validated. */
export interface RawSseEvent {
  id?: string;
  event: string;
  data: string;
}

/** Incrementally parses SSE across arbitrary UTF-8 byte and line boundaries. */
export class SseParser {
  private readonly decoder = new TextDecoder();
  private readonly onEvent: (event: RawSseEvent) => void;
  private buffer = "";
  private dataLines: string[] = [];
  private eventName = "message";
  private eventId: string | undefined;

  constructor(onEvent: (event: RawSseEvent) => void) {
    this.onEvent = onEvent;
  }

  push(chunk: Uint8Array): void {
    this.buffer += this.decoder.decode(chunk, { stream: true });
    this.processLines(false);
  }

  finish(): void {
    this.buffer += this.decoder.decode();
    this.processLines(true);
    this.dispatch();
  }

  private processLines(flush: boolean): void {
    while (true) {
      const newline = this.buffer.search(/[\r\n]/);
      if (newline === -1) break;
      const character = this.buffer[newline];
      if (character === "\r" && newline === this.buffer.length - 1 && !flush) break;
      const line = this.buffer.slice(0, newline);
      const consumed = character === "\r" && this.buffer[newline + 1] === "\n" ? 2 : 1;
      this.buffer = this.buffer.slice(newline + consumed);
      this.processLine(line);
    }
    if (flush && this.buffer.length > 0) {
      this.processLine(this.buffer);
      this.buffer = "";
    }
  }

  private processLine(line: string): void {
    if (line === "") {
      this.dispatch();
      return;
    }
    if (line.startsWith(":")) return;
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "data") this.dataLines.push(value);
    else if (field === "event") this.eventName = value || "message";
    else if (field === "id" && !value.includes("\0")) this.eventId = value;
  }

  private dispatch(): void {
    if (this.dataLines.length === 0) {
      this.eventName = "message";
      this.eventId = undefined;
      return;
    }
    const event: RawSseEvent = {
      event: this.eventName,
      data: this.dataLines.join("\n"),
      ...(this.eventId === undefined ? {} : { id: this.eventId }),
    };
    this.dataLines = [];
    this.eventName = "message";
    this.eventId = undefined;
    this.onEvent(event);
  }
}
