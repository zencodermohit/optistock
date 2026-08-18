import {
  AlertTriangle,
  ArrowRight,
  ArrowUpRight,
  CheckCircle2,
  ChevronRight,
  ClipboardCheck,
  ClipboardList,
  Clock,
  PackageX,
  ShoppingCart,
  Truck,
  XCircle,
} from "lucide-react";
import { Link } from "react-router-dom";

import { PageHeader } from "@/components/layout/AppShell";
import { ProductMark } from "@/components/products/ProductMark";
import { Band } from "@/components/ui/Band";
import { ErrorState, Skeleton } from "@/components/ui/states";
import { count, currencyCompact, percent } from "@/lib/format";
import { useProcurement, type Procurement as ProcurementData } from "@/lib/queries";
import { cn } from "@/lib/utils";

/**
 * Procurement — what to order, and what is going wrong with what was ordered.
 *
 * The old page was a table of purchase orders, which answers "what did we
 * order" and nothing else. Nobody opens a procurement screen to read a list;
 * they open it because something needs buying or something has not arrived. So
 * the recommendations and the exceptions come first and the orders sit under
 * them.
 *
 * Two rules the page holds to, both inherited rather than invented here. Red and
 * amber mean supply trouble and nothing else may borrow them — a KPI that is
 * merely large stays unmarked. And every derived figure states its definition,
 * because a number whose definition is hidden is one nobody can argue with.
 *
 * Nothing here is labelled AI. The recommendations come from a forecast, and
 * its confidence score is a data-density heuristic rather than a model
 * probability, so the page says that in the words it uses.
 */
export function Procurement() {
  const query = useProcurement();
  const data = query.data;

  if (query.isError) {
    return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  }

  return (
    <>
      <PageHeader
        title="Purchase orders"
        description="What needs buying, what has not arrived, and what is open with each supplier."
        action={
          <Link
            to="/purchase-orders/all"
            className="flex items-center gap-1.5 rounded-xl bg-accent px-4 py-2.5 text-sm font-bold text-white transition-colors hover:bg-accent-hover"
          >
            Browse all orders
            <ArrowRight className="h-4 w-4" />
          </Link>
        }
      />

      {/* ---------------- KPIs ---------------- */}
      <div className="mt-5 mb-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {PLACEHOLDER_KPIS.map((placeholder) => (
          <KpiCard
            key={placeholder.key}
            kpi={data?.kpis.find((k) => k.key === placeholder.key)}
            label={placeholder.label}
          />
        ))}
      </div>

      {/* ---------------- Recommendations + exceptions ---------------- */}
      <div className="grid gap-4 xl:grid-cols-[1fr_23rem]">
        <Recommendations data={data} loading={query.isLoading} />
        <Exceptions data={data} loading={query.isLoading} />
      </div>

      {/* ---------------- Workspaces ---------------- */}
      <Workspaces data={data} />

      {/* ---------------- Suppliers ---------------- */}
      <Suppliers data={data} />
    </>
  );
}

const PLACEHOLDER_KPIS = [
  { key: "open", label: "Open orders" },
  { key: "awaiting_approval", label: "Awaiting approval" },
  { key: "delayed", label: "Delayed orders" },
  { key: "urgent_reorders", label: "Urgent reorders" },
] as const;

const KPI_ICON: Record<string, React.ReactNode> = {
  open: <ClipboardList className="h-4 w-4" />,
  awaiting_approval: <ClipboardCheck className="h-4 w-4" />,
  delayed: <Clock className="h-4 w-4" />,
  urgent_reorders: <ShoppingCart className="h-4 w-4" />,
};

const TONE: Record<string, { chip: string; line: string }> = {
  accent: { chip: "bg-accent-soft text-accent", line: "var(--color-accent)" },
  warning: { chip: "bg-warning-soft text-warning", line: "var(--color-warning)" },
  danger: { chip: "bg-danger-soft text-danger", line: "var(--color-danger)" },
  success: { chip: "bg-success-soft text-success", line: "var(--color-success)" },
};

function KpiCard({
  kpi,
  label,
}: {
  kpi?: ProcurementData["kpis"][number];
  label: string;
}) {
  const tone = TONE[kpi?.tone ?? "accent"];

  return (
    <Band className="p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <span
            className={cn(
              "flex h-8 w-8 items-center justify-center rounded-lg",
              tone.chip,
            )}
          >
            {KPI_ICON[kpi?.key ?? ""] ?? <ClipboardList className="h-4 w-4" />}
          </span>
          <p className="eyebrow mt-3">{label}</p>
          {kpi ? (
            <p
              className={cn(
                "tnum mt-1 text-3xl leading-none font-extrabold",
                kpi.tone === "danger" && kpi.value > 0 && "text-danger",
              )}
            >
              {count(kpi.value)}
            </p>
          ) : (
            <Skeleton className="mt-1.5 h-8 w-16" />
          )}
          {kpi && (
            <p className="tnum mt-1.5 text-2xs text-ink-subtle">
              {currencyCompact(kpi.amount)}
            </p>
          )}
        </div>

        {kpi && kpi.sparkline.length > 0 && (
          <Sparkline values={kpi.sparkline} stroke={tone.line} />
        )}
      </div>

      {/* A trend only where one is meaningful. Three of these four cards are
          levels, and a level has no month-on-month change — only the rate of
          raising orders does. */}
      {kpi?.trend != null && (
        <p
          title={kpi.trend_label}
          className={cn(
            "tnum mt-2 flex cursor-help items-center gap-1 border-t border-border pt-2 text-2xs font-bold",
            kpi.trend >= 0 ? "text-success" : "text-danger",
          )}
        >
          <ArrowUpRight
            className={cn("h-3 w-3", kpi.trend < 0 && "rotate-90")}
          />
          {percent(Math.abs(kpi.trend) * 100, 0)}
          <span className="font-medium text-ink-subtle">{kpi.trend_label}</span>
        </p>
      )}
    </Band>
  );
}

/** Eight weeks of order value. Weekly rather than daily, because a daily line
 *  for a business raising forty-five orders a month is mostly zeros. */
function Sparkline({ values, stroke }: { values: number[]; stroke: string }) {
  const peak = Math.max(...values, 1);
  const points = values
    .map((v, i) => `${(i / Math.max(values.length - 1, 1)) * 64},${24 - (v / peak) * 22}`)
    .join(" ");

  return (
    <svg viewBox="0 0 64 24" className="h-6 w-16 shrink-0" aria-hidden>
      <polyline
        points={points}
        fill="none"
        stroke={stroke}
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}

/* -------------------------------------------------------------------------- */

function Recommendations({
  data,
  loading,
}: {
  data?: ProcurementData;
  loading: boolean;
}) {
  const rows = data?.recommendations ?? [];

  return (
    <Band className="flex flex-col overflow-hidden">
      <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-border px-4 py-3">
        <div>
          <h3 className="font-display text-lg font-bold">Recommended orders</h3>
          <p className="mt-0.5 text-2xs text-ink-subtle">
            From the nightly demand forecast, net of stock already on hand.
          </p>
        </div>
        <Link to="/stockout-risk" className="text-2xs font-bold text-accent">
          Stockout risk →
        </Link>
      </div>

      {loading ? (
        <div className="flex flex-col gap-2 p-4">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-28 rounded-xl" />
          ))}
        </div>
      ) : rows.length === 0 ? (
        <div className="flex flex-col items-center gap-2 px-4 py-14 text-center">
          <CheckCircle2 className="h-8 w-8 text-success" />
          <p className="text-sm font-semibold">Nothing needs ordering</p>
          <p className="max-w-sm text-2xs text-ink-subtle">
            Every product is forecast to have enough stock for the coming window.
            Recommendations appear here when forecast demand exceeds what is on
            the shelf.
          </p>
        </div>
      ) : (
        <ul className="divide-y divide-border">
          {rows.map((row) => (
            <li key={row.id} className="p-4">
              <div className="flex flex-wrap items-start gap-3">
                <ProductMark sku={row.sku} category={row.category} size="lg" />

                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <Link
                      to={`/products/${row.product_id}`}
                      className="font-display text-base font-bold hover:text-accent"
                    >
                      {row.name}
                    </Link>
                    <span
                      className={cn(
                        "rounded-full px-2 py-0.5 text-2xs font-bold",
                        row.priority === "high"
                          ? "bg-danger-soft text-danger"
                          : "bg-warning-soft text-warning",
                      )}
                    >
                      {row.priority === "high" ? "High priority" : "Medium"}
                    </span>
                  </div>
                  <p className="tnum mt-0.5 text-2xs text-ink-subtle">
                    {row.sku}
                    {row.category && ` · ${row.category}`} · {row.warehouse}
                  </p>
                </div>

                <button
                  type="button"
                  className="rounded-xl bg-accent px-4 py-2 text-sm font-bold text-white transition-colors hover:bg-accent-hover"
                >
                  Raise order
                </button>
              </div>

              <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-4">
                <Figure
                  label="On hand"
                  value={count(row.on_hand)}
                  note={
                    row.days_of_stock === null
                      ? "no measured demand"
                      : `${row.days_of_stock.toFixed(0)} days of stock`
                  }
                  tone={row.on_hand <= 0 ? "danger" : undefined}
                />
                <Figure
                  label="Forecast demand"
                  value={count(row.forecast_demand)}
                  note="next 30 days"
                />
                <Figure
                  label="Recommended buy"
                  value={count(row.recommended_quantity)}
                  note={`${currencyCompact(row.order_value)} at cost`}
                  accent
                />
                <Figure
                  label="Revenue at risk"
                  value={currencyCompact(row.revenue_at_risk)}
                  note="ceiling, not a forecast"
                />
              </dl>

              <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2 border-t border-border pt-3">
                <span className="text-2xs">
                  <span className="text-ink-subtle">Supplier </span>
                  <span className="font-semibold">
                    {row.supplier ?? "never ordered before"}
                  </span>
                </span>
                <span className="text-2xs">
                  <span className="text-ink-subtle">Lead time </span>
                  <span
                    className="cursor-help font-semibold"
                    title={
                      row.lead_time_days === null
                        ? "No delivered orders to measure"
                        : `Averaged over ${row.lead_time_observations} delivered orders`
                    }
                  >
                    {row.lead_time_days === null
                      ? "unknown"
                      : `${row.lead_time_days.toFixed(0)} days`}
                  </span>
                </span>

                {/* The bar is the number, and the label says what the number
                    means. "92% confident" reads as a probability; this is the
                    share of days that recorded a sale, which is a different
                    claim and a weaker one. */}
                <span
                  className="flex flex-1 cursor-help items-center gap-2"
                  title={data?.definitions.confidence}
                >
                  <span className="text-2xs text-ink-subtle">Data density</span>
                  <span className="h-1.5 min-w-16 flex-1 overflow-hidden rounded-full bg-sunken">
                    <span
                      className={cn(
                        "block h-full rounded-full",
                        row.confidence >= 60
                          ? "bg-success"
                          : row.confidence >= 30
                            ? "bg-warning"
                            : "bg-danger",
                      )}
                      style={{ width: `${row.confidence}%` }}
                    />
                  </span>
                  <span className="tnum text-2xs font-bold">{row.confidence}%</span>
                </span>
              </div>
            </li>
          ))}
        </ul>
      )}

      {data && rows.length > 0 && (
        <p className="border-t border-border px-4 py-2.5 text-2xs text-ink-subtle">
          {data.definitions.revenue_at_risk}
        </p>
      )}
    </Band>
  );
}

function Figure({
  label,
  value,
  note,
  accent,
  tone,
}: {
  label: string;
  value: string;
  note: string;
  accent?: boolean;
  tone?: "danger";
}) {
  return (
    <div>
      <dt className="eyebrow">{label}</dt>
      <dd
        className={cn(
          "tnum mt-0.5 text-lg leading-none font-extrabold",
          accent && "text-accent",
          tone === "danger" && "text-danger",
        )}
      >
        {value}
      </dd>
      <dd className="mt-1 text-2xs text-ink-subtle">{note}</dd>
    </div>
  );
}

/* -------------------------------------------------------------------------- */

const EXCEPTION_ICON: Record<string, React.ReactNode> = {
  supplier_delay: <Truck className="h-3.5 w-3.5" />,
  stockout_risk: <PackageX className="h-3.5 w-3.5" />,
  approval_pending: <ClipboardCheck className="h-3.5 w-3.5" />,
};

const SEVERITY: Record<string, { chip: string; label: string }> = {
  critical: { chip: "bg-danger-soft text-danger", label: "Critical" },
  high: { chip: "bg-warning-soft text-warning", label: "High" },
  medium: { chip: "bg-sunken text-ink-muted", label: "Medium" },
};

function Exceptions({
  data,
  loading,
}: {
  data?: ProcurementData;
  loading: boolean;
}) {
  const rows = data?.exceptions ?? [];

  return (
    <Band className="flex flex-col overflow-hidden">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <h3 className="font-display text-lg font-bold">Exceptions</h3>
        {rows.length > 0 && (
          <span className="tnum rounded-full bg-sunken px-2 py-0.5 text-2xs font-bold text-ink-muted">
            {count(rows.length)}
          </span>
        )}
      </div>

      {loading ? (
        <div className="flex flex-col gap-2 p-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-14 rounded-xl" />
          ))}
        </div>
      ) : rows.length === 0 ? (
        <div className="flex flex-col items-center gap-2 px-4 py-12 text-center">
          <CheckCircle2 className="h-7 w-7 text-success" />
          <p className="text-sm font-semibold">Nothing is going wrong</p>
          <p className="text-2xs text-ink-subtle">
            No late deliveries, no stockouts, no forgotten drafts.
          </p>
        </div>
      ) : (
        <ul className="divide-y divide-border">
          {rows.map((row) => (
            <li
              key={row.key}
              className="flex items-start gap-3 px-4 py-3 transition-colors hover:bg-sunken/50"
            >
              <span
                className={cn(
                  "mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg",
                  SEVERITY[row.severity].chip,
                )}
              >
                {EXCEPTION_ICON[row.kind] ?? <AlertTriangle className="h-3.5 w-3.5" />}
              </span>

              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-1.5">
                  <span
                    className={cn(
                      "rounded-full px-1.5 py-0.5 text-[10px] font-bold",
                      SEVERITY[row.severity].chip,
                    )}
                  >
                    {SEVERITY[row.severity].label}
                  </span>
                  <span className="tnum text-2xs font-bold text-ink-muted">
                    {currencyCompact(row.amount)}
                  </span>
                </div>
                <p className="mt-1 text-sm leading-snug font-semibold">{row.title}</p>
                <p className="text-2xs text-ink-subtle">{row.detail}</p>
              </div>

              <ChevronRight className="mt-1 h-4 w-4 shrink-0 text-ink-subtle" />
            </li>
          ))}
        </ul>
      )}
    </Band>
  );
}

/* -------------------------------------------------------------------------- */

const WORKSPACE_ICON: Record<string, React.ReactNode> = {
  open: <ClipboardList className="h-4 w-4" />,
  draft: <ClipboardCheck className="h-4 w-4" />,
  submitted: <Truck className="h-4 w-4" />,
  delivered: <CheckCircle2 className="h-4 w-4" />,
  cancelled: <XCircle className="h-4 w-4" />,
};

const WORKSPACE_TONE: Record<string, string> = {
  open: "bg-accent-soft text-accent",
  draft: "bg-warning-soft text-warning",
  submitted: "bg-info-soft text-info",
  delivered: "bg-success-soft text-success",
  cancelled: "bg-sunken text-ink-muted",
};

function Workspaces({ data }: { data?: ProcurementData }) {
  return (
    <section className="mt-4">
      <div className="mb-3 flex items-baseline justify-between">
        <h3 className="font-display text-lg font-bold">Order workspaces</h3>
        <Link to="/purchase-orders/all" className="text-2xs font-bold text-accent">
          Browse all orders →
        </Link>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
        {(data?.workspaces ?? Array.from({ length: 5 })).map((workspace, i) =>
          workspace ? (
            <Link
              key={workspace.key}
              to={`/purchase-orders/all?status=${workspace.statuses.join(",")}`}
              className="flex flex-col rounded-2xl border border-border bg-surface p-4 shadow-sm transition-all hover:-translate-y-0.5 hover:border-accent-border hover:shadow-md"
            >
              <div className="flex items-center gap-2">
                <span
                  className={cn(
                    "flex h-7 w-7 items-center justify-center rounded-lg",
                    WORKSPACE_TONE[workspace.key],
                  )}
                >
                  {WORKSPACE_ICON[workspace.key]}
                </span>
                <span className="font-display text-sm font-bold">
                  {workspace.label}
                </span>
                <ChevronRight className="ml-auto h-4 w-4 text-ink-subtle" />
              </div>

              <p className="tnum mt-3 text-2xl leading-none font-extrabold">
                {count(workspace.count)}
              </p>
              <p className="tnum mt-1 text-2xs text-ink-subtle">
                {currencyCompact(workspace.value)}
              </p>

              <div className="mt-2.5 flex h-6 items-end gap-[3px]">
                {workspace.sparkline.map((value, index) => {
                  const peak = Math.max(...workspace.sparkline, 1);
                  return (
                    <span
                      key={index}
                      className="flex-1 rounded-sm bg-accent/25"
                      style={{ height: `${Math.max((value / peak) * 100, 6)}%` }}
                    />
                  );
                })}
              </div>
            </Link>
          ) : (
            <Skeleton key={i} className="h-40 rounded-2xl" />
          ),
        )}
      </div>
    </section>
  );
}

/* -------------------------------------------------------------------------- */

function Suppliers({ data }: { data?: ProcurementData }) {
  if (!data) return null;

  const rows = [...data.suppliers].sort(
    (a, b) => b.overdue_now - a.overdue_now || (b.lead_time_days ?? 0) - (a.lead_time_days ?? 0),
  );
  if (rows.length === 0) return null;

  return (
    <Band className="mt-4 flex flex-col overflow-hidden">
      <div className="border-b border-border px-4 py-3">
        <h3 className="font-display text-lg font-bold">Suppliers</h3>
        <p className="mt-0.5 text-2xs text-ink-subtle">
          Lead time is measured from delivered orders, not stored on the record.
        </p>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[36rem]">
          <thead>
            <tr className="border-b border-border">
              <th className="px-4 py-2.5 text-left text-2xs font-bold text-ink-subtle">
                Supplier
              </th>
              <th className="px-4 py-2.5 text-right text-2xs font-bold text-ink-subtle">
                Orders
              </th>
              <th className="px-4 py-2.5 text-right text-2xs font-bold text-ink-subtle">
                Lead time
              </th>
              <th className="px-4 py-2.5 text-right text-2xs font-bold text-ink-subtle">
                Overdue now
              </th>
              <th className="px-4 py-2.5 text-right text-2xs font-bold text-ink-subtle">
                Stated reliability
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {rows.map((supplier) => (
              <tr key={supplier.id} className="transition-colors hover:bg-sunken/50">
                <td className="px-4 py-2.5 text-sm font-semibold">{supplier.name}</td>
                <td className="tnum px-4 py-2.5 text-right text-sm">
                  {count(supplier.orders)}
                </td>
                <td className="tnum px-4 py-2.5 text-right text-sm">
                  {supplier.lead_time_days === null
                    ? "—"
                    : `${supplier.lead_time_days.toFixed(0)}d`}
                </td>
                <td
                  className={cn(
                    "tnum px-4 py-2.5 text-right text-sm font-bold",
                    supplier.overdue_now > 0 ? "text-danger" : "text-ink-subtle",
                  )}
                >
                  {supplier.overdue_now === 0 ? "—" : count(supplier.overdue_now)}
                </td>
                <td className="tnum px-4 py-2.5 text-right text-sm text-ink-muted">
                  {supplier.stated_reliability === null
                    ? "—"
                    : percent(supplier.stated_reliability * 100, 0)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* The absence is deliberate and worth saying out loud. */}
      <p className="border-t border-border px-4 py-2.5 text-2xs text-ink-subtle">
        {data.definitions.on_time_rate}
      </p>
    </Band>
  );
}
