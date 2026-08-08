import { Boxes, Search } from "lucide-react";
import { useState } from "react";

import { PageHeader } from "@/components/layout/AppShell";
import { AbcBadge, Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
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
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states";
import { count, date } from "@/lib/format";
import { useInventory, useWarehouses } from "@/lib/queries";
import { cn } from "@/lib/utils";

export function Inventory() {
  const [search, setSearch] = useState("");
  const [warehouseId, setWarehouseId] = useState<string>("");
  const [lowOnly, setLowOnly] = useState(false);

  const warehouses = useWarehouses();
  const inventory = useInventory({
    search: search || undefined,
    warehouse_id: warehouseId || undefined,
    low_only: lowOnly,
  });

  const rows = inventory.data?.data ?? [];

  return (
    <>
      <PageHeader
        title="Inventory"
        description="Live stock across every warehouse, lowest first."
      />

      <Card>
        {/* Filter bar */}
        <div className="flex flex-wrap items-center gap-3 border-b border-border px-5 py-3">
          <div className="w-full sm:w-64">
            <Input
              placeholder="Search SKU or product"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              icon={<Search className="h-4 w-4" />}
              aria-label="Search inventory"
            />
          </div>

          <select
            value={warehouseId}
            onChange={(e) => setWarehouseId(e.target.value)}
            aria-label="Filter by warehouse"
            className="h-9 rounded-md border border-border-strong bg-surface px-3 text-base text-ink"
          >
            <option value="">All warehouses</option>
            {warehouses.data?.data.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name}
              </option>
            ))}
          </select>

          <Button
            variant={lowOnly ? "primary" : "secondary"}
            size="sm"
            onClick={() => setLowOnly((v) => !v)}
            aria-pressed={lowOnly}
          >
            Below reorder point
          </Button>

          {inventory.data && (
            <span className="ml-auto text-xs text-ink-muted">
              <span className="tnum">{count(inventory.data.total)}</span> lines
            </span>
          )}
        </div>

        {inventory.isPending ? (
          <TableSkeleton rows={10} cols={6} />
        ) : inventory.isError ? (
          <ErrorState error={inventory.error} onRetry={() => inventory.refetch()} />
        ) : rows.length === 0 ? (
          <EmptyState
            icon={<Boxes className="h-5 w-5" />}
            title={lowOnly ? "Nothing is running low" : "No stock lines found"}
            description={
              lowOnly
                ? "Every product is above its reorder point right now."
                : search
                  ? `Nothing matches "${search}". Try a different SKU or name.`
                  : "Stock appears once products are received into a warehouse."
            }
            action={
              (search || lowOnly) && (
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => {
                    setSearch("");
                    setLowOnly(false);
                  }}
                >
                  Clear filters
                </Button>
              )
            }
          />
        ) : (
          <TableWrap className="max-h-[calc(100vh-19rem)]">
            <Table>
              <THead>
                <TR className="hover:bg-transparent">
                  <TH>SKU</TH>
                  <TH>Product</TH>
                  <TH className="w-14">ABC</TH>
                  <TH>Warehouse</TH>
                  <TH numeric>On hand</TH>
                  <TH numeric>Reorder at</TH>
                  <TH>Last counted</TH>
                </TR>
              </THead>
              <TBody>
                {rows.map((row) => (
                  <TR key={row.id}>
                    <TD className="tnum text-xs text-ink-muted">{row.sku}</TD>
                    <TD className="font-medium">{row.product_name}</TD>
                    <TD>
                      <AbcBadge value={row.abc_class} />
                    </TD>
                    <TD className="text-ink-muted">{row.warehouse_name}</TD>
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
                      {row.is_low && (
                        <Badge
                          tone={row.quantity === 0 ? "danger" : "warning"}
                          className="ml-2"
                        >
                          {row.quantity === 0 ? "out" : "low"}
                        </Badge>
                      )}
                    </TD>
                    <TD numeric className="text-ink-subtle">
                      {row.reorder_point > 0 ? count(row.reorder_point) : "—"}
                    </TD>
                    <TD className="text-xs text-ink-subtle">
                      {date(row.last_counted_at)}
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          </TableWrap>
        )}
      </Card>
    </>
  );
}
