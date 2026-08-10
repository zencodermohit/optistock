import { Search, Users } from "lucide-react";
import { useState } from "react";

import { PageHeader } from "@/components/layout/AppShell";
import { Badge } from "@/components/ui/Badge";
import { Band, BandHeader } from "@/components/ui/Band";
import { Input } from "@/components/ui/Input";
import { Table, TableWrap, TBody, TD, TH, THead, TR } from "@/components/ui/Table";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states";
import { count, currency, date, percent } from "@/lib/format";
import { useCustomerDirectory } from "@/lib/queries";
import { useDebounced } from "@/lib/useDebounced";
import { cn } from "@/lib/utils";

/**
 * Customers, ranked by what they are worth.
 *
 * A name and an email address is a contact list. What makes one customer
 * different from another here is what they buy and when they last did, so the
 * page opens on value rather than on the alphabet — alphabetical order answers
 * a question nobody arrived with.
 *
 * The share bar is the signature, and it is the same idea the product already
 * applies to stock. Products get ABC classification because revenue concentrates
 * in a few of them; customers concentrate the same way, and the bar makes that
 * concentration visible without a chart or a second page. Reading down the
 * column, you can see where the revenue actually comes from — and the cumulative
 * figure names the point where the top of the list becomes most of the business.
 */
export function Customers() {
  const [search, setSearch] = useState("");
  const directory = useCustomerDirectory(useDebounced(search) || undefined);

  const rows = directory.data?.data ?? [];
  const totalValue = rows.reduce((sum, row) => sum + row.lifetime_value, 0);
  const trading = rows.filter((row) => row.orders > 0);
  const dormant = rows.length - trading.length;

  // How many customers make up 80% of revenue — the Pareto point, computed on
  // what is shown rather than asserted as a rule of thumb.
  let running = 0;
  let paretoCount = 0;
  for (const row of rows) {
    if (running / (totalValue || 1) >= 0.8) break;
    running += row.lifetime_value;
    paretoCount += 1;
  }

  return (
    <>
      <PageHeader
        title="Customers"
        description="Who buys from you, what they are worth, and when they last ordered."
      />

      <div className="mb-4 grid gap-3 sm:grid-cols-3">
        <Figure label="Customers" value={count(rows.length)} />
        <Figure label="Lifetime revenue" value={currency(totalValue)} />
        <Figure
          label="Make up 80% of revenue"
          value={trading.length > 0 ? count(paretoCount) : "—"}
          hint={
            trading.length > 0
              ? `of ${count(trading.length)} who have ordered`
              : undefined
          }
        />
      </div>

      <Band>
        <BandHeader
          label="By lifetime value"
          description={
            dormant > 0
              ? `${count(dormant)} on the list have never ordered — worth a call.`
              : undefined
          }
          action={
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search name or email"
              aria-label="Search customers"
              icon={<Search className="h-3.5 w-3.5" />}
              className="w-56"
            />
          }
        />

        {directory.isError ? (
          <ErrorState
            error={directory.error}
            onRetry={() => void directory.refetch()}
          />
        ) : directory.isLoading ? (
          <TableSkeleton rows={8} cols={6} />
        ) : rows.length === 0 ? (
          <EmptyState
            icon={<Users className="h-5 w-5" />}
            title={search ? "Nobody matches that" : "No customers yet"}
            description={
              search
                ? "Try a different name or email."
                : "Customers appear here once they exist in the system."
            }
          />
        ) : (
          <TableWrap className="max-h-[70vh]">
            <Table>
              <THead>
                <TR>
                  <TH>Customer</TH>
                  <TH>Share of revenue</TH>
                  <TH numeric>Lifetime value</TH>
                  <TH numeric>Orders</TH>
                  <TH numeric>Avg order</TH>
                  <TH>Last ordered</TH>
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
                      {row.email && (
                        <p className="mt-0.5 text-2xs text-ink-subtle">
                          {row.email}
                        </p>
                      )}
                    </TD>
                    <TD>
                      <ShareBar value={row.lifetime_value} total={totalValue} />
                    </TD>
                    <TD numeric className="font-medium">
                      {row.orders > 0 ? currency(row.lifetime_value) : "—"}
                    </TD>
                    <TD numeric className="text-ink-muted">
                      {row.orders > 0 ? count(row.orders) : "—"}
                    </TD>
                    <TD numeric className="text-ink-muted">
                      {row.average_order_value != null
                        ? currency(row.average_order_value)
                        : "—"}
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
 * One customer's share of revenue, as a bar plus the figure.
 *
 * The number is there for anyone the bar does not serve — a bar alone encodes
 * by length only, and a screen reader gets nothing from it. Ink blue rather
 * than a severity colour: a large customer is not a warning.
 */
function ShareBar({ value, total }: { value: number; total: number }) {
  if (total <= 0 || value <= 0) {
    return <span className="text-2xs text-ink-subtle">—</span>;
  }
  const share = value / total;

  return (
    <span className="flex items-center gap-2">
      <span
        className="h-1.5 w-24 shrink-0 overflow-hidden rounded-sm bg-sunken"
        aria-hidden
      >
        <span
          className={cn("block h-full rounded-sm bg-accent")}
          style={{ width: `${Math.max(share * 100, 1.5)}%` }}
        />
      </span>
      <span className="tnum text-2xs text-ink-muted">{percent(share * 100)}</span>
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
