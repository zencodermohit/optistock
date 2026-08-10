import { Factory } from "lucide-react";

import { PageHeader } from "@/components/layout/AppShell";
import { Badge } from "@/components/ui/Badge";
import { Band, BandHeader } from "@/components/ui/Band";
import { Table, TableWrap, TBody, TD, TH, THead, TR } from "@/components/ui/Table";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states";
import { count, currency, date, percent } from "@/lib/format";
import { useSupplierScorecard, type SupplierScore } from "@/lib/queries";
import { cn } from "@/lib/utils";

/**
 * Suppliers, judged by what they actually delivered.
 *
 * `reliability_score` has been on the suppliers table since the schema was
 * written and has never been shown to anyone, which makes it a number nobody
 * could check. This page puts it beside the order history it is supposed to
 * summarise — and where the two disagree, the history is the one to believe.
 *
 * That is the whole point of the layout: the stated score and the counted
 * delivery rate sit in adjacent columns so a gap between them is impossible to
 * miss. A supplier claiming 1.00 while delivering 3 of 8 orders is the row this
 * screen exists to surface.
 */
export function Suppliers() {
  const scorecard = useSupplierScorecard();
  const rows = scorecard.data?.data ?? [];

  const trading = rows.filter((row) => row.orders > 0);
  const spend = rows.reduce((sum, row) => sum + row.spend, 0);
  const unproven = rows.length - trading.length;

  return (
    <>
      <PageHeader
        title="Suppliers"
        description="Who you buy from, what you have spent with them, and whether their record matches their score."
      />

      <div className="mb-4 grid gap-3 sm:grid-cols-3">
        <Figure label="Suppliers" value={count(rows.length)} />
        <Figure label="Total ordered" value={currency(spend)} />
        <Figure
          label="No orders yet"
          value={count(unproven)}
          hint={unproven > 0 ? "unproven, not unreliable" : undefined}
        />
      </div>

      <Band>
        <BandHeader
          label="Scorecard"
          description="Delivery rate is counted from real orders. The score beside it is the one stored on the supplier record."
        />

        {scorecard.isError ? (
          <ErrorState
            error={scorecard.error}
            onRetry={() => void scorecard.refetch()}
          />
        ) : scorecard.isLoading ? (
          <TableSkeleton rows={6} cols={6} />
        ) : rows.length === 0 ? (
          <EmptyState
            icon={<Factory className="h-5 w-5" />}
            title="No suppliers yet"
            description="Add a supplier before the assistant can propose an order — it needs somebody to order from."
          />
        ) : (
          <TableWrap>
            <Table>
              <THead>
                <TR>
                  <TH>Supplier</TH>
                  <TH numeric>Orders</TH>
                  <TH numeric>Delivered</TH>
                  <TH>Delivery rate</TH>
                  <TH numeric>Stated score</TH>
                  <TH numeric>Spend</TH>
                  <TH>Last order</TH>
                </TR>
              </THead>
              <TBody>
                {rows.map((row) => (
                  <TR key={row.id}>
                    <TD>
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-medium">{row.name}</span>
                        {!row.is_active && <Badge>inactive</Badge>}
                      </div>
                      {row.contact_email && (
                        <p className="mt-0.5 text-2xs text-ink-subtle">
                          {row.contact_email}
                        </p>
                      )}
                    </TD>
                    <TD numeric className="text-ink-muted">
                      {row.orders > 0 ? count(row.orders) : "—"}
                    </TD>
                    <TD numeric className="text-ink-muted">
                      {row.orders > 0 ? count(row.delivered) : "—"}
                    </TD>
                    <TD>
                      <DeliveryRate row={row} />
                    </TD>
                    <TD numeric className="text-ink-muted">
                      {row.reliability_score.toFixed(2)}
                    </TD>
                    <TD numeric className="font-medium">
                      {row.spend > 0 ? currency(row.spend) : "—"}
                    </TD>
                    <TD className="text-ink-muted">
                      {row.last_order_at ? (
                        date(row.last_order_at)
                      ) : (
                        <span className="text-2xs text-ink-subtle">never</span>
                      )}
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          </TableWrap>
        )}
      </Band>
    </>
  );
}

/**
 * Measured delivery rate.
 *
 * "No orders yet" is rendered as exactly that, never as 0%. A supplier you have
 * not used is unproven, and showing them a zero would libel them for the crime
 * of being new.
 *
 * Warning is legitimate here: a supplier failing to deliver is the upstream
 * cause of a stockout, which is what that colour is reserved for.
 */
function DeliveryRate({ row }: { row: SupplierScore }) {
  if (row.delivery_rate === null) {
    return <span className="text-2xs text-ink-subtle">no orders yet</span>;
  }
  const pct = row.delivery_rate * 100;
  const poor = row.delivery_rate < 0.6;

  return (
    <span className="flex items-center gap-2">
      <span className="h-1.5 w-16 shrink-0 overflow-hidden rounded-sm bg-sunken" aria-hidden>
        <span
          className={cn(
            "block h-full rounded-sm",
            poor ? "bg-warning" : "bg-success",
          )}
          style={{ width: `${Math.max(pct, 2)}%` }}
        />
      </span>
      <span className={cn("tnum text-2xs", poor ? "text-warning" : "text-ink-muted")}>
        {percent(pct, 0)}
      </span>
    </span>
  );
}

function Figure({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <Band className="p-3">
      <p className="eyebrow">{label}</p>
      <p className="tnum mt-1 text-2xl leading-none font-semibold">{value}</p>
      {hint && <p className="mt-1 text-2xs text-ink-subtle">{hint}</p>}
    </Band>
  );
}
