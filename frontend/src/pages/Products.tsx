import { Package, Search } from "lucide-react";
import { useState } from "react";

import { PageHeader } from "@/components/layout/AppShell";
import { ProductThumb } from "@/components/ui/ProductThumb";
import { AbcBadge, StatusBadge } from "@/components/ui/Badge";
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
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states";
import { count, currency, percent } from "@/lib/format";
import { useProducts } from "@/lib/queries";
import { useDebounced } from "@/lib/useDebounced";

export function Products() {
  const [search, setSearch] = useState("");
  const [abcFilter, setAbcFilter] = useState<string>("");

  // Filtering runs server-side. A page caps at 100 rows, so filtering the page
  // already in memory would search a truncated catalogue and report confidently
  // wrong counts -- "3 A-class products" when there are 22.
  const products = useProducts({
    search: useDebounced(search) || undefined,
    abc_class: abcFilter || undefined,
  });

  const rows = products.data?.data ?? [];

  const margin = (cost: string, price: string) => {
    const c = Number(cost);
    const p = Number(price);
    return p > 0 ? ((p - c) / p) * 100 : null;
  };

  return (
    <>
      <PageHeader
        title="Products"
        description="Catalogue with revenue classification from the nightly Pareto analysis."
      />

      <Band>
        <BandHeader
          label="Catalogue"
          action={
            <>
              <div className="w-full sm:w-56">
                <Input
                  placeholder="Search SKU or name"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  icon={<Search className="h-3.5 w-3.5" />}
                  aria-label="Search products"
                  className="h-8 text-sm"
                />
              </div>

              <div className="flex items-center gap-1">
                {["A", "B", "C"].map((cls) => (
                  <Button
                    key={cls}
                    size="sm"
                    variant={abcFilter === cls ? "primary" : "secondary"}
                    onClick={() => setAbcFilter(abcFilter === cls ? "" : cls)}
                    aria-pressed={abcFilter === cls}
                    className="w-8 px-0 font-mono"
                  >
                    {cls}
                  </Button>
                ))}
              </div>

              <span className="font-mono text-2xs tracking-wider text-ink-subtle uppercase">
                {count(products.data?.total ?? 0)}
                {search || abcFilter ? " matching" : " products"}
              </span>
            </>
          }
        />

        {products.isPending ? (
          <TableSkeleton rows={10} cols={6} />
        ) : products.isError ? (
          <ErrorState
            error={products.error}
            onRetry={() => products.refetch()}
          />
        ) : rows.length === 0 ? (
          <EmptyState
            icon={<Package className="h-5 w-5" />}
            title="No products match"
            description={
              abcFilter
                ? `No ${abcFilter}-class products match your search.`
                : `Nothing matches "${search}".`
            }
            action={
              <Button
                variant="secondary"
                size="sm"
                onClick={() => {
                  setSearch("");
                  setAbcFilter("");
                }}
              >
                Clear filters
              </Button>
            }
          />
        ) : (
          <TableWrap className="max-h-[calc(100vh-17rem)]">
            <Table>
              <THead>
                <TR>
                  <TH>SKU</TH>
                  <TH>Name</TH>
                  <TH>Category</TH>
                  <TH className="w-14">ABC</TH>
                  <TH numeric>Cost</TH>
                  <TH numeric>Price</TH>
                  <TH numeric>Margin</TH>
                  <TH>Status</TH>
                </TR>
              </THead>
              <TBody>
                {rows.map((p) => {
                  const m = margin(p.unit_cost, p.selling_price);
                  return (
                    <TR key={p.id}>
                      <TD className="tnum text-2xs whitespace-nowrap text-ink-subtle">
                        {p.sku}
                      </TD>
                      <TD className="max-w-[20rem] font-medium">
                        {/* Picture and name in one cell rather than two
                            columns. They are one piece of information -- what
                            this product IS -- and splitting them puts a
                            column of images between the SKU and the thing it
                            identifies. */}
                        <div className="flex items-center gap-2.5">
                          <ProductThumb src={p.image_url} name={p.name} />
                          <span className="min-w-0 truncate">{p.name}</span>
                        </div>
                      </TD>
                      <TD className="text-ink-muted">{p.category ?? "—"}</TD>
                      <TD>
                        <AbcBadge value={p.abc_class} />
                      </TD>
                      <TD numeric className="text-ink-muted">
                        {currency(p.unit_cost)}
                      </TD>
                      <TD numeric>{currency(p.selling_price)}</TD>
                      <TD numeric className="text-ink-muted">
                        {percent(m, 0)}
                      </TD>
                      <TD>
                        {/* Almost everything in a catalogue is active, and a
                            column of two hundred green badges is a column the
                            eye has to filter before it can find the one
                            discontinued line. Only the exception is marked. */}
                        {p.status === "active" ? null : (
                          <StatusBadge value={p.status} />
                        )}
                      </TD>
                    </TR>
                  );
                })}
              </TBody>
            </Table>
          </TableWrap>
        )}
      </Band>
    </>
  );
}
