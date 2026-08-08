import { useEffect, useRef, useState } from "react";

import { tokenStore } from "@/lib/api";

export interface DomainEvent {
  sequence: string | number;
  event_id: string;
  event_type: string;
  aggregate_type: string;
  aggregate_id: string;
  occurred_at: string;
  payload: Record<string, unknown>;
}

export type StreamStatus = "connecting" | "live" | "reconnecting" | "stopped";

/**
 * Subscribe to the server-sent event stream.
 *
 * Uses fetch + a ReadableStream rather than the browser's EventSource. That is
 * a deliberate trade of a few dozen lines for one property: EventSource cannot
 * send an Authorization header, so every EventSource implementation of an
 * authenticated stream ends up putting the token in the query string, where it
 * lands in access logs, proxy logs and browser history. fetch can set headers,
 * so the token stays where every other request in this app puts it.
 *
 * What is given up is EventSource's automatic reconnection, so that is
 * reimplemented below -- with backoff, which EventSource does not do anyway.
 */
export function useEventStream(enabled = true, cap = 200) {
  const [events, setEvents] = useState<DomainEvent[]>([]);
  const [status, setStatus] = useState<StreamStatus>("connecting");
  // A ref, not state: the reconnect loop reads it and must not restart the
  // effect every time a delay changes.
  const attempt = useRef(0);

  useEffect(() => {
    if (!enabled) {
      setStatus("stopped");
      return;
    }

    const controller = new AbortController();
    let cancelled = false;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;

    async function connect() {
      try {
        setStatus(attempt.current === 0 ? "connecting" : "reconnecting");

        const response = await fetch("/api/v1/events/stream", {
          headers: {
            Accept: "text/event-stream",
            Authorization: `Bearer ${tokenStore.get() ?? ""}`,
          },
          signal: controller.signal,
        });

        if (!response.ok || !response.body) {
          throw new Error(`Stream refused with ${response.status}`);
        }

        attempt.current = 0;
        setStatus("live");

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        for (;;) {
          const { done, value } = await reader.read();
          if (done || cancelled) break;

          buffer += decoder.decode(value, { stream: true });

          // SSE frames are separated by a blank line. A chunk can split one in
          // half, so anything after the last separator stays in the buffer
          // until the rest of it arrives.
          const frames = buffer.split("\n\n");
          buffer = frames.pop() ?? "";

          for (const frame of frames) {
            const data = frame
              .split("\n")
              .filter((line) => line.startsWith("data:"))
              .map((line) => line.slice(5).trim())
              .join("");
            if (!data) continue; // keepalive comment

            try {
              const event = JSON.parse(data) as DomainEvent;
              // Newest first, and bounded. A tab left open overnight would
              // otherwise hold every event of the day in memory and render
              // them all on each update.
              setEvents((current) => [event, ...current].slice(0, cap));
            } catch {
              // A malformed frame is not worth tearing the connection down for.
            }
          }
        }

        if (!cancelled) scheduleReconnect();
      } catch (error) {
        if (controller.signal.aborted || cancelled) return;
        console.warn("Event stream dropped:", error);
        scheduleReconnect();
      }
    }

    function scheduleReconnect() {
      if (cancelled) return;
      setStatus("reconnecting");
      // Exponential backoff, capped. A server that is down should not be asked
      // once a second by every open tab -- that is how a brief outage becomes a
      // sustained one.
      const delay = Math.min(1000 * 2 ** attempt.current, 30_000);
      attempt.current += 1;
      retryTimer = setTimeout(connect, delay);
    }

    connect();

    return () => {
      cancelled = true;
      controller.abort();
      if (retryTimer) clearTimeout(retryTimer);
    };
  }, [enabled, cap]);

  return { events, status, clear: () => setEvents([]) };
}
