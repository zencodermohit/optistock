import { Check, PackageCheck, Sparkles, Truck } from "lucide-react";
import { useState } from "react";

import { PageHeader } from "@/components/layout/AppShell";
import { Badge } from "@/components/ui/Badge";
import { Band, BandHeader } from "@/components/ui/Band";
import { Button } from "@/components/ui/Button";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/states";
import { count, currency, date } from "@/lib/format";
import {
  usePurchaseOrders,
  useReceiveDelivery,
  type PurchaseOrder,
} from "@/lib/queries";
import { cn } from "@/lib/utils";

/**
 * Purchase orders — what is on order, and the dock where it arrives.
 *
 * Structured as the lifecycle rather than as one sortable table, because the
 * lifecycle is the only thing about an order that changes and it is what the
 * reader came to act on. Not sent / On the way / Received is a real sequence,
 * so using it as the page's structure encodes something true rather than
 * decorating the page with an order it does not have.
 *
 * It deliberately rhymes with Approvals — divided rows inside bands, the same
 * quotation treatment for reasoning — because these two screens are the two
 * ends of one pipeline. A proposal approved over there becomes an order over
 * here, and the visual continuity is what makes that legible.
 *
 * The one loud element is the provenance line. Everything else stays quiet.
 */
export function PurchaseOrders() {
  const orders = usePurchaseOrders();
  /** What the last receipt actually moved. Named, because "Saved" tells a
   *  stock controller nothing about whether their shelves changed. */
  const [receipt, setReceipt] = useState<string | null>(null);

  const all = orders.data?.data ?? [];
  const groups = [
    {
      key: "draft",
      label: "Not sent yet",
      hint: "Approved and costed. Send these to the supplier.",
      rows: all.filter((o) => o.status === "draft"),
    },
    {
      key: "submitted",
      label: "On the way",
      hint: "Placed with the supplier and not yet at the dock.",
      rows: all.filter((o) => o.status === "submitted"),
    },
    {
      key: "delivered",
      label: "Received",
      hint: "Counted into stock. These already moved your inventory.",
      rows: all.filter((o) => o.status === "delivered" || o.status === "cancelled"),
    },
  ];

  const fromAssistant = all.filter((o) => o.origin).length;

  return (
    <>
      <PageHeader
        title="Purchase orders"
        description="What you have on order, where each one came from, and receiving them into stock."
      />

      {receipt && (
        <Band className="mb-4 border-success/30 bg-success-soft p-3">
          <p className="flex items-start gap-2 text-sm text-ink">
            <PackageCheck className="mt-0.5 h-4 w-4 shrink-0 text-success" />
            {receipt}
          </p>
        </Band>
      )}

      {orders.isError ? (
        <ErrorState error={orders.error} onRetry={() => void orders.refetch()} />
      ) : orders.isLoading ? (
        <Band className="p-4">
          <div className="space-y-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-20 w-full" />
            ))}
          </div>
        </Band>
      ) : all.length === 0 ? (
        <Band>
          <EmptyState
            title="No purchase orders yet"
            description="Ask the assistant what needs reordering. Approve its suggestion and the order lands here."
          />
        </Band>
      ) : (
        <>
          {fromAssistant > 0 && (
            <p className="mb-4 text-2xs text-ink-subtle">
              {fromAssistant} of {all.length}{" "}
              {all.length === 1 ? "order" : "orders"} began as an assistant
              proposal a person approved.
            </p>
          )}

          <div className="space-y-4">
            {groups.map((group) =>
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
                    {group.rows.map((order) => (
                      <li key={order.id}>
                        <OrderRow order={order} onReceived={setReceipt} />
                      </li>
                    ))}
                  </ul>
                </Band>
              ),
            )}
          </div>
        </>
      )}
    </>
  );
}

/** Is this order late? The only condition on this page allowed to use warning:
 *  goods that have not arrived when they were due is a stockout risk, which is
 *  what the warning token is reserved for. */
function isOverdue(order: PurchaseOrder): boolean {
  if (order.status === "delivered" || order.status === "cancelled") return false;
  if (!order.expected_delivery_date) return false;
  return new Date(order.expected_delivery_date) < new Date();
}

function OrderRow({
  order,
  onReceived,
}: {
  order: PurchaseOrder;
  onReceived: (message: string) => void;
}) {
  const receive = useReceiveDelivery();
  const [confirming, setConfirming] = useState(false);
  const settled = order.status === "delivered" || order.status === "cancelled";
  const overdue = isOverdue(order);

  function confirmReceipt() {
    receive.mutate(order.id, {
      onSuccess: () => {
        setConfirming(false);
        const line = order.items[0];
        onReceived(
          order.items.length === 1 && line
            ? `Received ${count(line.quantity)} × ${line.sku} into ${order.warehouse_name}. Stock is updated.`
            : `Received ${count(order.units)} units across ${order.items.length} lines into ${order.warehouse_name}. Stock is updated.`,
        );
      },
    });
  }

  return (
    <div className="px-4 py-3.5">
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-display text-base font-semibold">
              {order.supplier_name}
            </span>
            <span className="text-sm text-ink-muted">→ {order.warehouse_name}</span>
            {order.status === "delivered" && <Badge tone="success">received</Badge>}
            {order.status === "cancelled" && <Badge>cancelled</Badge>}
            {overdue && <Badge tone="warning">overdue</Badge>}
          </div>

          {/* Line items read as the order form they are: quantity, what, at what
              price. Mono throughout so the numbers stack down the column. */}
          <ul className="mt-2 space-y-1">
            {order.items.map((line, i) => (
              <li key={`${line.sku}-${i}`} className="text-sm">
                <span className="tnum font-medium">{count(line.quantity)}</span>
                <span className="text-ink-subtle"> × </span>
                <span className="tnum">{line.sku}</span>
                <span className="text-ink-muted"> {line.product_name}</span>
                <span className="tnum text-ink-subtle">
                  {" "}
                  @ {currency(line.unit_price)}
                </span>
              </li>
            ))}
          </ul>

          {order.origin && <Provenance origin={order.origin} />}

          <p className="mt-2 flex flex-wrap items-center gap-x-3 text-2xs text-ink-subtle">
            <span>raised {date(order.created_at)}</span>
            {order.expected_delivery_date && (
              <span className={cn(overdue && "font-medium text-warning")}>
                due {date(order.expected_delivery_date)}
              </span>
            )}
          </p>
        </div>

        <div className="flex shrink-0 flex-col items-end gap-2">
          <span className="tnum text-lg font-semibold">
            {currency(order.total_amount)}
          </span>
          {!settled && !confirming && (
            <Button
              variant="secondary"
              onClick={() => setConfirming(true)}
              icon={<Truck className="h-3.5 w-3.5" />}
            >
              Mark received
            </Button>
          )}
        </div>
      </div>

      {confirming && (
        /* A confirm step rather than a straight button, because this is the one
           action in the app that moves physical stock: it increments inventory
           inside the same transaction and there is no undo. Inline rather than a
           modal — nothing on this page floats above the paper, and the sentence
           the reader needs is the consequence, which fits here beside it. */
        <div className="mt-3 rounded-md border border-border bg-sunken px-3 py-2.5">
          <p className="text-sm">
            This adds{" "}
            <span className="tnum font-semibold">{count(order.units)} units</span>{" "}
            to <span className="font-medium">{order.warehouse_name}</span> and
            cannot be undone.
          </p>
          <div className="mt-2.5 flex flex-wrap items-center gap-2">
            <Button
              onClick={confirmReceipt}
              disabled={receive.isPending}
              icon={<Check className="h-4 w-4" />}
            >
              {receive.isPending ? "Receiving…" : "Confirm receipt"}
            </Button>
            <Button
              variant="ghost"
              onClick={() => setConfirming(false)}
              disabled={receive.isPending}
            >
              Cancel
            </Button>
          </div>
          {receive.isError && (
            <p
              role="alert"
              className="mt-2 rounded-sm border border-danger/25 bg-danger-soft px-2.5 py-1.5 text-xs text-danger"
            >
              {receive.error instanceof Error
                ? receive.error.message
                : "That didn't go through. Nothing was received."}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * The signature element: where this order came from.
 *
 * Most inventory systems record who typed an order in. This one can say that an
 * order began as a machine's suggestion, and — when the two differ — show what
 * the model asked for against what a person actually signed. That gap is the
 * whole human-in-the-loop design made visible at the last step; without it an
 * approved suggestion becomes an anonymous purchase order and the story ends in
 * a shrug.
 *
 * Ink blue, not green or amber: this is information about the record, not a
 * judgement on the stock, and the warning hues are reserved.
 */
function Provenance({
  origin,
}: {
  origin: NonNullable<PurchaseOrder["origin"]>;
}) {
  return (
    <div className="mt-2.5 border-l-2 border-accent-border pl-2.5">
      <p className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
        <span className="inline-flex items-center gap-1 text-2xs font-medium tracking-wide text-accent uppercase">
          <Sparkles className="h-3 w-3" />
          Assistant proposal
        </span>
        {origin.model && (
          <span className="font-mono text-2xs text-ink-subtle">{origin.model}</span>
        )}
      </p>

      {origin.amended &&
      origin.proposed_quantity != null &&
      origin.executed_quantity != null ? (
        <p className="mt-1 text-sm text-ink-muted">
          Asked for{" "}
          <span className="tnum text-ink-subtle line-through">
            {count(origin.proposed_quantity)}
          </span>
          {"; approved at "}
          <span className="tnum font-semibold text-ink">
            {count(origin.executed_quantity)}
          </span>
          .
        </p>
      ) : (
        <p className="mt-1 text-sm text-ink-muted">Approved as suggested.</p>
      )}

      {origin.rationale && (
        <p className="mt-1 text-sm text-ink-muted italic">“{origin.rationale}”</p>
      )}
    </div>
  );
}
