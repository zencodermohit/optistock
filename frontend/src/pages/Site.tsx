import { AlertTriangle, Boxes, Layers, Maximize2, TrendingUp } from "lucide-react";
import { Suspense, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { SiteScene } from "@/components/site/SiteScene";
import { Badge } from "@/components/ui/Badge";
import { ErrorState } from "@/components/ui/states";
import { count, currency, percent } from "@/lib/format";
import { useOverview, useSite, type SiteWarehouse } from "@/lib/queries";
import { cn } from "@/lib/utils";

/**
 * The landing screen: the company's sites, as places.
 *
 * Everything else in the product is a list of rows about stock. This is the one
 * screen that answers "where is my business, and which building needs me
 * today" before you have read a single number — the tallest building holds the
 * most, the violet band up its face is how full it is, and a red marker only
 * appears above a site with stock actually at zero.
 *
 * The KPI strip below it never leaves. It is the one piece of the interface
 * that is true regardless of which screen you are on, so it sits outside the
 * scene rather than inside it.
 */
export function Site() {
  const site = useSite();
  const overview = useOverview(30);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const warehouses = useMemo(() => site.data?.data ?? [], [site.data]);

  // Select the site that most needs attention, not the first alphabetically.
  // On login the useful default is "the one with a problem".
  useEffect(() => {
    if (selectedId || warehouses.length === 0) return;
    const worst = [...warehouses].sort(
      (a, b) => b.out_lines - a.out_lines || b.open_alerts - a.open_alerts,
    )[0];
    setSelectedId(worst.id);
  }, [warehouses, selectedId]);

  const selected = warehouses.find((w) => w.id === selectedId) ?? null;

  const totals = useMemo(() => {
    const units = warehouses.reduce((n, w) => n + w.units_held, 0);
    const capacity = warehouses.reduce((n, w) => n + w.capacity_units, 0);
    return {
      units,
      capacity,
      lines: warehouses.reduce((n, w) => n + w.stock_lines, 0),
      out: warehouses.reduce((n, w) => n + w.out_lines, 0),
      low: warehouses.reduce((n, w) => n + w.low_lines, 0),
      utilisation: capacity > 0 ? units / capacity : null,
    };
  }, [warehouses]);

  if (site.isError) {
    return <ErrorState error={site.error} onRetry={() => void site.refetch()} />;
  }

  return (
    <div className="flex flex-col gap-4">
      {/* ---------------- Site switcher ---------------- */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="eyebrow mr-1">Sites</span>
        {warehouses.map((warehouse) => (
          <SiteChip
            key={warehouse.id}
            warehouse={warehouse}
            active={warehouse.id === selectedId}
            onClick={() => setSelectedId(warehouse.id)}
          />
        ))}
        {site.isLoading && (
          <span className="text-2xs text-ink-subtle">Loading sites…</span>
        )}
      </div>

      {/* ---------------- The scene ---------------- */}
      <div className="relative overflow-hidden rounded-2xl border border-border bg-canvas shadow-md">
        <div className="h-[clamp(20rem,58vh,36rem)] w-full">
          {warehouses.length > 0 ? (
            <Suspense
              fallback={
                <div className="flex h-full items-center justify-center text-sm text-ink-subtle">
                  Building the site…
                </div>
              }
            >
              <SiteScene
                warehouses={warehouses}
                selectedId={selectedId}
                onSelect={setSelectedId}
              />
            </Suspense>
          ) : (
            <div className="flex h-full items-center justify-center text-sm text-ink-subtle">
              {site.isLoading ? "Building the site…" : "No warehouses yet."}
            </div>
          )}
        </div>

        {/* Legend. The scene encodes three things and says so, because a
            visualisation whose rules you have to guess is decoration. */}
        <div className="pointer-events-none absolute top-3 left-3 flex flex-col gap-1.5 rounded-xl border border-border bg-surface/85 px-3 py-2.5 backdrop-blur-sm">
          <p className="eyebrow">Reading the site</p>
          <Key swatch="bg-ink-subtle" label="Building size = capacity" />
          <Key swatch="bg-capacity" label="Violet band = how full" />
          <Key swatch="bg-danger" label="Marker = stock at zero" />
        </div>

        <p className="pointer-events-none absolute right-3 bottom-3 flex items-center gap-1.5 text-2xs text-ink-subtle">
          <Maximize2 className="h-3 w-3" />
          Drag to orbit · scroll to zoom · click a building
        </p>
      </div>

      {/* ---------------- Selected site detail ---------------- */}
      {selected && <SelectedSite warehouse={selected} />}

      {/* ---------------- The persistent KPI strip ---------------- */}
      <div className="grid gap-px overflow-hidden rounded-2xl border border-border bg-border shadow-sm sm:grid-cols-2 lg:grid-cols-5">
        <Kpi
          icon={<Boxes className="h-4 w-4" />}
          label="Units on hand"
          value={count(totals.units)}
          note={`across ${count(totals.lines)} stock lines`}
        />
        <Kpi
          icon={<Layers className="h-4 w-4" />}
          label="Capacity used"
          value={totals.utilisation != null ? percent(totals.utilisation * 100, 1) : "—"}
          note={`of ${count(totals.capacity)} units`}
          bar={totals.utilisation ?? undefined}
        />
        <Kpi
          icon={<AlertTriangle className="h-4 w-4" />}
          label="Out of stock"
          value={count(totals.out)}
          note={`${count(totals.low)} more below reorder point`}
          tone={totals.out > 0 ? "danger" : undefined}
        />
        <Kpi
          icon={<TrendingUp className="h-4 w-4" />}
          label="Revenue, 30 days"
          value={
            overview.data ? currency(overview.data.trading.revenue) : "—"
          }
          note={
            overview.data?.trading.revenue_change_pct != null
              ? `${overview.data.trading.revenue_change_pct > 0 ? "+" : ""}${overview.data.trading.revenue_change_pct.toFixed(1)}% on previous`
              : undefined
          }
        />
        <Kpi
          icon={<Boxes className="h-4 w-4" />}
          label="Orders, 30 days"
          value={overview.data ? count(overview.data.trading.orders) : "—"}
          note={
            overview.data
              ? `${count(overview.data.trading.units_sold)} units sold`
              : undefined
          }
        />
      </div>
    </div>
  );
}

function Key({ swatch, label }: { swatch: string; label: string }) {
  return (
    <span className="flex items-center gap-2 text-2xs text-ink-muted">
      <span className={cn("h-2 w-2 rounded-full", swatch)} />
      {label}
    </span>
  );
}

function SiteChip({
  warehouse,
  active,
  onClick,
}: {
  warehouse: SiteWarehouse;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex cursor-pointer items-center gap-2 rounded-full border px-3 py-1.5 text-sm transition-colors",
        active
          ? "border-accent bg-accent text-white"
          : "border-border bg-surface text-ink-muted hover:border-accent-border hover:text-ink",
      )}
    >
      {warehouse.name}
      {warehouse.out_lines > 0 && (
        <span
          className={cn(
            "tnum rounded-full px-1.5 text-2xs font-bold",
            active ? "bg-white/20 text-white" : "bg-danger-soft text-danger",
          )}
        >
          {warehouse.out_lines}
        </span>
      )}
    </button>
  );
}

/** The building you clicked, in numbers. */
function SelectedSite({ warehouse }: { warehouse: SiteWarehouse }) {
  const used = warehouse.utilisation ?? 0;

  return (
    <div className="flex flex-wrap items-center gap-x-8 gap-y-4 rounded-2xl border border-border bg-surface px-5 py-4 shadow-sm">
      <div className="min-w-0">
        <p className="eyebrow">Selected site</p>
        <p className="font-display text-xl font-bold">{warehouse.name}</p>
        <p className="tnum mt-0.5 text-2xs text-ink-subtle">
          {warehouse.location_code}
        </p>
      </div>

      <div className="min-w-[12rem] flex-1">
        <div className="flex items-baseline justify-between">
          <span className="eyebrow">Capacity</span>
          <span className="tnum text-sm font-semibold">
            {count(warehouse.units_held)} / {count(warehouse.capacity_units)}
          </span>
        </div>
        <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-sunken">
          <div
            className="h-full rounded-full bg-capacity transition-[width] duration-500"
            style={{ width: `${Math.max(used * 100, 1)}%` }}
          />
        </div>
      </div>

      <Stat label="Stock lines" value={count(warehouse.stock_lines)} />
      <Stat
        label="Below reorder"
        value={count(warehouse.low_lines)}
        tone={warehouse.low_lines > 0 ? "warning" : undefined}
      />
      <Stat
        label="Out of stock"
        value={count(warehouse.out_lines)}
        tone={warehouse.out_lines > 0 ? "danger" : undefined}
      />

      <div className="flex items-center gap-2">
        {warehouse.open_alerts > 0 && (
          <Badge tone="warning">{warehouse.open_alerts} open alerts</Badge>
        )}
        <Link
          to={`/inventory?warehouse=${warehouse.id}`}
          className="rounded-lg border border-border px-3 py-1.5 text-sm font-semibold text-ink transition-colors hover:border-accent-border hover:text-accent"
        >
          Open stock
        </Link>
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "warning" | "danger";
}) {
  return (
    <div>
      <p className="eyebrow">{label}</p>
      <p
        className={cn(
          "tnum mt-0.5 text-xl font-bold",
          tone === "danger" && "text-danger",
          tone === "warning" && "text-warning",
        )}
      >
        {value}
      </p>
    </div>
  );
}

function Kpi({
  icon,
  label,
  value,
  note,
  tone,
  bar,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  note?: string;
  tone?: "danger";
  bar?: number;
}) {
  return (
    <div className="flex flex-col gap-1.5 bg-surface px-4 py-3.5">
      <span className="flex items-center gap-1.5 text-ink-subtle">
        {icon}
        <span className="eyebrow">{label}</span>
      </span>
      <span
        className={cn(
          "tnum text-3xl leading-none font-extrabold tracking-tight",
          tone === "danger" && "text-danger",
        )}
      >
        {value}
      </span>
      {bar != null && (
        <div className="h-1.5 overflow-hidden rounded-full bg-sunken">
          <div
            className="h-full rounded-full bg-capacity"
            style={{ width: `${Math.max(bar * 100, 1)}%` }}
          />
        </div>
      )}
      {note && <span className="text-2xs text-ink-subtle">{note}</span>}
    </div>
  );
}
