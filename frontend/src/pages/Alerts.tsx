import { AlertTriangle, Check, ShieldCheck } from "lucide-react";
import { useState } from "react";

import { PageHeader } from "@/components/layout/AppShell";
import { Badge } from "@/components/ui/Badge";
import { Band, BandHeader } from "@/components/ui/Band";
import { Button } from "@/components/ui/Button";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states";
import { count, dateTime, relativeTime } from "@/lib/format";
import { useAlerts, useDismissAlert, type Alert } from "@/lib/queries";
import { cn } from "@/lib/utils";

const FILTERS = [
  { value: "open", label: "Open" },
  { value: "resolved", label: "Resolved" },
  { value: "dismissed", label: "Dismissed" },
  { value: "all", label: "All" },
];

export function Alerts() {
  const [status, setStatus] = useState("open");

  const alerts = useAlerts({ status });
  const dismiss = useDismissAlert();

  const rows = alerts.data?.data ?? [];
  const open = alerts.data?.open_counts ?? {};
  const openTotal = (open.critical ?? 0) + (open.warning ?? 0) + (open.info ?? 0);

  return (
    <>
      <PageHeader
        title="Alerts"
        description="Raised by the event consumers, not by this page. Each one carries the evidence that fired it."
      />

      <Band>
        <BandHeader
          label="Needs attention"
          action={
            <>
              <div className="flex items-center gap-1">
                {FILTERS.map((filter) => (
                  <Button
                    key={filter.value}
                    size="sm"
                    variant={status === filter.value ? "primary" : "secondary"}
                    onClick={() => setStatus(filter.value)}
                    aria-pressed={status === filter.value}
                  >
                    {filter.label}
                  </Button>
                ))}
              </div>
              <span className="font-mono text-2xs tracking-wider text-ink-subtle uppercase">
                {/* Always the OPEN count, whatever is being viewed: a filtered
                    list should still say what it is hiding. */}
                {count(openTotal)} open
              </span>
            </>
          }
        />

        {alerts.isPending ? (
          <TableSkeleton rows={6} cols={4} />
        ) : alerts.isError ? (
          <ErrorState error={alerts.error} onRetry={() => alerts.refetch()} />
        ) : rows.length === 0 ? (
          <EmptyState
            icon={
              status === "open" ? (
                <ShieldCheck className="h-5 w-5" />
              ) : (
                <AlertTriangle className="h-5 w-5" />
              )
            }
            title={status === "open" ? "Nothing needs attention" : "Nothing here"}
            description={
              status === "open"
                ? "No stock line is below its reorder point or out of stock right now."
                : `No ${status} alerts yet.`
            }
          />
        ) : (
          <ul className="max-h-[calc(100vh-19rem)] overflow-y-auto">
            {rows.map((alert, index) => (
              <AlertRow
                key={alert.id}
                alert={alert}
                banded={index % 2 === 1}
                onDismiss={() => dismiss.mutate(alert.id)}
                dismissing={dismiss.isPending && dismiss.variables === alert.id}
              />
            ))}
          </ul>
        )}
      </Band>
    </>
  );
}

function AlertRow({
  alert,
  banded,
  onDismiss,
  dismissing,
}: {
  alert: Alert;
  banded: boolean;
  onDismiss: () => void;
  dismissing: boolean;
}) {
  const detail = alert.detail as Record<string, string | number | undefined>;

  return (
    <li
      className={cn(
        "flex flex-wrap items-start gap-x-4 gap-y-2 px-4 py-3",
        banded && "bg-sunken/60",
      )}
    >
      <div className="w-20 shrink-0 pt-0.5">
        <Badge tone={alert.severity === "critical" ? "danger" : "warning"}>
          {alert.severity}
        </Badge>
      </div>

      <div className="min-w-0 flex-1">
        <p className="font-medium">{alert.title}</p>

        {/* The evidence, laid out as the numbers it actually was. An alert that
            only asserts a conclusion is an alert you have to go and verify. */}
        <dl className="mt-1 flex flex-wrap gap-x-5 gap-y-1 text-2xs text-ink-muted">
          <Fact label="SKU" value={detail.sku} mono />
          <Fact label="Warehouse" value={detail.warehouse_name} />
          <Fact label="On hand" value={detail.quantity} mono />
          <Fact label="Reorder at" value={detail.reorder_point} mono />
        </dl>

        {detail.reason && (
          <p className="mt-1.5 text-2xs text-ink-subtle">{detail.reason}</p>
        )}
      </div>

      <time
        className="shrink-0 font-mono text-2xs text-ink-subtle"
        dateTime={alert.created_at}
        title={dateTime(alert.created_at)}
      >
        {relativeTime(alert.created_at)}
      </time>

      <div className="shrink-0">
        {alert.status === "open" ? (
          <Button
            size="sm"
            variant="secondary"
            onClick={onDismiss}
            loading={dismissing}
            icon={<Check className="h-3.5 w-3.5" />}
          >
            Dismiss
          </Button>
        ) : (
          <Badge tone="neutral">{alert.status}</Badge>
        )}
      </div>
    </li>
  );
}

function Fact({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string | number | undefined;
  mono?: boolean;
}) {
  if (value === undefined || value === null || value === "") return null;
  return (
    <div className="flex items-baseline gap-1.5">
      <dt className="text-ink-subtle">{label}</dt>
      <dd className={cn("text-ink", mono && "tnum")}>{value}</dd>
    </div>
  );
}
