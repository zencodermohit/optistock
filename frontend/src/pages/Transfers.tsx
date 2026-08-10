import { ArrowRight, Check, Send, Truck } from "lucide-react";

import { PageHeader } from "@/components/layout/AppShell";
import { Badge } from "@/components/ui/Badge";
import { Band, BandHeader } from "@/components/ui/Band";
import { Button } from "@/components/ui/Button";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/states";
import { count, dateTime } from "@/lib/format";
import { useTransferAction, useTransfers, type TransferRow } from "@/lib/queries";

/**
 * Transfers — stock moving between your own warehouses.
 *
 * The one movement that is neither a purchase nor a sale. Stock leaves one
 * shelf and lands on another, and in between it belongs to neither: it has left
 * the source and not arrived at the destination. That gap is the reason this
 * screen exists, so it is drawn rather than collapsed into a status word — the
 * route reads left to right, and the state of the journey is where the marker
 * sits along it.
 *
 * Two actions, two very different weights. Shipping records a departure.
 * Completing lands the stock and changes what every other screen believes, so
 * only that one takes a confirmation.
 */
export function Transfers() {
  const transfers = useTransfers();
  const rows = transfers.data?.data ?? [];

  const inFlight = rows.filter((row) => row.status === "in_transit" || row.status === "shipped");
  const pending = rows.filter((row) => row.status === "pending");
  const done = rows.filter(
    (row) => !["pending", "in_transit", "shipped"].includes(row.status),
  );

  return (
    <>
      <PageHeader
        title="Transfers"
        description="Stock moving between your warehouses. Nothing counts as arrived until somebody says it did."
      />

      {transfers.isError ? (
        <ErrorState error={transfers.error} onRetry={() => void transfers.refetch()} />
      ) : transfers.isLoading ? (
        <Band className="space-y-3 p-4">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-20 w-full" />
          ))}
        </Band>
      ) : rows.length === 0 ? (
        <Band>
          <EmptyState
            icon={<Truck className="h-5 w-5" />}
            title="No transfers"
            description="Move stock between warehouses and the journey shows up here."
          />
        </Band>
      ) : (
        <div className="space-y-4">
          {[
            { key: "flight", label: "In transit", hint: "Left the source, not yet counted in.", rows: inFlight },
            { key: "pending", label: "Not shipped", hint: "Raised, still sitting at the source.", rows: pending },
            { key: "done", label: "Completed", hint: "Counted into the destination.", rows: done },
          ].map((group) =>
            group.rows.length === 0 ? null : (
              <Band key={group.key}>
                <BandHeader
                  label={group.label}
                  description={group.hint}
                  action={
                    <span className="tnum text-2xs text-ink-subtle">
                      {group.rows.length}
                    </span>
                  }
                />
                <ul className="divide-y divide-border">
                  {group.rows.map((row) => (
                    <li key={row.id}>
                      <TransferCard row={row} />
                    </li>
                  ))}
                </ul>
              </Band>
            ),
          )}
        </div>
      )}
    </>
  );
}

function TransferCard({ row }: { row: TransferRow }) {
  const act = useTransferAction();
  const shipped = Boolean(row.shipped_at);
  const received = Boolean(row.received_at);

  return (
    <div className="px-4 py-3.5">
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-3">
        <div className="min-w-0">
          {/* The route, read left to right. Two named ends and the line between
              them is the clearest possible picture of "where is it". */}
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-display text-base font-semibold">
              {row.source_name}
            </span>
            <ArrowRight className="h-3.5 w-3.5 text-ink-subtle" />
            <span className="font-display text-base font-semibold">
              {row.destination_name}
            </span>
            {received && <Badge tone="success">arrived</Badge>}
            {shipped && !received && <Badge tone="outline">in transit</Badge>}
          </div>

          <ul className="mt-2 space-y-1">
            {row.items.map((item, i) => (
              <li key={`${item.sku}-${i}`} className="text-sm">
                <span className="tnum font-medium">{count(item.quantity)}</span>
                <span className="text-ink-subtle"> × </span>
                <span className="tnum">{item.sku}</span>
                <span className="text-ink-muted"> {item.product_name}</span>
              </li>
            ))}
          </ul>

          <p className="mt-2 flex flex-wrap items-center gap-x-3 text-2xs text-ink-subtle">
            <span>raised {dateTime(row.created_at)}</span>
            {row.shipped_at && <span>shipped {dateTime(row.shipped_at)}</span>}
            {row.received_at && <span>received {dateTime(row.received_at)}</span>}
          </p>
        </div>

        <div className="flex shrink-0 flex-col items-end gap-2">
          <span className="tnum text-lg font-semibold">
            {count(row.units)}
            <span className="ml-1 text-2xs font-normal text-ink-subtle">units</span>
          </span>

          {!shipped && (
            <Button
              variant="secondary"
              disabled={act.isPending}
              onClick={() => act.mutate({ id: row.id, action: "ship" })}
              icon={<Send className="h-3.5 w-3.5" />}
            >
              {act.isPending ? "Shipping…" : "Mark shipped"}
            </Button>
          )}
          {shipped && !received && (
            <Button
              disabled={act.isPending}
              onClick={() => act.mutate({ id: row.id, action: "complete" })}
              icon={<Check className="h-4 w-4" />}
            >
              {act.isPending ? "Receiving…" : "Confirm arrival"}
            </Button>
          )}
        </div>
      </div>

      {act.isError && (
        <p
          role="alert"
          className="mt-2 rounded-sm border border-danger/25 bg-danger-soft px-2.5 py-1.5 text-xs text-danger"
        >
          {act.error instanceof Error ? act.error.message : "That didn't go through."}
        </p>
      )}
    </div>
  );
}
