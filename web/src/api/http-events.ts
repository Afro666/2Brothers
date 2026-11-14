import type { Api, LiveEvent, Session } from "@/api/types";

const RETRY_MS = 2_000;

function publish(raw: string, onEvent: (event: LiveEvent) => void) {
  let name = "";
  const data: string[] = [];
  for (const line of raw.split(/\r\n|\r|\n/)) {
    if (!line || line.startsWith(":")) continue;
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    const value = (colon === -1 ? "" : line.slice(colon + 1)).replace(/^ /, "");
    if (field === "event") name = value;
    if (field === "data") data.push(value);
  }
  if (name !== "proposal" && name !== "approval" && name !== "audit") return;
  try {
    const body = JSON.parse(data.join("\n")) as { operation?: unknown };
    if (typeof body?.operation === "string") onEvent({ kind: name, operation: body.operation });
  } catch {
    // A malformed event only loses that notification; polling remains the fallback.
  }
}

export function createEventsHttp(
  baseUrl: string,
  kitchen: string,
  getSession: () => Session | null,
): Pick<Api, "subscribeEvents"> {
  return {
    subscribeEvents(onEvent, onStatus) {
      let stopped = false;
      let unavailable = false;
      let controller: AbortController | null = null;
      let retry: ReturnType<typeof setTimeout> | undefined;

      const drop = (connection: AbortController | null) => {
        if (stopped || unavailable) return;
        if (connection && controller !== connection) return;
        controller = null;
        onStatus?.(false);
        if (!document.hidden && retry === undefined) {
          retry = setTimeout(() => {
            retry = undefined;
            open();
          }, RETRY_MS);
        }
      };

      const open = () => {
        if (stopped || unavailable || document.hidden || controller || retry !== undefined) return;
        const connection = new AbortController();
        controller = connection;
        const session = getSession();
        void fetch(`${baseUrl.replace(/\/$/, "")}${kitchen}/events`, {
          credentials: "same-origin",
          headers: session?.email ? undefined : { "X-User": session?.name || "human" },
          signal: connection.signal,
        })
          .then(async (response) => {
            if (stopped || controller !== connection) return;
            if (response.status === 503 || response.status === 401 || response.status === 403) {
              unavailable = true;
              controller = null;
              onStatus?.(false);
              return;
            }
            if (!response.ok || !response.body) {
              drop(connection);
              return;
            }
            onStatus?.(true);
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = "";
            try {
              while (true) {
                const { done, value } = await reader.read();
                if (done) {
                  const tail = decoder.decode();
                  if (tail.trim()) publish(tail, onEvent);
                  break;
                }
                buffer += decoder.decode(value, { stream: true });
                let boundary: RegExpMatchArray | null;
                while ((boundary = buffer.match(/(?:\r\n|\r|\n){2}/))) {
                  const end = boundary.index ?? 0;
                  const raw = buffer.slice(0, end);
                  buffer = buffer.slice(end + boundary[0].length);
                  if (raw.trim()) publish(raw, onEvent);
                }
              }
            } finally {
              reader.releaseLock();
            }
          })
          .catch(() => {})
          .then(() => {
            if (controller === connection) drop(connection);
          });
      };

      const visibility = () => {
        if (stopped || unavailable) return;
        if (document.hidden) {
          if (retry !== undefined) clearTimeout(retry);
          retry = undefined;
          controller?.abort();
          controller = null;
          onStatus?.(false);
        } else {
          open();
        }
      };
      document.addEventListener("visibilitychange", visibility);
      open();

      return () => {
        if (stopped) return;
        stopped = true;
        document.removeEventListener("visibilitychange", visibility);
        if (retry !== undefined) clearTimeout(retry);
        controller?.abort();
        controller = null;
        onStatus?.(false);
      };
    },
  };
}
