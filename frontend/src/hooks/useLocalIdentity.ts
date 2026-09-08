import { useCallback, useState } from "react";
import { useAuthSession } from "../auth/context";

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
  const scope = useAuthSession()?.storageScope ?? "";
  const [identity] = useState(() => getOrCreateIdentity(scope));
  const [threadId, setThreadId] = useState(identity.threadId);
  const [recentThreads, setRecentThreads] = useState(() => getRecentThreads(scope));

  const newTrip = useCallback(() => {
    const next = createThread(scope);
    setThreadId(next);
    setRecentThreads(getRecentThreads(scope));
  }, [scope]);

  const selectThread = useCallback((next: string) => {
    setCurrentThread(next, scope);
    setThreadId(next);
    setRecentThreads(getRecentThreads(scope));
  }, [scope]);

  const updateTitle = useCallback(
    (title: string) => setRecentThreads(rememberThread(threadId, title, scope)),
    [threadId, scope],
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
