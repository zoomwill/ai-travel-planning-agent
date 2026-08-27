import { useCallback, useState } from "react";

import {
  createThread,
  getOrCreateIdentity,
  getRecentThreads,
  rememberThread,
  setCurrentThread,
  type RecentThread,
} from "../lib/storage";

/** Own the anonymous local demo identity and a bounded list of thread pointers. */
export function useLocalIdentity(): {
  userId: string;
  threadId: string;
  recentThreads: RecentThread[];
  newTrip: () => void;
  selectThread: (threadId: string) => void;
  updateTitle: (title: string) => void;
} {
  const [identity] = useState(getOrCreateIdentity);
  const [threadId, setThreadId] = useState(identity.threadId);
  const [recentThreads, setRecentThreads] = useState(getRecentThreads);

  const newTrip = useCallback(() => {
    const next = createThread();
    setThreadId(next);
    setRecentThreads(getRecentThreads());
  }, []);

  const selectThread = useCallback((next: string) => {
    setCurrentThread(next);
    setThreadId(next);
    setRecentThreads(getRecentThreads());
  }, []);

  const updateTitle = useCallback(
    (title: string) => setRecentThreads(rememberThread(threadId, title)),
    [threadId],
  );

  return {
    userId: identity.userId,
    threadId,
    recentThreads,
    newTrip,
    selectThread,
    updateTitle,
  };
}
