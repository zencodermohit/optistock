import {
  AlertTriangle,
  ArrowRight,
  Boxes,
  ChevronRight,
  Layers,
  PackageX,
  Truck,
  Warehouse as WarehouseIcon,
} from "lucide-react";
import { Link, useNavigate } from "react-router-dom";

import { PageHeader } from "@/components/layout/AppShell";
import { Band } from "@/components/ui/Band";
import { ErrorState, Skeleton } from "@/components/ui/states";
import { count, currencyCompact, percent, relativeTime } from "@/lib/format";
import { useNetwork, type NetworkData, type NetworkNode } from "@/lib/queries";
import { cn } from "@/lib/utils";

/**
 * Layer 1 — the network.
 *
 * The question this page answers is "which building needs me", and it has to
 * answer it before anybody reads a number. So the sites are drawn as a topology
 * with stock moving between them, not listed in a table: a table makes you
 * compare four rows, a map makes the struggling one look wrong.
 *
 * It is a TOPOLOGY, not a geography. There are no coordinates in the schema and
 * inventing them would put buildings in the wrong cities — which is worse than
 * not drawing a country at all. Nodes sit on a ring around the hub, and the
 * only lines drawn are real transfers with stock actually in flight.
 *
 * Nothing here reports revenue or margin. Analytics owns those, and two screens
 * answering the same question eventually disagree.
 */
export function InventoryNetwork() {
  const network = useNetwork();
  const data = network.data;

  if (network.isError) {
    return <ErrorState error={network.error} onRetry={() => void network.refetch()} />;
  }

  const s = data?.summary;

  return (
    <>
      <PageHeader
        title="Inventory network"
        description="Where the stock is, which site is under pressure, and what is moving between them."
      />

      {/* ---------------- Network KPIs ---------------- */}
      <div className="mt-5 mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <Metric
          icon={<Boxes className="h-4 w-4" />}
          label="Inventory value"
          value={s ? currencyCompact(s.inventory_value) : undefined}
          note={s ? `${count(s.stock_lines)} stock lines` : undefined}
        />
        <Metric
          icon={<Layers className="h-4 w-4" />}
          label="Units held"
          value={s ? count(s.units_held) : undefined}
          note={s ? `across ${s.sites} sites` : undefined}
        />
        <Metric
          icon={<WarehouseIcon className="h-4 w-4" />}
          label="Network utilisation"
          value={s ? percent(s.utilisation * 100, 1) : undefined}
          bar={s?.utilisation}
        />
        <Metric
          icon={<Truck className="h-4 w-4" />}
          label="Stock in flight"
          value={s ? count(s.in_flight) : undefined}
          note="transfers between sites"
        />
        <Metric
          icon={<PackageX className="h-4 w-4" />}
          label="Needs attention"
          value={s ? count(s.low_lines + s.out_lines) : undefined}
          note={s ? `${count(s.out_lines)} out of stock` : undefined}
          tone={s && s.out_lines > 0 ? "danger" : s && s.low_lines > 0 ? "warning" : undefined}
        />
      </div>

      {/* ---------------- Map + intelligence ---------------- */}
      <div className="grid gap-4 xl:grid-cols-[1fr_22rem]">
        <NetworkMap data={data} loading={network.isLoading} />

        <div className="flex flex-col gap-4">
          <NetworkSummary data={data} />
          <TopAlerts data={data} />
          <RecentTransfers data={data} />
        </div>
      </div>
    </>
  );
}

/* -------------------------------------------------------------------------- */

const BAND: Record<string, { dot: string; ring: string; text: string; label: string }> = {
  healthy: {
    dot: "bg-success",
    ring: "var(--color-success)",
    text: "text-success",
    label: "Healthy",
  },
  moderate: {
    dot: "bg-warning",
    ring: "var(--color-warning)",
    text: "text-warning",
    label: "Attention",
  },
  at_risk: {
    dot: "bg-danger",
    ring: "var(--color-danger)",
    text: "text-danger",
    label: "Critical",
  },
  unknown: {
    dot: "bg-ink-subtle",
    ring: "var(--color-ink-subtle)",
    text: "text-ink-subtle",
    label: "No stock",
  },
};

function NetworkMap({ data, loading }: { data?: NetworkData; loading: boolean }) {
  const navigate = useNavigate();
  const nodes = data?.nodes ?? [];

  // Nodes on a ring around a hub. Deliberately geometric rather than
  // geographic: placing a building on a map it does not have coordinates for
  // is a lie a viewer will believe.
  const placed = nodes.map((node, i) => {
    const angle = (i / Math.max(nodes.length, 1)) * Math.PI * 2 - Math.PI / 2;
    return {
      node,
      x: 50 + Math.cos(angle) * 33,
      y: 50 + Math.sin(angle) * 34,
    };
  });
  const byId = new Map(placed.map((p) => [p.node.id, p]));

  return (
    <Band className="relative flex min-h-[30rem] flex-col overflow-hidden">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <h3 className="font-display text-lg font-bold">Warehouse network</h3>
        <span className="flex items-center gap-1.5 text-2xs font-bold text-success">
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-success opacity-60" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-success" />
          </span>
          Live
        </span>
      </div>

      <div className="relative flex-1 bg-gradient-to-b from-sunken/60 to-transparent">
        {loading ? (
          <div className="grid h-full min-h-[24rem] place-items-center text-sm text-ink-subtle">
            Mapping the network…
          </div>
        ) : nodes.length === 0 ? (
          <div className="grid h-full min-h-[24rem] place-items-center text-sm text-ink-muted">
            No warehouses yet.
          </div>
        ) : (
          <div className="relative h-full min-h-[26rem] w-full">
            {/* Edges first, so cards sit on top of their own lines. */}
            <svg
              className="absolute inset-0 h-full w-full"
              viewBox="0 0 100 100"
              preserveAspectRatio="none"
              aria-hidden
            >
              {/* Spokes to the hub — the shape of the network itself. */}
              {placed.map((p) => (
                <line
                  key={`spoke-${p.node.id}`}
                  x1="50"
                  y1="50"
                  x2={p.x}
                  y2={p.y}
                  stroke="var(--color-border-strong)"
                  strokeWidth="0.18"
                  strokeDasharray="1.2 1"
                  vectorEffect="non-scaling-stroke"
                />
              ))}
              {/* Real transfers. A line here means stock has left one building
                  and not arrived at the other. */}
              {(data?.edges ?? []).map((edge) => {
                const from = byId.get(edge.from);
                const to = byId.get(edge.to);
                if (!from || !to) return null;
                return (
                  <line
                    key={edge.id}
                    x1={from.x}
                    y1={from.y}
                    x2={to.x}
                    y2={to.y}
                    stroke="var(--color-accent)"
                    strokeWidth="0.35"
                    strokeDasharray="2 1.5"
                    vectorEffect="non-scaling-stroke"
                    className="animate-[dash_1.4s_linear_infinite]"
                  />
                );
              })}
            </svg>

            {/* The hub */}
            <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2">
              <div className="flex h-12 w-12 items-center justify-center rounded-2xl border border-accent-border bg-accent text-on-accent shadow-md">
                <WarehouseIcon className="h-5 w-5" />
              </div>
            </div>

            {placed.map(({ node, x, y }) => (
              <button
                key={node.id}
                type="button"
                onClick={() => navigate(`/inventory/${node.id}`)}
                style={{ left: `${x}%`, top: `${y}%` }}
                className={cn(
                  "absolute w-[13.5rem] -translate-x-1/2 -translate-y-1/2 cursor-pointer",
                  "rounded-xl border border-border bg-surface/95 p-3 text-left shadow-md backdrop-blur-sm",
                  "transition-all hover:-translate-y-[calc(50%+3px)] hover:border-accent-border hover:shadow-lg",
                  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
                )}
              >
                <div className="flex items-start gap-2.5">
                  <Donut value={node.utilisation ?? 0} band={node.band} />
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-display text-sm font-bold">
                      {node.name}
                    </p>
                    <p className="tnum text-2xs text-ink-muted">
                      {currencyCompact(node.inventory_value)}
                    </p>
                    <p className="tnum text-2xs text-ink-subtle">
                      {count(node.units_held)} items
                    </p>
                  </div>
                </div>
                <div className="mt-2 flex items-center justify-between border-t border-border pt-2">
                  <span
                    className={cn(
                      "flex items-center gap-1.5 text-2xs font-bold",
                      BAND[node.band].text,
                    )}
                  >
                    <span className={cn("h-1.5 w-1.5 rounded-full", BAND[node.band].dot)} />
                    {BAND[node.band].label}
                  </span>
                  <ChevronRight className="h-3.5 w-3.5 text-ink-subtle" />
                </div>
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-4 border-t border-border px-4 py-2.5">
        {(["healthy", "moderate", "at_risk"] as const).map((key) => (
          <span key={key} className="flex items-center gap-1.5 text-2xs text-ink-muted">
            <span className={cn("h-2 w-2 rounded-full", BAND[key].dot)} />
            {BAND[key].label}
            <span className="text-ink-subtle">
              {key === "healthy" ? "80+" : key === "moderate" ? "60–79" : "under 60"}
            </span>
          </span>
        ))}
        <span className="ml-auto flex items-center gap-3 text-2xs text-ink-subtle">
          Click a site for its command center
          {/* The line-level browser still exists; it is a drill-down rather
              than the front door, because a table cannot tell you which
              building is struggling. */}
          <Link to="/inventory/all" className="font-bold text-accent">
            Browse all stock lines
          </Link>
        </span>
      </div>
    </Band>
  );
}

/** Utilisation as a ring. The arc is the number; the figure inside repeats it
 *  for anyone the arc does not serve. */
function Donut({ value, band }: { value: number; band: string }) {
  const pct = Math.min(Math.max(value, 0), 1);
  const r = 15;
  const circumference = 2 * Math.PI * r;

  return (
    <span className="relative grid h-11 w-11 shrink-0 place-items-center">
      <svg viewBox="0 0 36 36" className="h-11 w-11 -rotate-90">
        <circle
          cx="18"
          cy="18"
          r={r}
          fill="none"
          stroke="var(--color-sunken)"
          strokeWidth="4"
        />
        <circle
          cx="18"
          cy="18"
          r={r}
          fill="none"
          stroke={BAND[band].ring}
          strokeWidth="4"
          strokeLinecap="round"
          strokeDasharray={`${pct * circumference} ${circumference}`}
        />
      </svg>
      <span className="tnum absolute text-[10px] font-extrabold">
        {Math.round(pct * 100)}%
      </span>
    </span>
  );
}

/* -------------------------------------------------------------------------- */

function NetworkSummary({ data }: { data?: NetworkData }) {
  const bands = data?.summary.bands ?? {};
  const total = Math.max(data?.summary.sites ?? 0, 1);
  const counted = data?.summary.counts_recorded ?? 0;
  const approved = data?.summary.counts_approved ?? 0;

  return (
    <Band className="p-4">
      <h3 className="font-display text-lg font-bold">Network summary</h3>

      <ul className="mt-3 flex flex-col gap-3">
        {(["healthy", "moderate", "at_risk"] as const).map((key) => {
          const value = bands[key] ?? 0;
          return (
            <li key={key}>
              <div className="flex items-baseline justify-between">
                <span className="flex items-center gap-2 text-sm font-semibold">
                  <span className={cn("h-2 w-2 rounded-full", BAND[key].dot)} />
                  {BAND[key].label}
                </span>
                <span className="tnum text-sm font-bold">{value}</span>
              </div>
              <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-sunken">
                <div
                  className={cn("h-full rounded-full", BAND[key].dot)}
                  style={{ width: `${(value / total) * 100}%` }}
                />
              </div>
            </li>
          );
        })}
      </ul>

      <div className="mt-4 border-t border-border pt-3">
        <p className="eyebrow">Inventory accuracy</p>
        {counted === 0 ? (
          // Not 100%. Nobody has counted anything, and an unmeasured shelf is
          // not an accurate one.
          <p className="mt-1 text-sm text-ink-muted">
            Not measured — no stock counts recorded yet.
          </p>
        ) : (
          <>
            <p className="tnum mt-1 text-2xl font-extrabold">
              {percent((approved / counted) * 100, 1)}
            </p>
            <p className="text-2xs text-ink-subtle">
              {count(approved)} of {count(counted)} counts accepted without
              correction
            </p>
          </>
        )}
      </div>
    </Band>
  );
}

function TopAlerts({ data }: { data?: NetworkData }) {
  const alerts = (data?.alerts ?? []).filter((a) => a.count > 0);

  return (
    <Band className="flex flex-col">
      <div className="border-b border-border px-4 py-3">
        <h3 className="font-display text-lg font-bold">Top alerts</h3>
      </div>
      {alerts.length === 0 ? (
        <p className="px-4 py-6 text-sm text-ink-muted">
          Nothing on the network needs attention.
        </p>
      ) : (
        <ul className="divide-y divide-border">
          {alerts.map((alert) => (
            <li key={alert.key} className="flex items-start gap-3 px-4 py-3">
              <span
                className={cn(
                  "mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-lg",
                  alert.severity === "critical"
                    ? "bg-danger-soft text-danger"
                    : "bg-warning-soft text-warning",
                )}
              >
                <AlertTriangle className="h-3.5 w-3.5" />
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-sm leading-snug font-semibold">{alert.title}</p>
                <p className="text-2xs text-ink-subtle">{alert.detail}</p>
              </div>
              <span
                className={cn(
                  "tnum rounded-full px-2 py-0.5 text-2xs font-bold",
                  alert.severity === "critical"
                    ? "bg-danger-soft text-danger"
                    : "bg-warning-soft text-warning",
                )}
              >
                {count(alert.count)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Band>
  );
}

function RecentTransfers({ data }: { data?: NetworkData }) {
  const transfers = data?.transfers ?? [];

  return (
    <Band className="flex flex-col">
      <div className="border-b border-border px-4 py-3">
        <h3 className="font-display text-lg font-bold">Recent transfers</h3>
      </div>
      {transfers.length === 0 ? (
        <p className="px-4 py-6 text-sm text-ink-muted">
          No stock has moved between sites yet.
        </p>
      ) : (
        <ul className="divide-y divide-border">
          {transfers.map((t) => (
            <li key={t.id} className="px-4 py-2.5">
              <div className="flex items-center gap-1.5 text-sm">
                <span className="truncate font-medium">{t.from}</span>
                <ArrowRight className="h-3 w-3 shrink-0 text-ink-subtle" />
                <span className="truncate font-medium">{t.to}</span>
              </div>
              <div className="mt-0.5 flex items-center justify-between">
                <span className="tnum text-2xs text-ink-subtle">
                  {count(t.units)} items · {relativeTime(t.created_at)}
                </span>
                <span
                  className={cn(
                    "text-2xs font-bold",
                    t.status === "completed" ? "text-success" : "text-accent",
                  )}
                >
                  {t.status === "completed" ? "Received" : "In transit"}
                </span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Band>
  );
}

/* -------------------------------------------------------------------------- */

function Metric({
  icon,
  label,
  value,
  note,
  bar,
  tone,
}: {
  icon: React.ReactNode;
  label: string;
  value?: string;
  note?: string;
  bar?: number | null;
  tone?: "warning" | "danger";
}) {
  return (
    <Band className="p-4">
      <span
        className={cn(
          "flex h-8 w-8 items-center justify-center rounded-lg",
          tone === "danger"
            ? "bg-danger-soft text-danger"
            : tone === "warning"
              ? "bg-warning-soft text-warning"
              : "bg-accent-soft text-accent",
        )}
      >
        {icon}
      </span>
      <p className="eyebrow mt-3">{label}</p>
      {value === undefined ? (
        <Skeleton className="mt-1.5 h-7 w-20" />
      ) : (
        <p
          className={cn(
            "tnum mt-1 text-2xl leading-none font-extrabold",
            tone === "danger" && "text-danger",
          )}
        >
          {value}
        </p>
      )}
      {bar != null && (
        <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-sunken">
          <div
            className="h-full rounded-full bg-capacity"
            style={{ width: `${Math.min(bar * 100, 100)}%` }}
          />
        </div>
      )}
      {note && <p className="mt-1.5 text-2xs text-ink-subtle">{note}</p>}
    </Band>
  );
}

export type { NetworkNode };
