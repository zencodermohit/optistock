import { ArrowUp, Square, Wrench } from "lucide-react";
import Markdown from "react-markdown";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { PageHeader } from "@/components/layout/AppShell";
import { Badge } from "@/components/ui/Badge";
import { Band, BandHeader } from "@/components/ui/Band";
import { Button } from "@/components/ui/Button";
import { useAssistantStatus } from "@/lib/queries";
import { useAssistant, type Turn } from "@/lib/useAssistant";
import { cn } from "@/lib/utils";

/** Openers that show what the assistant is for, phrased as a person would ask. */
const STARTERS = [
  "What needs reordering right now?",
  "How has revenue been over the last 30 days?",
  "Can I trust the forecast?",
  "What happened in the last hour?",
];

export function Assistant() {
  const status = useAssistantStatus();
  const { turns, busy, ask, stop } = useAssistant();
  const [draft, setDraft] = useState("");
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns]);

  function submit(event: FormEvent) {
    event.preventDefault();
    const question = draft.trim();
    if (!question) return;
    setDraft("");
    void ask(question);
  }

  const configured = status.data?.configured ?? true;

  return (
    <>
      <PageHeader
        title="Assistant"
        description="Ask about your stock, trading and alerts. Every answer is built from tool calls against your own data."
      />

      {status.data && !configured && (
        <Band className="mb-4 p-4">
          <p className="eyebrow">Not configured</p>
          <p className="mt-2 text-sm text-ink-muted">
            The server has no <span className="tnum">GEMINI_API_KEY</span> set, so
            the assistant is switched off. Everything else in OptiStock works
            without it. A free key comes from aistudio.google.com/apikey.
          </p>
        </Band>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        <Band className="flex min-h-[28rem] flex-col lg:col-span-2">
          <BandHeader
            label="Conversation"
            action={
              status.data?.model && (
                <span className="font-mono text-2xs text-ink-subtle">
                  {status.data.model}
                </span>
              )
            }
          />

          <div className="flex-1 overflow-y-auto px-4 py-4">
            {turns.length === 0 ? (
              <div className="mx-auto max-w-lg py-8">
                <p className="text-sm text-ink-muted">
                  This assistant can only read. It answers from the same records
                  the rest of the app shows, and it will say so when a question
                  falls outside what it can see.
                </p>
                <div className="mt-5 flex flex-col gap-2">
                  {STARTERS.map((starter) => (
                    <button
                      key={starter}
                      type="button"
                      disabled={!configured}
                      onClick={() => void ask(starter)}
                      className="rounded-md border border-border bg-surface px-3 py-2 text-left text-sm transition-colors hover:border-accent-border hover:bg-accent-soft disabled:opacity-50"
                    >
                      {starter}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <ol className="space-y-5">
                {turns.map((turn, index) => (
                  <li key={index}>
                    <TurnBlock turn={turn} />
                  </li>
                ))}
              </ol>
            )}
            <div ref={bottom} />
          </div>

          <form
            onSubmit={submit}
            className="flex items-end gap-2 border-t border-border bg-sunken px-4 py-3"
          >
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                // Enter sends, Shift+Enter breaks the line — the convention
                // every chat box shares, and the one people try first.
                if (e.key === "Enter" && !e.shiftKey) submit(e);
              }}
              rows={1}
              disabled={!configured}
              placeholder={
                configured ? "Ask about your inventory" : "Assistant unavailable"
              }
              aria-label="Ask the assistant"
              className="max-h-32 min-h-9 flex-1 resize-y rounded-md border border-border-strong bg-surface px-3 py-2 text-base text-ink placeholder:text-ink-subtle focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:bg-sunken"
            />
            {busy ? (
              <Button
                type="button"
                variant="secondary"
                onClick={stop}
                icon={<Square className="h-3.5 w-3.5" />}
              >
                Stop
              </Button>
            ) : (
              <Button
                type="submit"
                disabled={!draft.trim() || !configured}
                icon={<ArrowUp className="h-4 w-4" />}
              >
                Ask
              </Button>
            )}
          </form>
        </Band>

        <Band className="self-start p-4">
          <p className="eyebrow">What it can reach</p>
          {/* Published deliberately. An assistant whose scope is invisible gets
              asked questions it cannot answer, and each one reads as a failure
              rather than as a boundary. */}
          <ul className="mt-3 space-y-2.5">
            {(status.data?.tools ?? []).map((tool) => (
              <li key={tool.name}>
                <p className="font-mono text-2xs text-accent">{tool.name}</p>
                <p className="mt-0.5 text-2xs leading-relaxed text-ink-muted">
                  {tool.description.split(". ")[0]}.
                </p>
              </li>
            ))}
          </ul>
          <p className="mt-4 border-t border-border pt-3 text-2xs text-ink-subtle">
            Read-only, and scoped to your company by the server rather than by
            the question. It cannot change stock, dismiss alerts or place orders.
          </p>
        </Band>
      </div>
    </>
  );
}

function TurnBlock({ turn }: { turn: Turn }) {
  if (turn.role === "user") {
    return (
      <div className="flex justify-end">
        <p className="max-w-[80%] rounded-lg rounded-br-sm bg-accent px-3 py-2 text-sm text-white">
          {turn.text}
        </p>
      </div>
    );
  }

  return (
    <div className="max-w-[90%]">
      {/* The tools it reached for, shown as it goes. Watching the steps is what
          separates "it answered" from "it looked it up". */}
      {turn.tools.length > 0 && (
        <div className="mb-2 flex flex-wrap gap-1.5">
          {turn.tools.map((tool, i) => (
            <span
              key={`${tool.name}-${i}`}
              className="inline-flex items-center gap-1 rounded-sm border border-border bg-sunken px-1.5 py-0.5 font-mono text-2xs text-ink-muted"
            >
              <Wrench className="h-2.5 w-2.5" />
              {tool.name}
            </span>
          ))}
        </div>
      )}

      {turn.text && (
        <div className="text-sm leading-relaxed">
          {/* The model answers in Markdown -- lists of SKUs, bold figures,
              small headings. Rendered as plain text it showed literal ** and
              ###, which reads as a broken integration rather than a formatting
              choice. Each element is mapped onto the design tokens instead of
              inheriting a stylesheet, so an answer looks like the rest of the
              product rather than like a README. */}
          <Markdown
            components={{
              p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
              strong: ({ children }) => (
                <strong className="font-semibold text-ink">{children}</strong>
              ),
              ul: ({ children }) => (
                <ul className="mb-2 ml-4 list-disc space-y-0.5 last:mb-0">{children}</ul>
              ),
              ol: ({ children }) => (
                <ol className="mb-2 ml-4 list-decimal space-y-0.5 last:mb-0">
                  {children}
                </ol>
              ),
              // Headings inside a chat bubble are a paragraph with emphasis, not
              // a document outline -- an <h3> here would outrank the page title.
              h1: ({ children }) => <p className="eyebrow mt-3 mb-1">{children}</p>,
              h2: ({ children }) => <p className="eyebrow mt-3 mb-1">{children}</p>,
              h3: ({ children }) => <p className="eyebrow mt-3 mb-1">{children}</p>,
              code: ({ children }) => (
                <code className="tnum rounded-sm bg-sunken px-1 py-0.5 text-2xs">
                  {children}
                </code>
              ),
              a: ({ children, href }) => (
                <a href={href} className="text-accent underline underline-offset-2">
                  {children}
                </a>
              ),
              hr: () => <hr className="my-3 border-border" />,
            }}
          >
            {turn.text}
          </Markdown>
          {turn.streaming && (
            <span className="ml-0.5 inline-block h-3.5 w-1.5 translate-y-0.5 animate-pulse bg-accent" />
          )}
        </div>
      )}

      {turn.streaming && !turn.text && (
        <p className="text-sm text-ink-subtle">Looking it up…</p>
      )}

      {turn.error && (
        <p
          role="alert"
          className="mt-2 rounded-sm border border-danger/25 bg-danger-soft px-2.5 py-1.5 text-xs text-danger"
        >
          {turn.error}
        </p>
      )}

      {turn.citations.length > 0 && (
        <div className="mt-3 border-t border-border pt-2">
          <p className="eyebrow">From</p>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {turn.citations.map((citation, i) => (
              <Badge
                key={`${citation.ref}-${i}`}
                tone="neutral"
                className={cn("normal-case")}
                title={citation.label}
              >
                {citation.ref}
              </Badge>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
