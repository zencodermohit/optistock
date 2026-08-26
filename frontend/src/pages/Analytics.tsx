import {
  AlertTriangle,
  Boxes,
  Info,
  PackageX,
  RefreshCw,
  RotateCw,
  Truck,
  TrendingDown,
  TrendingUp,
} from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { PageHeader } from "@/components/layout/AppShell";
import { Band } from "@/components/ui/Band";
import { ErrorState, Skeleton } from "@/components/ui/states";
import {
  count,
  currency,
  currencyCompact,
  date,
  percent,
  relativeTime,
} from "@/lib/format";
import {
  useAnalytics,
  useWarehouses,
  type WarehousePerformance,
} from "@/lib/queries";
import { cn } from "@/lib/utils";

/**
 * Analytics — how the business is doing, in one screen.
 *
 * Every figure here comes from one request. The page asks a single question and
 * answering it with eight round trips would mean eight loading states resolving
 * at eight different moments.
 *
 * Two rules the layout follows, both inherited from the design system rather
 * than invented here. Red and amber mean stock trouble and nothing else may
 * borrow them, so a KPI that is merely LARGE stays unmarked and only a KPI that
 * is WRONG gets a colour. And every derived number — dead stock, turnover, the
 * health score — states its definition on the page, because a figure whose
 * definition is hidden is a figure nobody can argue with.
 */

const RANGES = [7, 30, 90] as const;

export function Analytics() {
  const [days, setDays] = useState<number>(30);
  const [warehouseId, setWarehouseId] = useState<string>("");
  const analytics = useAnalytics(days, warehouseId || undefined);
  const warehouses = useWarehouses();

  const data = analytics.data;
  const k = data?.kpis;

  if (analytics.isError) {
    return (
      <ErrorState
        error={analytics.error}
        onRetry={() => void analytics.refetch()}
      />
    );
  }

  return (
    <>
      <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
        <PageHeader
          title="Analytics"
          description="Trading, stock and risk across the business."
        />

        <div className="flex flex-wrap items-center gap-2">
          {/* Range. Segmented rather than a date picker: three windows cover
              every question this page answers, and an arbitrary range control
              invites a request the read model does not support. */}
          <div className="flex items-center gap-0.5 rounded-lg border border-border bg-surface p-0.5">
            {RANGES.map((range) => (
              <button
                key={range}
                type="button"
                onClick={() => setDays(range)}
                className={cn(
                  "cursor-pointer rounded-md px-3 py-1.5 text-sm font-semibold transition-colors",
                  days === range
                    ? "bg-accent text-on-accent"
                    : "text-ink-muted hover:text-ink",
                )}
              >
                {range}d
              </button>
            ))}
          </div>

          <select
            value={warehouseId}
            onChange={(e) => setWarehouseId(e.target.value)}
            aria-label="Filter by warehouse"
            className="cursor-pointer rounded-lg border border-border bg-surface px-3 py-2 text-sm font-semibold text-ink"
          >
            <option value="">All sites</option>
            {warehouses.data?.data.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name}
              </option>
            ))}
          </select>

          <button
            type="button"
            onClick={() => void analytics.refetch()}
            aria-label="Refresh"
            className="flex h-9 w-9 cursor-pointer items-center justify-center rounded-lg border border-border bg-surface text-ink-muted transition-colors hover:text-accent"
          >
            <RefreshCw
              className={cn("h-4 w-4", analytics.isFetching && "animate-spin")}
            />
          </button>
        </div>
      </div>

      {/* ---------------- KPI row ---------------- */}
      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-3 xl:grid-cols-6">
        <Kpi
          icon={<TrendingUp className="h-4 w-4" />}
          label="Revenue"
          value={k ? currencyCompact(k.revenue) : undefined}
          delta={k?.revenue_change_pct ?? null}
          note={`last ${days} days`}
        />
        <Kpi
          icon={<Boxes className="h-4 w-4" />}
          label="Inventory value"
          value={k ? currencyCompact(k.inventory_value) : undefined}
          note={k ? `across ${count(k.stock_lines)} stock lines` : undefined}
        />
        <Kpi
          icon={<AlertTriangle className="h-4 w-4" />}
          label="Stockout risk"
          value={k ? `${count(k.at_risk)}` : undefined}
          note={
            k
              ? `${count(k.critical)} critical · under 15 days cover`
              : undefined
          }
          tone={
            k && k.critical > 0
              ? "danger"
              : k && k.at_risk > 0
                ? "warning"
                : undefined
          }
        />
        <Kpi
          icon={<PackageX className="h-4 w-4" />}
          label="Dead inventory"
          value={k ? currencyCompact(k.dead_value) : undefined}
          note={
            k
              ? `${count(k.dead_lines)} lines · no sale in ${data?.assumptions.dead_stock_days}d`
              : undefined
          }
          tone={k && k.dead_value > 0 ? "warning" : undefined}
        />
        <Kpi
          icon={<RotateCw className="h-4 w-4" />}
          label="Inventory turnover"
          value={k?.turnover != null ? `${k.turnover.toFixed(1)}×` : "—"}
          note="annualised, at cost"
          hint={data?.assumptions.turnover_note}
        />
        <Kpi
          icon={<Truck className="h-4 w-4" />}
          label="Active POs"
          value={k ? count(k.active_pos) : undefined}
          note={k ? `${count(k.delayed_pos)} past due` : undefined}
          tone={k && k.delayed_pos > 0 ? "warning" : undefined}
        />
      </div>

      {/* ---------------- Middle row ---------------- */}
      <div className="mb-4 grid gap-4 xl:grid-cols-[1fr_1fr_20rem]">
        <WarehouseTable
          rows={data?.warehouse_performance ?? []}
          formula={data?.assumptions.health_formula}
          loading={analytics.isLoading}
        />
        <RevenueTrend
          series={data?.revenue_trend ?? []}
          days={days}
          source={data?.trend_source}
          note={data?.assumptions.trend_note}
          loading={analytics.isLoading}
        />
        <CriticalAlerts
          alerts={data?.critical_alerts ?? []}
          loading={analytics.isLoading}
        />
      </div>

      {/* ---------------- Bottom row ---------------- */}
      <div className="grid gap-4 lg:grid-cols-[22rem_1fr]">
        <InventoryHealth
          health={data?.inventory_health}
          excessDays={data?.assumptions.excess_cover_days}
          deadDays={data?.assumptions.dead_stock_days}
        />
        <RiskSummary bands={data?.risk_bands ?? []} atRisk={k?.at_risk ?? 0} />
      </div>
    </>
  );
}

/* -------------------------------------------------------------------------- */

function Kpi({
  icon,
  label,
  value,
  note,
  delta,
  tone,
  hint,
}: {
  icon: React.ReactNode;
  label: string;
  value?: string;
  note?: string;
  delta?: number | null;
  tone?: "warning" | "danger";
  hint?: string;
}) {
  return (
    <Band className="p-4">
      <div className="flex items-start justify-between gap-2">
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
        {hint && (
          <span title={hint} className="cursor-help text-ink-subtle">
            <Info className="h-3.5 w-3.5" />
          </span>
        )}
      </div>

      <p className="eyebrow mt-3">{label}</p>

      {value === undefined ? (
        <Skeleton className="mt-1.5 h-8 w-24" />
      ) : (
        <p
          className={cn(
            "tnum mt-1 text-3xl leading-none font-extrabold tracking-tight",
            tone === "danger" && "text-danger",
          )}
        >
          {value}
        </p>
      )}

      <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-0.5">
        {delta != null && (
          <span
            className={cn(
              "tnum inline-flex items-center gap-0.5 text-2xs font-bold",
              // Revenue direction is a fact about trading, not a stock alarm,
              // so it uses success/ink rather than borrowing the danger hue.
              delta >= 0 ? "text-success" : "text-ink-muted",
            )}
          >
            {delta >= 0 ? (
              <TrendingUp className="h-3 w-3" />
            ) : (
              <TrendingDown className="h-3 w-3" />
            )}
            {delta >= 0 ? "+" : ""}
            {delta.toFixed(1)}%
          </span>
        )}
        {note && <span className="text-2xs text-ink-subtle">{note}</span>}
      </div>
    </Band>
  );
}

/* -------------------------------------------------------------------------- */

function WarehouseTable({
  rows,
  formula,
  loading,
}: {
  rows: WarehousePerformance[];
  formula?: string;
  loading: boolean;
}) {
  return (
    <Band className="flex flex-col">
      <div className="border-b border-border px-4 py-3">
        <h3 className="font-display text-lg font-bold">
          Warehouse performance
        </h3>
      </div>

      <div className="flex-1 overflow-x-auto">
        {loading ? (
          <div className="space-y-2 p-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-9 w-full" />
            ))}
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border">
                {["Site", "Revenue", "Value", "Out", "Health"].map((h, i) => (
                  <th
                    key={h}
                    className={cn(
                      "px-4 py-2 font-display text-2xs font-bold tracking-wide text-ink-subtle uppercase",
                      i === 0 ? "text-left" : "text-right",
                    )}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr
                  key={row.id}
                  className="border-b border-border last:border-0"
                >
                  <td className="px-4 py-2.5 font-medium">{row.name}</td>
                  <td className="tnum px-4 py-2.5 text-right">
                    {currencyCompact(row.revenue)}
                  </td>
                  <td className="tnum px-4 py-2.5 text-right text-ink-muted">
                    {currencyCompact(row.inventory_value)}
                  </td>
                  <td
                    className={cn(
                      "tnum px-4 py-2.5 text-right",
                      row.stockouts > 0
                        ? "font-bold text-danger"
                        : "text-ink-muted",
                    )}
                  >
                    {row.stockouts}
                  </td>
                  <td className="px-4 py-2.5 text-right">
                    <HealthPill row={row} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* The formula, printed. A composite score that cannot be checked is an
          oracle, and an oracle is the first thing a reviewer distrusts. */}
      {formula && (
        <p className="border-t border-border px-4 py-2.5 text-2xs leading-relaxed text-ink-subtle">
          Health = {formula}
        </p>
      )}
    </Band>
  );
}

function HealthPill({ row }: { row: WarehousePerformance }) {
  if (row.score === null) {
    return <span className="text-2xs text-ink-subtle">no stock</span>;
  }
  const good = row.score >= 90;
  const fair = row.score >= 75;

  return (
    <span
      title={`−${row.out_penalty} out of stock · −${row.low_penalty} below reorder · −${row.alert_penalty} alerts`}
      className={cn(
        "tnum inline-block cursor-help rounded-full px-2.5 py-0.5 text-2xs font-bold",
        good
          ? "bg-success-soft text-success"
          : fair
            ? "bg-warning-soft text-warning"
            : "bg-danger-soft text-danger",
      )}
    >
      {row.score}
    </span>
  );
}

/* -------------------------------------------------------------------------- */

function RevenueTrend({
  series,
  days,
  source,
  note,
  loading,
}: {
  series: { date: string; revenue: number }[];
  days: number;
  source?: "projection" | "sales";
  note?: string;
  loading: boolean;
}) {
  const peak = Math.max(...series.map((d) => d.revenue), 0);

  return (
    <Band className="flex flex-col">
      <div className="flex items-baseline justify-between border-b border-border px-4 py-3">
        <h3 className="font-display text-lg font-bold">Revenue trend</h3>
        <span className="tnum text-2xs text-ink-subtle">
          peak {currencyCompact(peak)}
        </span>
      </div>

      <div className="min-h-[14rem] flex-1 p-3">
        {loading ? (
          <Skeleton className="h-full min-h-[13rem] w-full" />
        ) : (
          <ResponsiveContainer width="100%" height="100%" minHeight={208}>
            <AreaChart
              data={series}
              margin={{ top: 8, right: 8, bottom: 0, left: 0 }}
            >
              <defs>
                <linearGradient id="revfill" x1="0" y1="0" x2="0" y2="1">
                  <stop
                    offset="0%"
                    stopColor="var(--color-accent)"
                    stopOpacity={0.28}
                  />
                  <stop
                    offset="100%"
                    stopColor="var(--color-accent)"
                    stopOpacity={0}
                  />
                </linearGradient>
              </defs>
              <CartesianGrid
                stroke="var(--color-border)"
                strokeDasharray="3 3"
                vertical={false}
              />
              <XAxis
                dataKey="date"
                tick={{ fontSize: 10, fill: "var(--color-ink-subtle)" }}
                tickLine={false}
                axisLine={false}
                // Three labels, not thirty. A dense axis on a 90-day range is
                // an unreadable smear.
                ticks={[
                  series[0]?.date,
                  series[Math.floor(series.length / 2)]?.date,
                  series[series.length - 1]?.date,
                ].filter(Boolean)}
                tickFormatter={(v: string) => date(v)}
              />
              <YAxis
                tick={{ fontSize: 10, fill: "var(--color-ink-subtle)" }}
                tickLine={false}
                axisLine={false}
                width={52}
                tickFormatter={(v: number) => currencyCompact(v)}
              />
              <Tooltip
                contentStyle={{
                  background: "var(--color-surface)",
                  border: "1px solid var(--color-border)",
                  borderRadius: "0.75rem",
                  fontSize: 12,
                  boxShadow: "var(--shadow-md)",
                }}
                labelFormatter={(label) => date(String(label))}
                formatter={(value) => [currency(Number(value)), "Revenue"]}
              />
              <Area
                type="monotone"
                dataKey="revenue"
                stroke="var(--color-accent)"
                strokeWidth={2}
                fill="url(#revfill)"
              />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>
      {/* Which query answered this. The two sources can disagree — the
          projection is maintained by background consumers and can lag — so
          naming it is the difference between a discrepancy somebody can
          explain and one they cannot. */}
      <p
        title={note}
        className="cursor-help border-t border-border px-4 py-2 text-2xs text-ink-subtle"
      >
        Daily revenue over {days} days
        {source === "sales"
          ? " for this site, queried from sales."
          : ", from the daily projection the consumers maintain."}
      </p>
    </Band>
  );
}

/* -------------------------------------------------------------------------- */

function CriticalAlerts({
  alerts,
  loading,
}: {
  alerts: { id: string; severity: string; title: string; raised_at: string }[];
  loading: boolean;
}) {
  return (
    <Band className="flex flex-col">
      <div className="flex items-baseline justify-between border-b border-border px-4 py-3">
        <h3 className="font-display text-lg font-bold">Needs attention</h3>
        <Link to="/alerts" className="text-2xs font-bold text-accent">
          View all
        </Link>
      </div>

      {loading ? (
        <div className="space-y-2 p-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      ) : alerts.length === 0 ? (
        <p className="px-4 py-8 text-sm text-ink-muted">
          Nothing open. Alerts raised by the background consumers appear here.
        </p>
      ) : (
        <ul className="divide-y divide-border">
          {alerts.map((alert) => (
            <li key={alert.id} className="flex gap-2.5 px-4 py-2.5">
              <span
                className={cn(
                  "mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-md",
                  alert.severity === "critical"
                    ? "bg-danger-soft text-danger"
                    : "bg-warning-soft text-warning",
                )}
              >
                <AlertTriangle className="h-3 w-3" />
              </span>
              <div className="min-w-0">
                <p className="text-sm leading-snug font-medium">
                  {alert.title}
                </p>
                <p className="mt-0.5 text-2xs text-ink-subtle">
                  {relativeTime(alert.raised_at)}
                </p>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Band>
  );
}

/* -------------------------------------------------------------------------- */

/**
 * Where the money on the shelves is sitting.
 *
 * A stacked bar rather than a donut. The three buckets are parts of one total
 * and the question is "how much of my capital is doing nothing" — which a bar
 * answers by length, the one visual channel people compare accurately. A donut
 * asks them to compare angles, which they cannot.
 */
function InventoryHealth({
  health,
  excessDays,
  deadDays,
}: {
  health?: { healthy: number; excess: number; dead: number; total: number };
  excessDays?: number;
  deadDays?: number;
}) {
  const total = health?.total || 1;
  const parts = [
    {
      key: "healthy",
      label: "Working stock",
      value: health?.healthy ?? 0,
      cls: "bg-success",
      text: "text-success",
      note: "selling at a normal rate",
    },
    {
      key: "excess",
      label: "Excess",
      value: health?.excess ?? 0,
      cls: "bg-warning",
      text: "text-warning",
      note: `over ${excessDays ?? 180} days of cover`,
    },
    {
      key: "dead",
      label: "Dead",
      value: health?.dead ?? 0,
      cls: "bg-danger",
      text: "text-danger",
      note: `no sale in ${deadDays ?? 60} days`,
    },
  ];

  return (
    <Band className="flex flex-col p-4">
      <h3 className="font-display text-lg font-bold">Inventory health</h3>
      <p className="tnum mt-1 text-2xl font-extrabold">
        {currencyCompact(health?.total ?? 0)}
      </p>
      <p className="text-2xs text-ink-subtle">held at cost</p>

      <div className="mt-4 flex h-3 overflow-hidden rounded-full bg-sunken">
        {parts.map((p) =>
          p.value <= 0 ? null : (
            <div
              key={p.key}
              className={p.cls}
              style={{ width: `${(p.value / total) * 100}%` }}
            />
          ),
        )}
      </div>

      <ul className="mt-4 flex flex-col gap-3">
        {parts.map((p) => (
          <li key={p.key} className="flex items-start justify-between gap-3">
            <span className="flex items-start gap-2">
              <span
                className={cn("mt-1 h-2.5 w-2.5 shrink-0 rounded-full", p.cls)}
              />
              <span>
                <span className="block text-sm font-semibold">{p.label}</span>
                <span className="block text-2xs text-ink-subtle">{p.note}</span>
              </span>
            </span>
            <span className="text-right">
              <span className="tnum block text-sm font-bold">
                {currencyCompact(p.value)}
              </span>
              <span className={cn("tnum block text-2xs font-semibold", p.text)}>
                {percent((p.value / total) * 100, 0)}
              </span>
            </span>
          </li>
        ))}
      </ul>
    </Band>
  );
}

/* -------------------------------------------------------------------------- */

function RiskSummary({
  bands,
  atRisk,
}: {
  bands: { key: string; label: string; count: number }[];
  atRisk: number;
}) {
  const total = bands.reduce((n, b) => n + b.count, 0) || 1;
  // Fill and ink together, because the ink that reads on a filled hue is a
  // property of that hue rather than one colour for all four -- see the
  // --color-on-* tokens.
  const tone: Record<string, string> = {
    critical: "bg-danger text-on-danger",
    high: "bg-warning text-on-warning",
    medium: "bg-capacity text-on-capacity",
    low: "bg-success text-on-success",
  };
  const text: Record<string, string> = {
    critical: "text-danger",
    high: "text-warning",
    medium: "text-capacity",
    low: "text-success",
  };

  return (
    <Band className="flex flex-col p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="font-display text-lg font-bold">Stockout risk</h3>
        <Link to="/stockout-risk" className="text-2xs font-bold text-accent">
          Open the full list
        </Link>
      </div>
      <p className="mt-1 text-sm text-ink-muted">
        <span className="tnum font-bold text-ink">{count(atRisk)}</span> lines
        have under 15 days of cover at their current sales rate.
      </p>

      {/* Widths are proportional, but each band keeps a floor so a single
          critical line among three hundred is still a visible segment rather
          than a sliver nobody can click or read. */}
      <div className="mt-4 flex gap-1">
        {bands.map((band) => (
          <div
            key={band.key}
            className="flex flex-col gap-1.5"
            style={{ flex: `${Math.max((band.count / total) * 100, 8)} 1 0%` }}
          >
            <div
              className={cn(
                "flex h-11 items-center justify-center rounded-lg text-lg font-extrabold",
                tone[band.key],
                band.count === 0 && "opacity-30",
              )}
            >
              <span className="tnum">{band.count}</span>
            </div>
            <span className={cn("text-2xs font-bold", text[band.key])}>
              {band.key}
            </span>
            <span className="text-2xs whitespace-nowrap text-ink-subtle">
              {band.label}
            </span>
          </div>
        ))}
      </div>
    </Band>
  );
}
