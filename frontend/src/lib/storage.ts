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

function scoped(key: string, scope: string): string {
  return scope ? `${key}:auth:${scope}` : key;
}

export function getOrCreateIdentity(scope = ""): { userId: string; threadId: string } {
  const userId = scope ? "authenticated" : validOrNew(read(USER_KEY));
  const threadId = validOrNew(read(scoped(THREAD_KEY, scope)));
  if (!scope) write(USER_KEY, userId);
  write(scoped(THREAD_KEY, scope), threadId);
  rememberThread(threadId, "New trip", scope);
  return { userId, threadId };
}

export function getRecentThreads(scope = ""): RecentThread[] {
  try {
    const raw: unknown = JSON.parse(read(scoped(RECENT_KEY, scope)) ?? "[]");
    const parsed = z.array(recentThreadSchema).max(MAX_RECENT).safeParse(raw);
    return parsed.success ? parsed.data : [];
  } catch {
    return [];
  }
}

export function rememberThread(threadId: string, title: string, scope = ""): RecentThread[] {
  const existing = getRecentThreads(scope);
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
  write(scoped(RECENT_KEY, scope), JSON.stringify(recent));
  return recent;
}

export function setCurrentThread(threadId: string, scope = ""): void {
  if (!uuidSchema.safeParse(threadId).success) return;
  write(scoped(THREAD_KEY, scope), threadId);
  rememberThread(threadId, getRecentThreads(scope).find((item) => item.threadId === threadId)?.title ?? "New trip", scope);
}

export function createThread(scope = ""): string {
  const threadId = crypto.randomUUID();
  setCurrentThread(threadId, scope);
  rememberThread(threadId, "New trip", scope);
  return threadId;
}

/** Clear only this session's local pointers; never delete persisted server data. */
export function clearSessionPointers(scope: string): void {
  if (!scope) return;
  try {
    localStorage.removeItem(scoped(THREAD_KEY, scope));
    localStorage.removeItem(scoped(RECENT_KEY, scope));
  } catch { /* The workspace still unmounts when browser storage is unavailable. */ }
}
