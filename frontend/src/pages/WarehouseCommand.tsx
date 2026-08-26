import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  ClipboardList,
  PackageX,
  Truck,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { Band } from "@/components/ui/Band";
import { ErrorState } from "@/components/ui/states";
import { count, currencyCompact, percent, relativeTime } from "@/lib/format";
import { useCommandCenter, type Zone } from "@/lib/queries";
import { cn } from "@/lib/utils";

/**
 * Layer 2 — one warehouse, from the inside.
 *
 * The centre of the screen is a floor, not a table. Zones are drawn at their
 * real relative size and filled to their real utilisation, so "Furniture is
 * overloaded" is something you SEE before you read a single figure — which is
 * the only way a page like this earns its place over a filtered list.
 *
 * A zone is red because stock in that category exceeds the space allocated to
 * it, and clicking it lists the actual lines a person would walk to. Nothing on
 * this screen is a status somebody typed in.
 */

const STATE: Record<Zone["state"], { fill: string; text: string; chip: string; label: string }> = {
  ok: {
    fill: "bg-success",
    text: "text-success",
    chip: "bg-success-soft text-success",
    label: "Healthy",
  },
  warning: {
    fill: "bg-warning",
    text: "text-warning",
    chip: "bg-warning-soft text-warning",
    label: "Filling up",
  },
  critical: {
    fill: "bg-danger",
    text: "text-danger",
    chip: "bg-danger-soft text-danger",
    label: "Overloaded",
  },
};

export function WarehouseCommand() {
  const { warehouseId } = useParams();
  const command = useCommandCenter(warehouseId);
  const [selected, setSelected] = useState<string | null>(null);

  const data = command.data;
  const zones = data?.zones ?? [];

  // Open on the zone that most needs somebody, not on the first letter.
  useEffect(() => {
    if (selected || zones.length === 0) return;
    const worst = [...zones].sort(
      (a, b) => (b.utilisation ?? 0) - (a.utilisation ?? 0),
    )[0];
    setSelected(worst.id);
  }, [zones, selected]);

  const zone = zones.find((z) => z.id === selected) ?? null;

  if (command.isError) {
    return <ErrorState error={command.error} onRetry={() => void command.refetch()} />;
  }

  const w = data?.warehouse;
  const ops = data?.operations;

  return (
    <>
      {/* ---------------- Header ---------------- */}
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Link
            to="/inventory"
            className="flex h-9 w-9 items-center justify-center rounded-lg border border-border bg-surface text-ink-muted transition-colors hover:text-accent"
            aria-label="Back to the network"
          >
            <ArrowLeft className="h-4 w-4" />
          </Link>
          <div>
            <h1 className="font-display text-2xl font-extrabold tracking-tight">
              {w?.name ?? "Warehouse"}
            </h1>
            <p className="tnum text-2xs text-ink-subtle">
              {w?.location_code ?? ""}
            </p>
          </div>
          <span className="flex items-center gap-1.5 rounded-full bg-success-soft px-2.5 py-1 text-2xs font-bold text-success">
            <span className="relative flex h-1.5 w-1.5">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-success opacity-60" />
              <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-success" />
            </span>
            Live
          </span>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-[13rem_1fr_21rem]">
        {/* ---------------- Capacity rail ---------------- */}
        <Band className="flex flex-col gap-4 p-4">
          <Stat label="Total capacity" value={w ? count(w.capacity_units) : "—"} unit="units" />
          <div>
            <p className="eyebrow">Utilised</p>
            <p className="tnum mt-0.5 text-2xl font-extrabold">
              {w?.utilisation != null ? percent(w.utilisation * 100, 0) : "—"}
            </p>
            <div className="mt-2 h-2 overflow-hidden rounded-full bg-sunken">
              <div
                className="h-full rounded-full bg-capacity transition-[width] duration-500"
                style={{ width: `${Math.min((w?.utilisation ?? 0) * 100, 100)}%` }}
              />
            </div>
            <p className="tnum mt-1 text-2xs text-ink-subtle">
              {w ? count(w.units_held) : "—"} of {w ? count(w.capacity_units) : "—"}
            </p>
          </div>
          <Stat label="Available" value={w ? count(w.available) : "—"} unit="units free" />
          <Stat
            label="Inventory value"
            value={w ? currencyCompact(w.inventory_value) : "—"}
            unit="at cost"
          />
          <Stat label="Stock lines" value={w ? count(w.stock_lines) : "—"} unit="product × zone" />
        </Band>

        {/* ---------------- The floor ---------------- */}
        <Band className="flex flex-col">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-3">
            <h3 className="font-display text-lg font-bold">Floor plan</h3>
            <div className="flex flex-wrap items-center gap-3">
              {(["ok", "warning", "critical"] as const).map((key) => (
                <span
                  key={key}
                  className="flex items-center gap-1.5 text-2xs text-ink-muted"
                >
                  <span className={cn("h-2 w-2 rounded-full", STATE[key].fill)} />
                  {key === "ok" ? "0–70%" : key === "warning" ? "70–90%" : "90%+"}
                </span>
              ))}
            </div>
          </div>

          <div className="flex-1 bg-gradient-to-b from-sunken/50 to-transparent p-4">
            {command.isLoading ? (
              <div className="grid h-full min-h-[22rem] place-items-center text-sm text-ink-subtle">
                Reading the floor…
              </div>
            ) : zones.length === 0 ? (
              <div className="grid h-full min-h-[22rem] place-items-center text-sm text-ink-muted">
                No zones configured for this warehouse.
              </div>
            ) : (
              <div className="flex h-full min-h-[22rem] items-stretch gap-3">
                {zones.map((z) => (
                  <ZoneBay
                    key={z.id}
                    zone={z}
                    active={z.id === selected}
                    onClick={() => setSelected(z.id)}
                  />
                ))}
              </div>
            )}
          </div>

          <p className="border-t border-border px-4 py-2.5 text-2xs text-ink-subtle">
            Bay width is the zone's share of the floor; the fill is how much of
            that zone is occupied. A line sits in a zone because of what the
            product is.
          </p>
        </Band>

        {/* ---------------- Right rail ---------------- */}
        <div className="flex flex-col gap-4">
          {zone && <ZonePanel zone={zone} onClose={() => setSelected(null)} />}

          <Band className="p-4">
            <h3 className="font-display text-lg font-bold">Operations</h3>
            <ul className="mt-3 flex flex-col gap-2.5">
              <Op
                icon={<Truck className="h-3.5 w-3.5" />}
                label="Inbound transfers"
                value={ops?.inbound_transfers ?? 0}
              />
              <Op
                icon={<Truck className="h-3.5 w-3.5" />}
                label="Outbound transfers"
                value={ops?.outbound_transfers ?? 0}
              />
              <Op
                icon={<ClipboardList className="h-3.5 w-3.5" />}
                label="Counts to review"
                value={ops?.counts_awaiting_review ?? 0}
              />
              <Op
                icon={<AlertTriangle className="h-3.5 w-3.5" />}
                label="Zones over 90%"
                value={ops?.zones_critical ?? 0}
                tone={ops && ops.zones_critical > 0 ? "danger" : undefined}
              />
              <Op
                icon={<PackageX className="h-3.5 w-3.5" />}
                label="Lines below reorder"
                value={ops?.lines_low ?? 0}
                tone={ops && ops.lines_low > 0 ? "warning" : undefined}
              />
            </ul>
          </Band>
        </div>
      </div>

      {/* ---------------- Live feed ---------------- */}
      <LiveFeed feed={data?.feed ?? []} loading={command.isLoading} />
    </>
  );
}

/* -------------------------------------------------------------------------- */

/**
 * One bay on the floor.
 *
 * Width is the zone's share of total capacity, so a big zone looks big. Fill
 * rises from the floor because that is what a full rack looks like, and a bar
 * that grows downward reads as draining rather than filling.
 */
function ZoneBay({
  zone,
  active,
  onClick,
}: {
  zone: Zone;
  active: boolean;
  onClick: () => void;
}) {
  const fill = Math.min(zone.utilisation ?? 0, 1);
  const over = (zone.utilisation ?? 0) > 1;

  return (
    <button
      type="button"
      onClick={onClick}
      style={{ flex: `${Math.max(zone.capacity_units, 1)} 1 0%` }}
      className={cn(
        "group relative flex cursor-pointer flex-col overflow-hidden rounded-xl border-2 transition-all",
        active
          ? "border-accent shadow-md"
          : "border-border hover:border-accent-border hover:shadow-sm",
        "bg-surface focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
      )}
    >
      {/* Fill, rising from the floor of the bay. */}
      <span
        className={cn(
          "absolute right-0 bottom-0 left-0 transition-[height] duration-700",
          STATE[zone.state].fill,
          // 25% turned danger red into pale pink. A bay that says "overloaded"
          // has to look overloaded, and the figure sits on the white part of
          // the bay above the fill, so contrast is not at risk.
          "opacity-40",
        )}
        style={{ height: `${fill * 100}%` }}
        aria-hidden
      />

      <span className="relative flex flex-1 flex-col items-center justify-between p-3">
        <span className="flex flex-col items-center gap-1">
          <span className="rounded-md bg-ink px-2 py-0.5 font-display text-2xs font-extrabold text-ink-inverse">
            {zone.code}
          </span>
          <span className="text-center text-2xs leading-tight font-semibold text-ink-muted">
            {zone.name}
          </span>
        </span>

        <span className="flex flex-col items-center">
          <span
            className={cn(
              "tnum text-2xl leading-none font-extrabold",
              STATE[zone.state].text,
            )}
          >
            {zone.utilisation != null ? Math.round(zone.utilisation * 100) : "—"}
            <span className="text-sm">%</span>
          </span>
          {over && (
            <span className="mt-1 rounded-full bg-danger px-1.5 py-px text-[10px] font-bold text-on-danger">
              over capacity
            </span>
          )}
        </span>

        <span className="tnum text-2xs text-ink-subtle">
          {count(zone.units_held)} / {count(zone.capacity_units)}
        </span>
      </span>
    </button>
  );
}

/* -------------------------------------------------------------------------- */

function ZonePanel({ zone, onClose }: { zone: Zone; onClose: () => void }) {
  return (
    <Band className="flex flex-col">
      <div className="flex items-start justify-between gap-2 border-b border-border px-4 py-3">
        <div>
          <p className="flex items-center gap-2">
            <span className="rounded-md bg-ink px-1.5 py-0.5 font-display text-2xs font-extrabold text-ink-inverse">
              {zone.code}
            </span>
            <span className="font-display text-lg font-bold">{zone.name}</span>
          </p>
          <span
            className={cn(
              "mt-1 inline-block rounded-full px-2 py-0.5 text-2xs font-bold",
              STATE[zone.state].chip,
            )}
          >
            {STATE[zone.state].label}
          </span>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close zone panel"
          className="cursor-pointer text-ink-subtle transition-colors hover:text-ink"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="grid grid-cols-2 gap-x-4 gap-y-3 px-4 py-3">
        <Cell label="Capacity" value={count(zone.capacity_units)} />
        <Cell label="Occupied" value={count(zone.units_held)} />
        <Cell
          label="Available"
          value={zone.available > 0 ? count(zone.available) : "none"}
          tone={zone.available === 0 ? "danger" : undefined}
        />
        <Cell label="Value" value={currencyCompact(zone.inventory_value)} />
        <Cell label="Stock lines" value={count(zone.stock_lines)} />
        <Cell
          label="Open alerts"
          value={count(zone.open_alerts)}
          tone={zone.open_alerts > 0 ? "warning" : undefined}
        />
      </div>

      {zone.attention.length > 0 ? (
        <div className="border-t border-border px-4 py-3">
          <p className="eyebrow">Needs restocking</p>
          <ul className="mt-2 flex flex-col gap-2">
            {zone.attention.map((line) => (
              <li key={line.sku} className="flex items-start justify-between gap-2">
                <span className="min-w-0">
                  <span className="tnum block text-2xs font-semibold">
                    {line.sku}
                  </span>
                  <span className="block truncate text-2xs text-ink-subtle">
                    {line.product_name}
                  </span>
                </span>
                <span
                  className={cn(
                    "tnum shrink-0 rounded-full px-2 py-0.5 text-2xs font-bold",
                    line.state === "out"
                      ? "bg-danger-soft text-danger"
                      : "bg-warning-soft text-warning",
                  )}
                >
                  {line.state === "out" ? "0" : count(line.quantity)}
                  <span className="font-normal opacity-70">
                    /{count(line.reorder_point)}
                  </span>
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="border-t border-border px-4 py-3 text-2xs text-ink-subtle">
          Every line in this zone is above its reorder point.
        </p>
      )}
    </Band>
  );
}

/* -------------------------------------------------------------------------- */

/** Real domain events from the outbox. Every row here actually happened. */
const EVENT_LABEL: Record<string, string> = {
  "stock.moved": "Stock moved",
  "stock.deducted": "Stock picked",
  "stock.received": "Inventory received",
  "stock.depleted": "Stock ran out",
  "sale.completed": "Sale completed",
  "scan.recorded": "Scan recorded",
  "alert.raised": "Alert raised",
};

function LiveFeed({
  feed,
  loading,
}: {
  feed: { sequence: number; type: string; payload: Record<string, unknown>; at: string }[];
  loading: boolean;
}) {
  return (
    <Band className="mt-4 flex flex-col">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <h3 className="flex items-center gap-2 font-display text-lg font-bold">
          <Activity className="h-4 w-4 text-accent" />
          Live operations
        </h3>
        <Link to="/system/events" className="text-2xs font-bold text-accent">
          Open the event stream
        </Link>
      </div>

      {loading ? (
        <p className="px-4 py-6 text-sm text-ink-subtle">Reading the stream…</p>
      ) : feed.length === 0 ? (
        <p className="px-4 py-6 text-sm text-ink-muted">
          Nothing has moved in the last seven days.
        </p>
      ) : (
        <ol className="divide-y divide-border">
          {feed.slice(0, 12).map((event) => (
            <li key={event.sequence} className="flex items-center gap-3 px-4 py-2.5">
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent">
                <Activity className="h-3 w-3" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-semibold">
                  {EVENT_LABEL[event.type] ?? event.type}
                </span>
                <span className="tnum block text-2xs text-ink-subtle">
                  #{event.sequence}
                  {typeof event.payload?.quantity === "number" &&
                    ` · ${count(event.payload.quantity as number)} units`}
                </span>
              </span>
              <span className="tnum shrink-0 text-2xs text-ink-subtle">
                {relativeTime(event.at)}
              </span>
            </li>
          ))}
        </ol>
      )}
    </Band>
  );
}

/* -------------------------------------------------------------------------- */

function Stat({ label, value, unit }: { label: string; value: string; unit?: string }) {
  return (
    <div>
      <p className="eyebrow">{label}</p>
      <p className="tnum mt-0.5 text-xl font-extrabold">{value}</p>
      {unit && <p className="text-2xs text-ink-subtle">{unit}</p>}
    </div>
  );
}

function Cell({
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
          "tnum mt-0.5 text-base font-bold",
          tone === "danger" && "text-danger",
          tone === "warning" && "text-warning",
        )}
      >
        {value}
      </p>
    </div>
  );
}

function Op({
  icon,
  label,
  value,
  tone,
}: {
  icon: React.ReactNode;
  label: string;
  value: number;
  tone?: "warning" | "danger";
}) {
  return (
    <li className="flex items-center gap-2.5">
      <span
        className={cn(
          "flex h-6 w-6 items-center justify-center rounded-lg",
          tone === "danger"
            ? "bg-danger-soft text-danger"
            : tone === "warning"
              ? "bg-warning-soft text-warning"
              : "bg-sunken text-ink-muted",
        )}
      >
        {icon}
      </span>
      <span className="flex-1 text-sm">{label}</span>
      <span
        className={cn(
          "tnum text-sm font-bold",
          tone === "danger" && "text-danger",
          tone === "warning" && "text-warning",
        )}
      >
        {value}
      </span>
    </li>
  );
}
