import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  ArrowLeft,
  Boxes,
  CalendarClock,
  ShoppingCart,
  TrendingUp,
  Truck,
} from "lucide-react";
import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { ProductMark } from "@/components/products/ProductMark";
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
import { useProductCommand, type ProductCommandCenter } from "@/lib/queries";
import { cn } from "@/lib/utils";

/**
 * Layer 2 — one SKU, everything.
 *
 * A product detail page is not a form. The editable fields are the least
 * interesting thing about a SKU; what matters is how it has BEHAVED. So the
 * record sits in the header and the rest of the screen is measurement: demand
 * over the window, the same demand by month so a season is visible, where the
 * stock physically sits, what it sells alongside, and what to order.
 *
 * The health score shows its workings. A number nobody can explain is worse
 * than no number, so the deductions are listed beside it — the score summarises
 * the factors, it does not replace them.
 */
/** The one range vocabulary, shared with the hub. */
const RANGES = [30, 90, 180];

export function ProductCommand() {
  const { productId } = useParams<{ productId: string }>();

  // The window arrives from the hub so the two layers agree. Without it, a
  // product badged "Growing" over 30 days opens on a page measuring 90 and
  // reports demand falling -- both true, and together they read as a bug.
  const [params] = useSearchParams();
  const incoming = Number(params.get("days"));
  const [days, setDays] = useState(
    RANGES.includes(incoming) ? incoming : 90,
  );

  const query = useProductCommand(productId, days);
  const data = query.data;

  if (query.isError) {
    return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  }

  return (
    <>
      <Header data={data} days={days} onDays={setDays} />

      {!data ? (
        <div className="mt-5 grid gap-4 xl:grid-cols-[20rem_1fr]">
          <Skeleton className="h-80 rounded-2xl" />
          <Skeleton className="h-80 rounded-2xl" />
        </div>
      ) : (
        <>
          <div className="mt-5 grid gap-4 xl:grid-cols-[20rem_1fr]">
            <HealthCard data={data} />
            <div className="flex flex-col gap-4">
              <Metrics data={data} />
              <DemandChart data={data} />
            </div>
          </div>

          <div className="mt-4 grid gap-4 xl:grid-cols-[1fr_20rem]">
            <Seasonality data={data} />
            <Replenishment data={data} />
          </div>

          <div className="mt-4 grid gap-4 lg:grid-cols-3">
            <Distribution data={data} />
            <BoughtTogether data={data} />
            <Lifetime data={data} />
          </div>

          <Purchases data={data} />
        </>
      )}
    </>
  );
}

/* -------------------------------------------------------------------------- */

function Header({
  data,
  days,
  onDays,
}: {
  data?: ProductCommandCenter;
  days: number;
  onDays: (d: number) => void;
}) {
  const p = data?.product;

  return (
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div className="flex items-center gap-4">
        <Link
          to="/products"
          className="flex h-9 w-9 items-center justify-center rounded-xl border border-border bg-surface text-ink-muted transition-colors hover:text-ink"
          aria-label="Back to products"
        >
          <ArrowLeft className="h-4 w-4" />
        </Link>

        {p ? (
          <>
            <ProductMark sku={p.sku} category={p.category} size="lg" />
            <div>
              <h1 className="text-2xl leading-tight font-semibold">{p.name}</h1>
              <p className="mt-1 flex flex-wrap items-center gap-2 text-sm text-ink-muted">
                <span className="tnum">{p.sku}</span>
                {p.category && <span>· {p.category}</span>}
                {p.abc_class && (
                  <span className="rounded-full bg-accent-soft px-2 py-0.5 text-2xs font-bold text-accent">
                    Class {p.abc_class}
                  </span>
                )}
                {p.status !== "active" && (
                  <span className="rounded-full bg-sunken px-2 py-0.5 text-2xs font-bold text-ink-muted capitalize">
                    {p.status}
                  </span>
                )}
              </p>
            </div>
          </>
        ) : (
          <Skeleton className="h-12 w-64" />
        )}
      </div>

      <div className="flex items-center gap-1 rounded-xl border border-border bg-surface p-1">
        {RANGES.map((option) => (
          <button
            key={option}
            type="button"
            onClick={() => onDays(option)}
            className={cn(
              "rounded-lg px-3 py-1.5 text-xs font-bold transition-colors",
              days === option ? "bg-accent text-white" : "text-ink-muted hover:text-ink",
            )}
          >
            {option}d
          </button>
        ))}
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */

const BAND: Record<string, { ring: string; text: string; label: string }> = {
  strong: { ring: "var(--color-success)", text: "text-success", label: "Strong" },
  fair: { ring: "var(--color-info)", text: "text-info", label: "Fair" },
  weak: { ring: "var(--color-warning)", text: "text-warning", label: "Needs work" },
  critical: { ring: "var(--color-danger)", text: "text-danger", label: "Critical" },
};

/** The score, and every point it lost. Deliberately not a weighted average of
 *  normalised sub-scores — that produces a number that moves for reasons nobody
 *  can name. It starts at 100 and loses points for specific, nameable problems. */
function HealthCard({ data }: { data: ProductCommandCenter }) {
  const { score, band, factors } = data.health;
  const r = 52;
  const circumference = 2 * Math.PI * r;

  return (
    <Band className="flex flex-col p-4">
      <h3 className="font-display text-lg font-bold">Product health</h3>

      <div className="relative mx-auto my-4 grid h-40 w-40 place-items-center">
        <svg viewBox="0 0 128 128" className="h-40 w-40 -rotate-90">
          <circle
            cx="64"
            cy="64"
            r={r}
            fill="none"
            stroke="var(--color-sunken)"
            strokeWidth="12"
          />
          <circle
            cx="64"
            cy="64"
            r={r}
            fill="none"
            stroke={BAND[band].ring}
            strokeWidth="12"
            strokeLinecap="round"
            strokeDasharray={`${(score / 100) * circumference} ${circumference}`}
          />
        </svg>
        <div className="absolute text-center">
          <p className="tnum text-4xl leading-none font-extrabold">{score}</p>
          <p className={cn("mt-1 text-2xs font-bold", BAND[band].text)}>
            {BAND[band].label}
          </p>
        </div>
      </div>

      {factors.length === 0 ? (
        <p className="rounded-xl bg-success-soft px-3 py-2.5 text-sm text-success">
          Nothing is wrong with this product. It is selling, stocked and priced.
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {factors.map((factor) => (
            <li
              key={factor.label}
              className="flex items-start gap-2.5 rounded-xl bg-sunken px-3 py-2"
            >
              <span className="tnum mt-0.5 shrink-0 rounded-md bg-danger-soft px-1.5 py-0.5 text-2xs font-bold text-danger">
                {factor.impact}
              </span>
              <span className="min-w-0">
                <span className="block text-sm font-semibold">{factor.label}</span>
                <span className="block text-2xs text-ink-subtle">{factor.detail}</span>
              </span>
            </li>
          ))}
        </ul>
      )}

      <p className="mt-3 border-t border-border pt-2.5 text-2xs text-ink-subtle">
        Starts at 100. Each named problem deducts a fixed number of points, so the
        score can always be explained.
      </p>
    </Band>
  );
}

/* -------------------------------------------------------------------------- */

function Metrics({ data }: { data: ProductCommandCenter }) {
  const m = data.metrics;

  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <Metric
        icon={<Boxes className="h-4 w-4" />}
        label="On hand"
        value={count(m.on_hand)}
        note={`${count(m.sites)} sites · ${currencyCompact(m.inventory_value)}`}
        tone={m.on_hand === 0 ? "danger" : undefined}
      />
      <Metric
        icon={<CalendarClock className="h-4 w-4" />}
        label="Days of cover"
        value={m.days_cover === null ? "—" : `${Math.round(m.days_cover)}d`}
        note={
          m.daily_rate > 0
            ? `${m.daily_rate.toFixed(1)} units a day`
            : "no measured demand"
        }
        tone={
          m.days_cover !== null && m.days_cover <= 14
            ? "danger"
            : m.days_cover !== null && m.days_cover > 180
              ? "capacity"
              : undefined
        }
      />
      <Metric
        icon={<ShoppingCart className="h-4 w-4" />}
        label={`Revenue · ${data.range_days}d`}
        value={currencyCompact(m.revenue)}
        note={`${count(m.units_sold)} units over ${count(m.orders)} orders`}
      />
      <Metric
        icon={<TrendingUp className="h-4 w-4" />}
        label="Demand trend"
        value={
          m.growth === null ? "—" : `${m.growth >= 0 ? "+" : "−"}${percent(Math.abs(m.growth) * 100, 0)}`
        }
        note={
          m.growth === null
            ? "no prior period to compare"
            : `against ${count(m.prior_units)} units before`
        }
        tone={m.growth !== null && m.growth < -0.2 ? "danger" : undefined}
      />
    </div>
  );
}

/* -------------------------------------------------------------------------- */

function DemandChart({ data }: { data: ProductCommandCenter }) {
  const series = data.series;
  const ticks = [
    series[0]?.date,
    series[Math.floor(series.length / 2)]?.date,
    series[series.length - 1]?.date,
  ].filter(Boolean) as string[];

  return (
    <Band className="flex flex-1 flex-col">
      <div className="flex items-baseline justify-between border-b border-border px-4 py-3">
        <h3 className="font-display text-lg font-bold">Units sold</h3>
        <span className="text-2xs text-ink-subtle">last {data.range_days} days</span>
      </div>
      <div className="min-h-[13rem] flex-1 p-3">
        <ResponsiveContainer width="100%" height="100%" minHeight={200}>
          <AreaChart data={series} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <defs>
              <linearGradient id="unitfill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="var(--color-accent)" stopOpacity={0.3} />
                <stop offset="100%" stopColor="var(--color-accent)" stopOpacity={0} />
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
              ticks={ticks}
              tickFormatter={(v: string) => date(v)}
            />
            <YAxis
              tick={{ fontSize: 10, fill: "var(--color-ink-subtle)" }}
              tickLine={false}
              axisLine={false}
              width={34}
              allowDecimals={false}
            />
            <Tooltip
              contentStyle={TOOLTIP}
              labelFormatter={(label) => date(String(label))}
              formatter={(value) => [count(Number(value)), "Units"]}
            />
            <Area
              type="monotone"
              dataKey="units"
              stroke="var(--color-accent)"
              strokeWidth={2}
              fill="url(#unitfill)"
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
      {/* Empty days are drawn as zero rather than skipped. A line that omits
          quiet days compresses time and draws a busier product than exists. */}
      <p className="border-t border-border px-4 py-2 text-2xs text-ink-subtle">
        Days with no sales are shown as zero, not skipped.
      </p>
    </Band>
  );
}

const TOOLTIP = {
  background: "var(--color-surface)",
  border: "1px solid var(--color-border)",
  borderRadius: "0.75rem",
  fontSize: 12,
  boxShadow: "var(--shadow-md)",
} as const;

/* -------------------------------------------------------------------------- */

/** Two years by month. A day-level chart shows noise; a month-level chart over
 *  two years shows whether this product has a season — which is the only way to
 *  know whether a quiet October is a problem or a pattern. */
function Seasonality({ data }: { data: ProductCommandCenter }) {
  const months = data.seasonality;
  const best = data.lifetime.best_month;

  return (
    <Band className="flex flex-col">
      <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-border px-4 py-3">
        <h3 className="font-display text-lg font-bold">Demand by month</h3>
        {best && (
          <span className="text-2xs text-ink-subtle">
            Best month {monthLabel(best.month)} · {count(best.units)} units
          </span>
        )}
      </div>

      <div className="min-h-[14rem] p-3">
        {months.length === 0 ? (
          <p className="grid h-52 place-items-center text-sm text-ink-muted">
            This product has never sold.
          </p>
        ) : (
          <ResponsiveContainer width="100%" height="100%" minHeight={210}>
            <BarChart data={months} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
              <CartesianGrid
                stroke="var(--color-border)"
                strokeDasharray="3 3"
                vertical={false}
              />
              <XAxis
                dataKey="month"
                tick={{ fontSize: 10, fill: "var(--color-ink-subtle)" }}
                tickLine={false}
                axisLine={false}
                interval={2}
                tickFormatter={monthLabel}
              />
              <YAxis
                tick={{ fontSize: 10, fill: "var(--color-ink-subtle)" }}
                tickLine={false}
                axisLine={false}
                width={34}
                allowDecimals={false}
              />
              <Tooltip
                contentStyle={TOOLTIP}
                cursor={{ fill: "var(--color-sunken)" }}
                labelFormatter={(label) => monthLabel(String(label))}
                formatter={(value) => [count(Number(value)), "Units"]}
              />
              <Bar dataKey="units" radius={[3, 3, 0, 0]}>
                {months.map((m) => (
                  // The month in progress is drawn hollow. It is genuinely
                  // shorter than the others because it is not over, and a solid
                  // bar would read as a collapse in demand.
                  <Cell
                    key={m.month}
                    fill={m.partial ? "var(--color-accent-soft)" : "var(--color-accent)"}
                    stroke={m.partial ? "var(--color-accent-border)" : undefined}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>

      <p className="border-t border-border px-4 py-2 text-2xs text-ink-subtle">
        The current month is shown hollow — it is still in progress and is not
        comparable with the months that finished.
      </p>
    </Band>
  );
}

function monthLabel(value: string): string {
  const [year, month] = value.split("-");
  const names = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
  ];
  return `${names[Number(month) - 1] ?? month} ${year.slice(2)}`;
}

/* -------------------------------------------------------------------------- */

/** What to order, and every assumption behind it. EOQ is a square root of three
 *  inputs — get one wrong and the answer is confidently wrong — so the inputs
 *  are printed next to the output rather than buried in a service. */
function Replenishment({ data }: { data: ProductCommandCenter }) {
  const r = data.recommendation;

  if (!r) {
    return (
      <Band className="p-4">
        <h3 className="font-display text-lg font-bold">Replenishment</h3>
        <p className="mt-2 text-sm text-ink-muted">
          No measured demand in this window, so there is no order quantity to
          recommend. An EOQ divided by zero demand is a division error, not
          advice.
        </p>
      </Band>
    );
  }

  return (
    <Band className="flex flex-col p-4">
      <div className="flex items-center justify-between">
        <h3 className="font-display text-lg font-bold">Replenishment</h3>
        {r.order_now ? (
          <span className="rounded-full bg-danger-soft px-2 py-0.5 text-2xs font-bold text-danger">
            Order now
          </span>
        ) : (
          <span className="rounded-full bg-success-soft px-2 py-0.5 text-2xs font-bold text-success">
            Stocked
          </span>
        )}
      </div>

      <dl className="mt-3 flex flex-col gap-2.5">
        <Figure
          label="Order quantity (EOQ)"
          value={count(r.eoq)}
          note="the size that minimises ordering plus holding cost"
        />
        <Figure
          label="Reorder point"
          value={count(r.reorder_point)}
          note={`${count(data.metrics.on_hand)} on hand today`}
        />
        <Figure
          label="Safety stock"
          value={count(r.safety_stock)}
          note={`covers a ${count(r.assumptions.peak_daily_demand)}-unit day`}
        />
        <Figure
          label="Lead time"
          value={`${r.lead_time_days}d`}
          note={r.lead_time_source}
        />
      </dl>

      <div className="mt-3 border-t border-border pt-2.5">
        <p className="eyebrow">Assumptions</p>
        <p className="mt-1 text-2xs leading-relaxed text-ink-subtle">
          Annual demand {count(r.assumptions.annual_demand)} units, extrapolated
          from this window. Holding cost{" "}
          {percent(r.assumptions.holding_cost_rate * 100, 0)} of unit cost a
          year. {currency(r.assumptions.order_cost)} to raise one order. Change
          any of these and the numbers above change with them.
        </p>
      </div>
    </Band>
  );
}

function Figure({
  label,
  value,
  note,
}: {
  label: string;
  value: string;
  note: string;
}) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="min-w-0">
        <span className="block text-sm font-semibold">{label}</span>
        <span className="block text-2xs text-ink-subtle">{note}</span>
      </dt>
      <dd className="tnum shrink-0 text-lg font-extrabold">{value}</dd>
    </div>
  );
}

/* -------------------------------------------------------------------------- */

function Distribution({ data }: { data: ProductCommandCenter }) {
  const sites = data.warehouses;

  return (
    <Band className="flex flex-col">
      <div className="border-b border-border px-4 py-3">
        <h3 className="font-display text-lg font-bold">Where the stock is</h3>
      </div>
      {sites.length === 0 ? (
        <p className="px-4 py-8 text-sm text-ink-muted">
          No stock line for this product in any warehouse.
        </p>
      ) : (
        <ul className="flex flex-col gap-3 p-4">
          {sites.map((site) => (
            <li key={site.id}>
              <div className="flex items-baseline justify-between gap-2">
                <Link
                  to={`/inventory/${site.id}`}
                  className="truncate text-sm font-semibold hover:text-accent"
                >
                  {site.name}
                </Link>
                <span className="tnum shrink-0 text-sm font-bold">
                  {count(site.quantity)}
                </span>
              </div>
              <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-sunken">
                <div
                  className={cn(
                    "h-full rounded-full",
                    site.below_reorder ? "bg-danger" : "bg-accent",
                  )}
                  style={{ width: `${site.share * 100}%` }}
                />
              </div>
              <p className="mt-1 text-2xs text-ink-subtle">
                {percent(site.share * 100, 0)} of stock
                {site.reorder_point > 0 &&
                  ` · reorders at ${count(site.reorder_point)}`}
                {site.below_reorder && (
                  <span className="font-bold text-danger"> · below reorder point</span>
                )}
              </p>
            </li>
          ))}
        </ul>
      )}
    </Band>
  );
}

/* -------------------------------------------------------------------------- */

/** Products that appear on the same orders. Worth knowing because a stockout on
 *  a product with strong companions can cost the whole basket, not just its own
 *  line — which is the argument for prioritising its reorder. */
function BoughtTogether({ data }: { data: ProductCommandCenter }) {
  const items = data.bought_together;

  return (
    <Band className="flex flex-col">
      <div className="border-b border-border px-4 py-3">
        <h3 className="font-display text-lg font-bold">Bought alongside</h3>
      </div>
      {items.length === 0 ? (
        <p className="px-4 py-8 text-sm text-ink-muted">
          Nothing has shared an order with this product in the last{" "}
          {data.range_days} days.
        </p>
      ) : (
        <ul className="divide-y divide-border">
          {items.map((item) => (
            <li key={item.id}>
              <Link
                to={`/products/${item.id}`}
                className="flex items-center gap-3 px-4 py-2.5 transition-colors hover:bg-sunken/50"
              >
                <ProductMark sku={item.sku} category={item.category} size="sm" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-semibold">
                    {item.name}
                  </span>
                  <span className="block truncate text-2xs text-ink-subtle">
                    {item.sku}
                  </span>
                </span>
                <span className="shrink-0 text-right">
                  <span className="tnum block text-sm font-bold">
                    {item.attach_rate === null
                      ? "—"
                      : percent(item.attach_rate * 100, 0)}
                  </span>
                  <span className="block text-2xs text-ink-subtle">
                    {count(item.orders)} orders
                  </span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Band>
  );
}

/* -------------------------------------------------------------------------- */

function Lifetime({ data }: { data: ProductCommandCenter }) {
  const l = data.lifetime;

  return (
    <Band className="flex flex-col p-4">
      <h3 className="font-display text-lg font-bold">Lifetime</h3>

      {l.first_sale === null ? (
        <p className="mt-2 text-sm text-ink-muted">
          This product has never sold.
        </p>
      ) : (
        <ol className="mt-3 flex flex-col gap-3 border-l border-border pl-4">
          <Event
            label="First sale"
            value={date(l.first_sale)}
            note={l.days_selling ? `${count(l.days_selling)} days ago` : undefined}
          />
          {l.best_month && (
            <Event
              label="Best month"
              value={monthLabel(l.best_month.month)}
              note={`${count(l.best_month.units)} units · ${currencyCompact(l.best_month.revenue)}`}
            />
          )}
          <Event
            label="Last sale"
            value={l.last_sale ? relativeTime(l.last_sale) : "—"}
            note={
              data.metrics.days_since_sale !== null
                ? `${count(data.metrics.days_since_sale)} days ago`
                : undefined
            }
          />
        </ol>
      )}

      <div className="mt-4 grid grid-cols-2 gap-3 border-t border-border pt-3">
        <div>
          <p className="eyebrow">Units, all time</p>
          <p className="tnum mt-0.5 text-xl font-extrabold">{count(l.units)}</p>
        </div>
        <div>
          <p className="eyebrow">Revenue, all time</p>
          <p className="tnum mt-0.5 text-xl font-extrabold">
            {currencyCompact(l.revenue)}
          </p>
        </div>
      </div>

      <div className="mt-3 border-t border-border pt-3">
        <p className="eyebrow">Unit economics</p>
        <p className="tnum mt-1 text-sm">
          {currency(data.product.unit_cost)} cost ·{" "}
          {currency(data.product.selling_price)} price
          {data.product.margin !== null && (
            <span
              className={cn(
                "ml-1 font-bold",
                data.product.margin < 0.1 ? "text-danger" : "text-success",
              )}
            >
              ({percent(data.product.margin * 100, 0)} margin)
            </span>
          )}
        </p>
      </div>
    </Band>
  );
}

function Event({
  label,
  value,
  note,
}: {
  label: string;
  value: string;
  note?: string;
}) {
  return (
    <li className="relative">
      <span className="absolute -left-[1.3rem] top-1.5 h-2 w-2 rounded-full bg-accent" />
      <p className="eyebrow">{label}</p>
      <p className="text-sm font-semibold">{value}</p>
      {note && <p className="text-2xs text-ink-subtle">{note}</p>}
    </li>
  );
}

/* -------------------------------------------------------------------------- */

function Purchases({ data }: { data: ProductCommandCenter }) {
  const purchases = data.purchases;

  return (
    <Band className="mt-4 flex flex-col">
      <div className="flex items-center gap-2 border-b border-border px-4 py-3">
        <Truck className="h-4 w-4 text-ink-muted" />
        <h3 className="font-display text-lg font-bold">Purchase history</h3>
      </div>
      {purchases.length === 0 ? (
        <p className="px-4 py-6 text-sm text-ink-muted">
          This product has never been ordered from a supplier. The lead time used
          in the replenishment figures is an assumption, not a measurement.
        </p>
      ) : (
        <ul className="divide-y divide-border">
          {purchases.map((po) => (
            <li key={po.id} className="flex items-center gap-3 px-4 py-2.5">
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-semibold">
                  {po.supplier ?? "Unknown supplier"}
                </span>
                <span className="block text-2xs text-ink-subtle">
                  {po.created_at ? date(po.created_at) : "—"}
                  {po.expected && ` · expected ${date(po.expected)}`}
                </span>
              </span>
              <span className="tnum w-20 shrink-0 text-right text-sm font-bold">
                {count(po.quantity)}
              </span>
              <span className="tnum w-24 shrink-0 text-right text-sm">
                {currency(po.unit_price)}
              </span>
              <span className="w-24 shrink-0 text-right text-2xs font-bold capitalize">
                {po.status}
              </span>
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
  tone,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  note?: string;
  tone?: "danger" | "capacity";
}) {
  return (
    <Band className="p-4">
      <span
        className={cn(
          "flex h-8 w-8 items-center justify-center rounded-lg",
          tone === "danger"
            ? "bg-danger-soft text-danger"
            : tone === "capacity"
              ? "bg-capacity-soft text-capacity"
              : "bg-accent-soft text-accent",
        )}
      >
        {icon}
      </span>
      <p className="eyebrow mt-3">{label}</p>
      <p
        className={cn(
          "tnum mt-1 text-2xl leading-none font-extrabold",
          tone === "danger" && "text-danger",
        )}
      >
        {value}
      </p>
      {note && <p className="mt-1.5 text-2xs text-ink-subtle">{note}</p>}
    </Band>
  );
}
