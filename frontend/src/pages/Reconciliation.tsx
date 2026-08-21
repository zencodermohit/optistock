import { Check, ClipboardList, X } from "lucide-react";

import { PageHeader } from "@/components/layout/AppShell";
import { Badge } from "@/components/ui/Badge";
import { Band, BandHeader } from "@/components/ui/Band";
import { Button } from "@/components/ui/Button";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/states";
import { count, dateTime } from "@/lib/format";
import {
  useReconciliations,
  useReconDecision,
  type ReconRow,
} from "@/lib/queries";
import { cn } from "@/lib/utils";

/**
 * Cycle counts — where the shelf disagrees with the system.
 *
 * Approving one of these does something no other screen does: it writes the
 * shelf's number over the system's. Every figure elsewhere in the product is
 * derived from stock levels, so an approval here quietly rewrites the premise
 * of the forecast, the stockout dates and the alerts. That is why the variance
 * is worked out on the server and shown in full before anyone can approve it.
 *
 * Short and over are kept apart rather than netted. A count that is 40 short on
 * one product and 40 over on another is not a clean count — it is two errors,
 * and a net of zero would hide both.
 */
export function Reconciliation() {
  const recons = useReconciliations();
  const rows = recons.data?.data ?? [];

  const pending = rows.filter((row) => row.status === "pending");
  const settled = rows.filter((row) => row.status !== "pending");

  return (
    <>
      <PageHeader
        title="Stock counts"
        description="Physical counts against system quantities. Approving one overwrites what the system believes."
      />

      {recons.isError ? (
        <ErrorState error={recons.error} onRetry={() => void recons.refetch()} />
      ) : recons.isLoading ? (
        <Band className="space-y-3 p-4">
          {Array.from({ length: 2 }).map((_, i) => (
            <Skeleton key={i} className="h-24 w-full" />
          ))}
        </Band>
      ) : rows.length === 0 ? (
        <Band>
          <EmptyState
            icon={<ClipboardList className="h-5 w-5" />}
            title="No counts submitted"
            description="Cycle counts appear here for review before they change stock levels."
          />
        </Band>
      ) : (
        <div className="space-y-4">
          {pending.length > 0 && (
            <Band>
              <BandHeader
                label="Awaiting review"
                description="Nothing here has changed stock yet."
                action={
                  <span className="tnum text-2xs text-ink-subtle">
                    {pending.length}
                  </span>
                }
              />
              <ul className="divide-y divide-border">
                {pending.map((row) => (
                  <li key={row.id}>
                    <CountCard row={row} decidable />
                  </li>
                ))}
              </ul>
            </Band>
          )}

          {settled.length > 0 && (
            <Band>
              <BandHeader label="Decided" />
              <ul className="divide-y divide-border">
                {settled.map((row) => (
                  <li key={row.id}>
                    <CountCard row={row} />
                  </li>
                ))}
              </ul>
            </Band>
          )}
        </div>
      )}
    </>
  );
}

function CountCard({ row, decidable }: { row: ReconRow; decidable?: boolean }) {
  const decide = useReconDecision();
  const clean = row.discrepancies === 0;

  return (
    <div className="px-4 py-3.5">
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        {/* basis-64 rather than the basis-0 that flex-1 implies. With a zero
            basis this column contributes no intrinsic width, so on a phone the
            approve/reject controls kept their size and the summary line was
            squeezed to 35px -- about three characters. A real minimum makes the
            controls wrap underneath instead. */}
        <div className="min-w-0 flex-1 basis-64">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-display text-base font-semibold">
              {row.warehouse_name}
            </span>
            {row.status === "approved" && <Badge tone="success">approved</Badge>}
            {row.status === "rejected" && <Badge>rejected</Badge>}
            {clean ? (
              <Badge tone="success">no discrepancies</Badge>
            ) : (
              <Badge tone="warning">
                {count(row.discrepancies)} of {count(row.counted)} off
              </Badge>
            )}
          </div>

          <p className="mt-1.5 text-sm text-ink-muted">
            {count(row.counted)} products counted
            {!clean && (
              <>
                {" · "}
                {row.units_short > 0 && (
                  <span className="tnum text-danger">
                    {count(row.units_short)} short
                  </span>
                )}
                {row.units_short > 0 && row.units_over > 0 && " · "}
                {row.units_over > 0 && (
                  <span className="tnum text-warning">
                    {count(row.units_over)} over
                  </span>
                )}
              </>
            )}
          </p>

          {/* Only the lines that disagree. A clean line is not evidence, and
              listing four hundred of them buries the six that matter. */}
          {!clean && (
            <ul className="mt-2 space-y-0.5">
              {row.items
                .filter((line) => line.variance !== 0)
                .slice(0, 8)
                .map((line, i) => (
                  <li key={`${line.sku}-${i}`} className="text-sm">
                    <span className="tnum">{line.sku}</span>
                    <span className="text-ink-muted"> {line.product_name}</span>
                    <span className="text-ink-subtle">
                      {" — system "}
                      <span className="tnum">{count(line.expected)}</span>
                      {", counted "}
                      <span className="tnum">{count(line.actual)}</span>{" "}
                    </span>
                    <span
                      className={cn(
                        "tnum font-medium",
                        line.variance < 0 ? "text-danger" : "text-warning",
                      )}
                    >
                      ({line.variance > 0 ? "+" : ""}
                      {count(line.variance)})
                    </span>
                    {line.reason && (
                      <span className="text-2xs text-ink-subtle"> {line.reason}</span>
                    )}
                  </li>
                ))}
            </ul>
          )}

          <p className="mt-2 text-2xs text-ink-subtle">
            submitted {dateTime(row.created_at)}
          </p>
        </div>

        {decidable && (
          <div className="flex shrink-0 items-center gap-2">
            <Button
              variant="secondary"
              disabled={decide.isPending}
              onClick={() => decide.mutate({ id: row.id, decision: "reject" })}
              icon={<X className="h-3.5 w-3.5" />}
            >
              Reject
            </Button>
            <Button
              disabled={decide.isPending}
              onClick={() => decide.mutate({ id: row.id, decision: "approve" })}
              icon={<Check className="h-4 w-4" />}
            >
              {decide.isPending ? "Applying…" : "Approve count"}
            </Button>
          </div>
        )}
      </div>

      {decidable && (
        <p className="mt-2 text-2xs text-ink-subtle">
          Approving sets stock to the counted figure. Every forecast and stockout
          date on the system is derived from it.
        </p>
      )}

      {decide.isError && (
        <p
          role="alert"
          className="mt-2 rounded-sm border border-danger/25 bg-danger-soft px-2.5 py-1.5 text-xs text-danger"
        >
          {decide.error instanceof Error
            ? decide.error.message
            : "That didn't go through. Stock is unchanged."}
        </p>
      )}
    </div>
  );
}
