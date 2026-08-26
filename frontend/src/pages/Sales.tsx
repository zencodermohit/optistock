import { ChevronDown, ChevronRight, ShoppingCart } from "lucide-react";
import { Fragment, useState } from "react";

import { PageHeader } from "@/components/layout/AppShell";
import { Badge } from "@/components/ui/Badge";
import { Band, BandHeader } from "@/components/ui/Band";
import { Table, TableWrap, TD, TH, THead, TR } from "@/components/ui/Table";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states";
import { count, currency, date } from "@/lib/format";
import { useSaleDetail, useSalesLedger, type SaleRow } from "@/lib/queries";
import { cn } from "@/lib/utils";

/**
 * Sales — the demand ledger.
 *
 * Not a revenue report; Overview already answers "how are we trading". This
 * page answers "what went out, to whom, from where", because these rows are the
 * raw material for everything downstream: the velocity on Stockout risk and the
 * demand forecast are both computed from exactly this table.
 *
 * It is also the first screen in the product with enough rows to need the
 * greenbar stripe for what greenbar was for — following one row across a wide
 * sheet. Purchase orders came in twos and read better as documents; sales come
 * in hundreds and read as a ledger.
 *
 * The day band is the signature. A printed ledger broke at the day and carried
 * that day's totals, and the same break here makes the rhythm of demand legible
 * — a quiet Tuesday and a heavy Friday are visible without a chart, and the
 * subtotal is the number a person would otherwise reach for a calculator to
 * get.
 */
export function Sales() {
  const [statusFilter, setStatusFilter] = useState<string>("");
  const ledger = useSalesLedger({ status: statusFilter || undefined });
  const [openRow, setOpenRow] = useState<string | null>(null);

  const rows = ledger.data?.data ?? [];
  const summary = ledger.data?.summary;

  // Grouped in the browser because the rows arrive newest-first already; the
  // server would have to send the same data in a shape only this page wants.
  const days: { day: string; rows: SaleRow[] }[] = [];
  for (const row of rows) {
    const day = row.created_at.slice(0, 10);
    const last = days[days.length - 1];
    if (last && last.day === day) last.rows.push(row);
    else days.push({ day, rows: [row] });
  }

  return (
    <>
      <PageHeader
        title="Sales"
        description="Every order that left a warehouse. These are the rows the demand forecast and stockout predictions are built from."
      />

      <Band>
        <BandHeader
          label="Demand ledger"
          description={
            summary
              ? `${count(summary.orders)} orders · ${count(summary.units)} units · ${currency(summary.revenue)} on this page`
              : undefined
          }
          action={
            <div className="flex flex-wrap gap-1">
              {[
                { value: "", label: "All" },
                { value: "completed", label: "Completed" },
                { value: "pending", label: "Pending" },
              ].map((option) => (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => setStatusFilter(option.value)}
                  className={cn(
                    "rounded-sm border px-2 py-0.5 font-mono text-2xs uppercase transition-colors",
                    statusFilter === option.value
                      ? "border-accent bg-accent text-on-accent"
                      : "border-border bg-surface text-ink-muted hover:border-accent-border",
                  )}
                >
                  {option.label}
                </button>
              ))}
            </div>
          }
        />

        {ledger.isError ? (
          <ErrorState error={ledger.error} onRetry={() => void ledger.refetch()} />
        ) : ledger.isLoading ? (
          <TableSkeleton rows={10} cols={6} />
        ) : rows.length === 0 ? (
          <EmptyState
            icon={<ShoppingCart className="h-5 w-5" />}
            title="No sales recorded"
            description={
              statusFilter
                ? "Nothing with that status. Try another filter."
                : "Sales appear here as they are recorded, newest first."
            }
          />
        ) : (
          <TableWrap className="max-h-[70vh]">
            <Table>
              <THead>
                <TR>
                  <TH className="w-8" />
                  <TH>Customer</TH>
                  <TH>From</TH>
                  <TH>Status</TH>
                  <TH numeric>Lines</TH>
                  <TH numeric>Units</TH>
                  <TH numeric>Total</TH>
                </TR>
              </THead>

              {days.map(({ day, rows: dayRows }) => (
                /* One tbody per day, so the band restarts with each day rather
                   than striping straight through the break. */
                <tbody key={day} className="zebra">
                  <tr className="border-y border-border bg-sunken">
                    <td colSpan={7} className="px-3 py-1.5">
                      <span className="flex flex-wrap items-baseline gap-x-3">
                        <span className="font-display text-sm font-semibold">
                          {date(day)}
                        </span>
                        <span className="tnum text-2xs text-ink-muted">
                          {count(dayRows.length)}{" "}
                          {dayRows.length === 1 ? "order" : "orders"} ·{" "}
                          {count(dayRows.reduce((n, r) => n + r.units, 0))} units ·{" "}
                          {currency(
                            dayRows.reduce((n, r) => n + r.total_amount, 0),
                          )}
                        </span>
                      </span>
                    </td>
                  </tr>

                  {dayRows.map((row) => (
                    <Fragment key={row.id}>
                      <TR
                        className="cursor-pointer hover:bg-accent-soft/50"
                        onClick={() => setOpenRow(openRow === row.id ? null : row.id)}
                      >
                        <TD className="pl-3 text-ink-subtle">
                          {openRow === row.id ? (
                            <ChevronDown className="h-3.5 w-3.5" />
                          ) : (
                            <ChevronRight className="h-3.5 w-3.5" />
                          )}
                        </TD>
                        <TD className="font-medium">{row.customer_name}</TD>
                        <TD className="text-ink-muted">{row.warehouse_name}</TD>
                        <TD>
                          {row.status === "completed" ? (
                            <span className="text-2xs text-ink-subtle">completed</span>
                          ) : (
                            <Badge tone="outline">{row.status}</Badge>
                          )}
                        </TD>
                        <TD numeric className="text-ink-muted">
                          {count(row.lines)}
                        </TD>
                        <TD numeric>{count(row.units)}</TD>
                        <TD numeric className="font-medium">
                          {currency(row.total_amount)}
                        </TD>
                      </TR>
                      {openRow === row.id && (
                        <tr>
                          <td colSpan={7} className="bg-surface px-3 pb-3">
                            <SaleLines id={row.id} />
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  ))}
                </tbody>
              ))}
            </Table>
          </TableWrap>
        )}
      </Band>
    </>
  );
}

/**
 * The line items behind one sale, fetched on open.
 *
 * Product names are not on this endpoint, so the SKU-level detail is what the
 * sale itself recorded: quantity and the price it actually sold at, which is
 * the pair that matters — a product's list price today does not tell you what
 * this order was worth.
 */
function SaleLines({ id }: { id: string }) {
  const detail = useSaleDetail(id);

  if (detail.isLoading) {
    return <p className="py-2 text-2xs text-ink-subtle">Loading lines…</p>;
  }
  if (detail.isError || !detail.data) {
    return (
      <p className="py-2 text-2xs text-danger">
        Couldn't load the lines for this sale.
      </p>
    );
  }

  return (
    <div className="border-l-2 border-accent-border py-1 pl-3">
      <p className="eyebrow mb-1">Lines</p>
      <ul className="space-y-0.5">
        {detail.data.items.map((line) => (
          <li key={line.id} className="text-sm">
            <span className="tnum font-medium">{count(line.quantity)}</span>
            <span className="text-ink-subtle"> × </span>
            <span className="tnum text-ink-muted">
              {currency(line.unit_price)} each
            </span>
            <span className="text-ink-subtle"> = </span>
            <span className="tnum">
              {currency(line.quantity * line.unit_price)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
