import { Activity, Pause, Play } from "lucide-react";
import { useMemo, useState } from "react";

import { PageHeader } from "@/components/layout/AppShell";
import { Badge } from "@/components/ui/Badge";
import { Band, BandHeader } from "@/components/ui/Band";
import { Button } from "@/components/ui/Button";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states";
import { count, currency, dateTime, relativeTime } from "@/lib/format";
import { useOutboxHealth, useRecentEvents } from "@/lib/queries";
import { useEventStream, type DomainEvent, type StreamStatus } from "@/lib/useEventStream";
import { cn } from "@/lib/utils";

/** Written once here so the feed and any future filter cannot disagree. */
const LABELS: Record<string, string> = {
  "stock.moved": "Stock moved",
  "stock.below_reorder_point": "Below reorder point",
  "stock.depleted": "Out of stock",
  "sale.completed": "Sale completed",
  "scan.recorded": "Scan recorded",
};

export function EventStream() {
  const [live, setLive] = useState(true);

  const history = useRecentEvents(50);
  const health = useOutboxHealth();
  const { events: streamed, status } = useEventStream(live);

  // One list from two sources. The page loads committed history from Postgres
  // and appends whatever Redis delivers after that; de-duplicating on event_id
  // covers the overlap, because an event can land in both if it is relayed
  // between the two requests.
  const rows = useMemo(() => {
    const seen = new Set<string>();
    const merged: DomainEvent[] = [];
    for (const event of [...streamed, ...(history.data?.data ?? [])]) {
      if (seen.has(event.event_id)) continue;
      seen.add(event.event_id);
      merged.push(event);
    }
    return merged;
  }, [streamed, history.data]);

  return (
    <>
      <PageHeader
        title="Event stream"
        description="Every domain event, in the order it was committed. This page is the outbox and the relay, live."
      />

      <div className="mb-4 grid gap-3 sm:grid-cols-3">
        <Stat
          label="Relayed"
          value={count(health.data?.published ?? 0)}
          hint="published to Redis"
        />
        <Stat
          label="Waiting"
          value={count(health.data?.unpublished ?? 0)}
          hint={
            health.data?.oldest_unpublished_age_seconds
              ? `oldest ${Math.round(health.data.oldest_unpublished_age_seconds)}s old`
              : "outbox is drained"
          }
          // A backlog is only interesting when it stops draining. One or two
          // in flight is the relay working, not the relay failing.
          tone={(health.data?.unpublished ?? 0) > 50 ? "warning" : "neutral"}
        />
        <Stat
          label="Connection"
          value={<StatusPill status={status} />}
          hint={live ? "server-sent events" : "paused by you"}
        />
      </div>

      <Band>
        <BandHeader
          label="Committed events"
          action={
            <>
              <Button
                size="sm"
                variant={live ? "secondary" : "primary"}
                onClick={() => setLive((v) => !v)}
                icon={
                  live ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />
                }
              >
                {live ? "Pause" : "Resume"}
              </Button>
              <span className="font-mono text-2xs tracking-wider text-ink-subtle uppercase">
                {count(rows.length)} shown
              </span>
            </>
          }
        />

        {history.isPending ? (
          <TableSkeleton rows={10} cols={4} />
        ) : history.isError ? (
          <ErrorState error={history.error} onRetry={() => history.refetch()} />
        ) : rows.length === 0 ? (
          <EmptyState
            icon={<Activity className="h-5 w-5" />}
            title="Nothing has happened yet"
            description="Record a sale, adjust stock or post a scan, and it appears here within a second."
          />
        ) : (
          <ol className="max-h-[calc(100vh-24rem)] overflow-y-auto">
            {rows.map((event, index) => (
              <EventRow key={event.event_id} event={event} banded={index % 2 === 1} />
            ))}
          </ol>
        )}
      </Band>
    </>
  );
}

function EventRow({ event, banded }: { event: DomainEvent; banded: boolean }) {
  return (
    <li
      className={cn(
        "flex flex-wrap items-baseline gap-x-3 gap-y-1 px-4 py-2",
        banded && "bg-sunken/60",
      )}
    >
      <span className="tnum w-16 shrink-0 text-2xs text-ink-subtle">
        #{event.sequence}
      </span>
      <span className="w-44 shrink-0">
        <Badge tone={toneFor(event.event_type)}>
          {LABELS[event.event_type] ?? event.event_type}
        </Badge>
      </span>
      <span className="min-w-0 flex-1 text-sm">{describe(event)}</span>
      <time
        className="font-mono text-2xs text-ink-subtle"
        dateTime={event.occurred_at}
        title={dateTime(event.occurred_at)}
      >
        {relativeTime(event.occurred_at)}
      </time>
    </li>
  );
}

/**
 * Turn a payload into a sentence.
 *
 * The stream is the most technical page here, which is exactly why the rows
 * should not read as JSON. "Acer Bluetooth Speaker: 3 out of Chennai Port
 * Facility, 37 left" is the same information a dump of the payload carries, and
 * a person can act on it without decoding anything.
 */
function describe(event: DomainEvent): string {
  const p = event.payload as Record<string, never>;
  const name = (p.product_name as string) ?? (p.sku as string) ?? "";

  switch (event.event_type) {
    case "stock.moved": {
      const change = Number(p.quantity_change ?? 0);
      const direction = change < 0 ? "out of" : "into";
      return `${name}: ${Math.abs(change)} ${direction} ${p.warehouse_name}, ${count(
        Number(p.quantity_after ?? 0),
      )} left`;
    }
    case "stock.below_reorder_point":
      return `${name} fell to ${count(Number(p.quantity ?? 0))}, below its reorder point of ${count(
        Number(p.reorder_point ?? 0),
      )}`;
    case "stock.depleted":
      return `${name} is out of stock at ${p.warehouse_name}`;
    case "sale.completed":
      return `${p.customer_name} bought ${count(Number(p.unit_count ?? 0))} units across ${count(
        Number(p.line_count ?? 0),
      )} lines — ${currency(Number(p.total_amount ?? 0))}`;
    case "scan.recorded":
      return `${name} scanned ${p.direction === "in" ? "in" : "out"} (${count(
        Number(p.quantity ?? 0),
      )}) by ${p.device_id ?? "an unnamed device"}`;
    default:
      return JSON.stringify(event.payload);
  }
}

function toneFor(eventType: string) {
  if (eventType === "stock.depleted") return "danger" as const;
  if (eventType === "stock.below_reorder_point") return "warning" as const;
  if (eventType === "sale.completed") return "outline" as const;
  return "neutral" as const;
}

function StatusPill({ status }: { status: StreamStatus }) {
  const map = {
    live: { label: "Live", tone: "success" as const },
    connecting: { label: "Connecting", tone: "neutral" as const },
    reconnecting: { label: "Reconnecting", tone: "warning" as const },
    stopped: { label: "Paused", tone: "neutral" as const },
  };
  const { label, tone } = map[status];

  return (
    <span className="inline-flex items-center gap-2">
      {status === "live" && (
        <span className="relative flex h-2 w-2" aria-hidden>
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-success opacity-60" />
          <span className="relative inline-flex h-2 w-2 rounded-full bg-success" />
        </span>
      )}
      <Badge tone={tone}>{label}</Badge>
    </span>
  );
}

function Stat({
  label,
  value,
  hint,
  tone = "neutral",
}: {
  label: string;
  value: React.ReactNode;
  hint?: string;
  tone?: "neutral" | "warning";
}) {
  return (
    <div className="rounded-lg border border-border bg-surface px-4 py-3">
      <p className="eyebrow">{label}</p>
      <p
        className={cn(
          "mt-1.5 font-display text-2xl leading-none font-semibold",
          tone === "warning" && "text-warning",
        )}
      >
        {value}
      </p>
      {hint && <p className="mt-1.5 text-2xs text-ink-subtle">{hint}</p>}
    </div>
  );
}
