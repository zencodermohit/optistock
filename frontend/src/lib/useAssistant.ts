import { useCallback, useRef, useState } from "react";

import { tokenStore } from "@/lib/api";

export interface Citation {
  type: string;
  label: string;
  ref: string;
}

export interface ToolCall {
  name: string;
  input: Record<string, unknown>;
}

export interface Turn {
  role: "user" | "assistant";
  text: string;
  tools: ToolCall[];
  citations: Citation[];
  error?: string;
  /**
   * A caveat about the answer rather than a failure of it — currently, that
   * the tool-call budget ran out before the model finished looking. Separate
   * from `error` because the answer above it is still worth reading.
   */
  notices: string[];
  /** True while this turn is still being written. */
  streaming?: boolean;
}

/**
 * Drives the assistant endpoint.
 *
 * fetch + ReadableStream rather than EventSource, for the same reason the event
 * stream page uses it: EventSource cannot send an Authorization header, and
 * every workaround puts the token in the query string where it lands in access
 * logs. This is a POST anyway, which EventSource cannot do at all.
 */
export function useAssistant() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const abort = useRef<AbortController | null>(null);

  const stop = useCallback(() => {
    abort.current?.abort();
    abort.current = null;
    setBusy(false);
    setTurns((current) =>
      current.map((t) => (t.streaming ? { ...t, streaming: false } : t)),
    );
  }, []);

  const ask = useCallback(
    async (question: string) => {
      if (!question.trim() || busy) return;

      const controller = new AbortController();
      abort.current = controller;
      setBusy(true);

      setTurns((current) => [
        ...current,
        { role: "user", text: question, tools: [], citations: [], notices: [] },
        {
          role: "assistant",
          text: "",
          tools: [],
          citations: [],
          notices: [],
          streaming: true,
        },
      ]);

      // Mutates only the last turn, so a long answer doesn't rebuild the
      // whole transcript on every token.
      const patch = (fn: (turn: Turn) => Turn) =>
        setTurns((current) =>
          current.map((t, i) => (i === current.length - 1 ? fn(t) : t)),
        );

      try {
        const response = await fetch("/api/v1/assistant/ask", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Accept: "text/event-stream",
            Authorization: `Bearer ${tokenStore.get() ?? ""}`,
          },
          body: JSON.stringify({ question }),
          signal: controller.signal,
        });

        if (!response.ok || !response.body) {
          throw new Error(`The assistant refused the request (${response.status}).`);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          // A chunk can split a frame, so anything after the last separator
          // waits for the rest of it to arrive.
          const frames = buffer.split("\n\n");
          buffer = frames.pop() ?? "";

          for (const frame of frames) {
            const data = frame
              .split("\n")
              .filter((line) => line.startsWith("data:"))
              .map((line) => line.slice(5).trim())
              .join("");
            if (!data) continue;

            let event: Record<string, never>;
            try {
              event = JSON.parse(data);
            } catch {
              continue;
            }

            switch (event.type as string) {
              case "text":
                patch((t) => ({ ...t, text: t.text + (event.text as string) }));
                break;
              case "tool":
                patch((t) => ({
                  ...t,
                  tools: [
                    ...t.tools,
                    { name: event.name as string, input: event.input ?? {} },
                  ],
                }));
                break;
              case "citation":
                patch((t) => ({
                  ...t,
                  citations: [...t.citations, event.citation as unknown as Citation],
                }));
                break;
              case "notice":
                // Appended, not replaced. One answer can carry several
                // caveats -- it was cut short AND it ran out of lookups --
                // and overwriting means the reader only ever sees the last.
                patch((t) => ({
                  ...t,
                  notices: [...t.notices, event.message as string],
                }));
                break;
              case "error":
                patch((t) => ({ ...t, error: event.message as string }));
                break;
              default:
                break;
            }
          }
        }
      } catch (error) {
        if (!controller.signal.aborted) {
          patch((t) => ({
            ...t,
            error:
              error instanceof Error ? error.message : "The assistant stopped.",
          }));
        }
      } finally {
        patch((t) => ({ ...t, streaming: false }));
        setBusy(false);
        abort.current = null;
      }
    },
    [busy],
  );

  const clear = useCallback(() => setTurns([]), []);

  return { turns, busy, ask, stop, clear };
}
