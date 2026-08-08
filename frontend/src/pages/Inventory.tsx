import { Boxes, Search } from "lucide-react";
import { useState } from "react";

import { PageHeader } from "@/components/layout/AppShell";
import { AbcBadge, StockMark } from "@/components/ui/Badge";
import { Band, BandHeader } from "@/components/ui/Band";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import {
  Table,
  TableWrap,
  TBody,
  TD,
  TH,
  THead,
  TR,
} from "@/components/ui/Table";
import { Trace } from "@/components/ui/Trace";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states";
import { count } from "@/lib/format";
import { useInventory, useInventoryTraces, useWarehouses } from "@/lib/queries";
import { useDebounced } from "@/lib/useDebounced";
import { cn } from "@/lib/utils";

export function Inventory() {
  const [search, setSearch] = useState("");
  const [warehouseId, setWarehouseId] = useState<string>("");
  const [lowOnly, setLowOnly] = useState(false);

  const warehouses = useWarehouses();
  const inventory = useInventory({
    search: useDebounced(search) || undefined,
    warehouse_id: warehouseId || undefined,
    low_only: lowOnly,
  });
  const traces = useInventoryTraces(30);
  // Asks only for the total, not the rows. `limit: 1` because the count comes
  // back in the envelope and the page never renders this query's data.
  const lowCount = useInventory({ low_only: true, limit: 1 });

  const rows = inventory.data?.data ?? [];
  const filtered = Boolean(search || warehouseId || lowOnly);

  return (
    <>
      <PageHeader
        title="Inventory"
        description="Every stock line with its last 30 days of movement, ordered by SKU."
      />

      <Band>
        <BandHeader
          label="Stock on hand"
          action={
            <>
              <div className="w-full sm:w-56">
                <Input
                  placeholder="Search SKU or product"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  icon={<Search className="h-3.5 w-3.5" />}
                  aria-label="Search inventory"
                  className="h-8 text-sm"
                />
              </div>

              <select
                value={warehouseId}
                onChange={(e) => setWarehouseId(e.target.value)}
                aria-label="Filter by warehouse"
                className="h-8 rounded-md border border-border-strong bg-surface px-2 text-sm text-ink"
              >
                <option value="">All warehouses</option>
                {warehouses.data?.data.map((w) => (
                  <option key={w.id} value={w.id}>
                    {w.name}
                  </option>
                ))}
              </select>

              {/* Reports and filters in one control: the count is the reason
                  you would press it. */}
              <Button
                variant={lowOnly ? "primary" : "secondary"}
                size="sm"
                onClick={() => setLowOnly((v) => !v)}
                aria-pressed={lowOnly}
              >
                Below reorder point
                {lowCount.data && (
                  <span className="tnum text-2xs opacity-70">
                    {count(lowCount.data.total)}
                  </span>
                )}
              </Button>

              {inventory.data && (
                <span className="font-mono text-2xs tracking-wider text-ink-subtle uppercase">
                  {count(inventory.data.total)} {filtered ? "matching" : "lines"}
                </span>
              )}
            </>
          }
        />

        {inventory.isPending ? (
          <TableSkeleton rows={12} cols={7} />
        ) : inventory.isError ? (
          <ErrorState error={inventory.error} onRetry={() => inventory.refetch()} />
        ) : rows.length === 0 ? (
          <EmptyState
            icon={<Boxes className="h-5 w-5" />}
            title={lowOnly ? "Nothing is running low" : "No stock lines found"}
            description={
              lowOnly
                ? "Every line is above its reorder point right now."
                : search
                  ? `Nothing matches "${search}". Try a different SKU or name.`
                  : "Stock appears here once products are received into a warehouse."
            }
            action={
              filtered && (
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => {
                    setSearch("");
                    setWarehouseId("");
                    setLowOnly(false);
                  }}
                >
                  Clear filters
                </Button>
              )
            }
          />
        ) : (
          <TableWrap className="max-h-[calc(100vh-17rem)]">
            <Table>
              <THead>
                <TR>
                  <TH>SKU</TH>
                  <TH>Product</TH>
                  <TH className="w-10">ABC</TH>
                  <TH>Warehouse</TH>
                  <TH className="w-20">30 days</TH>
                  <TH numeric>On hand</TH>
                  <TH numeric>Reorder at</TH>
                  <TH className="w-14" />
                </TR>
              </THead>
              <TBody>
                {rows.map((row) => (
                  <TR key={row.id}>
                    <TD className="tnum text-2xs whitespace-nowrap text-ink-subtle">
                      {row.sku}
                    </TD>
                    <TD className="max-w-[16rem] truncate font-medium">
                      {row.product_name}
                    </TD>
                    <TD>
                      <AbcBadge value={row.abc_class} />
                    </TD>
                    <TD className="text-xs text-ink-muted">{row.warehouse_name}</TD>
                    <TD>
                      <Trace
                        points={traces.data?.traces[row.id]}
                        reorderPoint={row.reorder_point}
                        low={row.is_low}
                        label={`${row.product_name}: ${count(row.quantity)} on hand, 30-day movement`}
                      />
                    </TD>
                    <TD numeric>
                      <span
                        className={cn(
                          "font-medium",
                          row.quantity === 0 && "text-danger",
                          row.is_low && row.quantity > 0 && "text-warning",
                        )}
                      >
                        {count(row.quantity)}
                      </span>
                    </TD>
                    <TD numeric className="text-ink-subtle">
                      {row.reorder_point > 0 ? count(row.reorder_point) : "—"}
                    </TD>
                    <TD>
                      <StockMark
                        quantity={row.quantity}
                        reorderPoint={row.reorder_point}
                      />
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
