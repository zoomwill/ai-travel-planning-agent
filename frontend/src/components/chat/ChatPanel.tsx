import { ArrowUp, Bot, RotateCcw, Sparkles, User } from "lucide-react";
import { type FormEvent, type KeyboardEvent, useEffect, useRef, useState } from "react";

import type { ConversationResponse } from "../../api/types";
import { formatDateTime } from "../../lib/formatters";
import type { UiPhase } from "../../state/appReducer";

const MAX_MESSAGE_LENGTH = 4000;
const examples = [
  "Plan a 5-day photography trip to Tokyo.",
  "I want a quiet week in Paris in October.",
  "Help me plan a budget trip from Cleveland to Japan.",
  "Plan a relaxed food and museum trip to Shanghai.",
];

interface ChatPanelProps {
  conversation: ConversationResponse | null;
  phase: UiPhase;
  optimisticMessage: string | null;
  failedMessage: string | null;
  onSend: (message: string) => Promise<void>;
}

/** Natural-language conversation surface backed entirely by the P15 API. */
export function ChatPanel({
  conversation,
  phase,
  optimisticMessage,
  failedMessage,
  onSend,
}: ChatPanelProps) {
  const [message, setMessage] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const sending = optimisticMessage !== null;
  const disabled = phase === "booting" || phase === "planning" || sending;

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [conversation?.messages.length, optimisticMessage]);

  const submit = async (event?: FormEvent): Promise<void> => {
    event?.preventDefault();
    const trimmed = message.trim();
    if (disabled || trimmed.length === 0 || trimmed.length > MAX_MESSAGE_LENGTH) return;
    setMessage("");
    await onSend(trimmed);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>): void => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      void submit();
    }
  };

  const hasMessages = (conversation?.messages.length ?? 0) > 0 || optimisticMessage !== null;

  return (
    <section className="chat-panel" aria-labelledby="conversation-heading">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Conversation</p>
          <h2 id="conversation-heading" className="text-xl font-bold text-slate-950">
            Plan your next journey
          </h2>
        </div>
        {conversation !== null && (
          <span className="status-chip">{conversation.status.replaceAll("_", " ")}</span>
        )}
      </div>

      <div className="message-scroll" ref={scrollRef} aria-live="polite" aria-relevant="additions text">
        {!hasMessages && (
          <div className="welcome-state">
            <span className="welcome-icon"><Sparkles aria-hidden="true" size={28} /></span>
            <p className="eyebrow mt-5">Start with an idea</p>
            <h1 className="mt-2 text-3xl font-bold tracking-tight text-slate-950 sm:text-4xl">
              Where do you want to go?
            </h1>
            <p className="mt-3 max-w-lg text-sm leading-6 text-slate-500 sm:text-base">
              Share what you know. I&apos;ll ask for the missing details before building your trip.
            </p>
            <div className="mt-7 grid w-full max-w-2xl gap-2 sm:grid-cols-2">
              {examples.map((example) => (
                <button
                  className="example-prompt"
                  type="button"
                  key={example}
                  onClick={() => {
                    setMessage(example);
                    textareaRef.current?.focus();
                  }}
                >
                  {example}
                </button>
              ))}
            </div>
          </div>
        )}

        {conversation?.messages.map((item) => (
          <article className={`message-row message-${item.role}`} key={item.message_id}>
            <span className="message-avatar" aria-hidden="true">
              {item.role === "assistant" ? <Bot size={17} /> : <User size={17} />}
            </span>
            <div>
              <div className="message-bubble">{item.content}</div>
              <time className="message-time" dateTime={item.created_at}>
                {formatDateTime(item.created_at)}
              </time>
            </div>
          </article>
        ))}

        {optimisticMessage !== null && (
          <article className="message-row message-user" aria-label="Sending message">
            <span className="message-avatar" aria-hidden="true"><User size={17} /></span>
            <div>
              <div className="message-bubble opacity-75">{optimisticMessage}</div>
              <p className="message-time">Sending…</p>
            </div>
          </article>
        )}
      </div>

      <form className="composer" onSubmit={(event) => void submit(event)}>
        <label className="sr-only" htmlFor="trip-message">Describe your trip</label>
        <textarea
          id="trip-message"
          ref={textareaRef}
          rows={2}
          maxLength={MAX_MESSAGE_LENGTH}
          value={message}
          disabled={disabled}
          placeholder={phase === "planning" ? "Planning is in progress…" : "Tell me about your trip…"}
          onChange={(event) => setMessage(event.target.value)}
          onKeyDown={onKeyDown}
        />
        <div className="flex items-center justify-between gap-3">
          <span className="text-xs text-slate-400">
            {message.length >= 3600 ? `${message.length}/${MAX_MESSAGE_LENGTH}` : "Enter to send · Shift+Enter for a new line"}
          </span>
          <button
            className="send-button"
            type="submit"
            aria-label="Send message"
            disabled={disabled || message.trim().length === 0}
          >
            <ArrowUp aria-hidden="true" size={18} />
          </button>
        </div>
        {failedMessage !== null && (
          <button className="button-secondary self-start" type="button" onClick={() => void onSend(failedMessage)}>
            <RotateCcw aria-hidden="true" size={15} /> Retry last message
          </button>
        )}
      </form>
    </section>
  );
}
