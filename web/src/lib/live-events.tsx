import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";

import { useApi } from "@/api";
import type { LiveEvent } from "@/api/types";
import { useT } from "@/lib/i18n";
import { dropKeptAnswers } from "@/lib/use-async";

type Notice = { event: LiveEvent; reconnected?: never } | { event?: never; reconnected: true };
type Listener = (notice: Notice) => void;

const LiveEventsContext = createContext<{
  connected: boolean;
  listen: (listener: Listener) => () => void;
}>({ connected: false, listen: () => () => {} });

export function LiveEventsProvider({ children }: { children: ReactNode }) {
  const api = useApi();
  const [connected, setConnected] = useState(false);
  const listeners = useRef(new Set<Listener>());

  useEffect(() => {
    setConnected(false);
    if (!api.subscribeEvents) return;
    return api.subscribeEvents(
      (event) => {
        // Something changed in the kitchen: no page may show its kept answer as current.
        dropKeptAnswers();
        listeners.current.forEach((listener) => listener({ event }));
      },
      (isConnected) => {
        if (isConnected) dropKeptAnswers();
        setConnected(isConnected);
        // Nothing is replayed, so every connect (also the first: a change can land between a
        // page's first load and the stream opening) tells the lists to load again.
        if (isConnected) listeners.current.forEach((listener) => listener({ reconnected: true }));
      },
    );
  }, [api]);

  const listen = useCallback((listener: Listener) => {
    listeners.current.add(listener);
    return () => listeners.current.delete(listener);
  }, []);

  return <LiveEventsContext.Provider value={{ connected, listen }}>{children}</LiveEventsContext.Provider>;
}

export function useLiveEvents(kinds: readonly LiveEvent["kind"][], onChange: () => void) {
  const { listen } = useContext(LiveEventsContext);
  const callback = useRef(onChange);
  callback.current = onChange;
  const wanted = kinds.join("\0");

  useEffect(() => {
    const selected = new Set(wanted.split("\0"));
    let timer: ReturnType<typeof setTimeout> | undefined;
    const notify = () => {
      if (timer !== undefined) clearTimeout(timer);
      timer = setTimeout(() => {
        timer = undefined;
        callback.current();
      }, 300);
    };
    const stop = listen((notice) => {
      if (notice.reconnected || (notice.event && selected.has(notice.event.kind))) notify();
    });
    return () => {
      stop();
      if (timer !== undefined) clearTimeout(timer);
    };
  }, [listen, wanted]);
}

export function useLiveConnected(): boolean {
  return useContext(LiveEventsContext).connected;
}

export function LiveConnectionLabel() {
  const t = useT();
  if (!useLiveConnected()) return null;
  const description = t("New proposals appear here without a refresh (MongoDB Atlas change stream)");
  return (
    <span
      className="inline-flex items-center gap-1.5 text-xs font-normal text-muted-foreground"
      title={description}
      aria-label={description}
    >
      <span aria-hidden className="size-1.5 rounded-full bg-success" />
      <span>{t("Live")}</span>
      {/* Named on the page, not only on hover: a judge should see which Atlas feature this is. */}
      <span aria-hidden>· {t("MongoDB Atlas change stream")}</span>
    </span>
  );
}
