import { z } from "zod";

const USER_KEY = "travel-planner:user-id";
const THREAD_KEY = "travel-planner:thread-id";
const RECENT_KEY = "travel-planner:recent-threads";
const MAX_RECENT = 10;
const uuidSchema = z.string().uuid();
const recentThreadSchema = z
  .object({
    threadId: uuidSchema,
    createdAt: z.string().min(1),
    title: z.string().min(1).max(80),
  })
  .strict();

export type RecentThread = z.infer<typeof recentThreadSchema>;

function read(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    // The app still works for this tab when browser storage is unavailable.
  }
}

function validOrNew(value: string | null): string {
  return uuidSchema.safeParse(value).success ? String(value) : crypto.randomUUID();
}

export function getOrCreateIdentity(): { userId: string; threadId: string } {
  const userId = validOrNew(read(USER_KEY));
  const threadId = validOrNew(read(THREAD_KEY));
  write(USER_KEY, userId);
  write(THREAD_KEY, threadId);
  rememberThread(threadId, "New trip");
  return { userId, threadId };
}

export function getRecentThreads(): RecentThread[] {
  try {
    const raw: unknown = JSON.parse(read(RECENT_KEY) ?? "[]");
    const parsed = z.array(recentThreadSchema).max(MAX_RECENT).safeParse(raw);
    return parsed.success ? parsed.data : [];
  } catch {
    return [];
  }
}

export function rememberThread(threadId: string, title: string): RecentThread[] {
  const existing = getRecentThreads();
  const found = existing.find((item) => item.threadId === threadId);
  const next: RecentThread = {
    threadId,
    createdAt: found?.createdAt ?? new Date().toISOString(),
    title: title.trim().slice(0, 80) || "New trip",
  };
  const recent = [next, ...existing.filter((item) => item.threadId !== threadId)].slice(
    0,
    MAX_RECENT,
  );
  write(RECENT_KEY, JSON.stringify(recent));
  return recent;
}

export function setCurrentThread(threadId: string): void {
  if (!uuidSchema.safeParse(threadId).success) return;
  write(THREAD_KEY, threadId);
  rememberThread(threadId, getRecentThreads().find((item) => item.threadId === threadId)?.title ?? "New trip");
}

export function createThread(): string {
  const threadId = crypto.randomUUID();
  setCurrentThread(threadId);
  rememberThread(threadId, "New trip");
  return threadId;
}
