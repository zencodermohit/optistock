import {
  Activity,
  ArrowDownRight,
  ChevronRight,
  ArrowUpRight,
  Ban,
  Boxes,
  Layers,
  PackageX,
  Sparkles,
  TrendingUp,
  Trophy,
  Wallet,
} from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { PageHeader } from "@/components/layout/AppShell";
import { ProductMark } from "@/components/products/ProductMark";
import { Band } from "@/components/ui/Band";
import { ErrorState, Skeleton } from "@/components/ui/states";
import { count, currencyCompact, percent } from "@/lib/format";
import {
  useProductIntelligence,
  type Bucket,
  type ProductIntelligence,
  type ProductRow,
} from "@/lib/queries";
import { cn } from "@/lib/utils";

/**
 * Layer 1 — the catalogue, by behaviour rather than alphabetically.
 *
 * What was here before was a paginated table with a search box, which is a fine
 * answer to "where is SKU-0142" and no answer at all to "which of my two hundred
 * products needs me today". A table sorts; it does not triage. So the front door
 * is now the classification: six states, one per product, ordered by urgency.
 *
 * The ring and the workspace cards are the same data twice, on purpose. The ring
 * says how the catalogue is DISTRIBUTED — one glance, is this healthy. The cards
 * say what each group is WORTH and what is in it, which is the number that makes
 * somebody act. Clicking either filters the list below, so the page narrows in
 * place instead of throwing you at another screen.
 *
 * Nothing here reports margin or forecast. Analytics owns those.
 */
export function ProductsHub() {
  const [days, setDays] = useState(30);
  const [filter, setFilter] = useState<string | null>(null);

  const query = useProductIntelligence(days);
  const data = query.data;

  const rows = useMemo(
    () => (data ? applyFilter(data.products, filter) : []),
    [data, filter],
  );

  if (query.isError) {
    return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  }

  const k = data?.kpis;

  return (
    <>
      <PageHeader
        title="Product intelligence"
        description="Every SKU sorted by how it is behaving — what is selling, what is stuck, and what is about to run out."
        action={
          <div className="flex items-center gap-1 rounded-xl border border-border bg-surface p-1">
            {[30, 90, 180].map((option) => (
              <button
                key={option}
                type="button"
                onClick={() => setDays(option)}
                className={cn(
                  "rounded-lg px-3 py-1.5 text-xs font-bold transition-colors",
                  days === option
                    ? "bg-accent text-white"
                    : "text-ink-muted hover:text-ink",
                )}
              >
                {option}d
              </button>
            ))}
          </div>
        }
      />

      {/* ---------------- Portfolio KPIs ---------------- */}
      <div className="mt-5 mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        <Metric
          icon={<Layers className="h-4 w-4" />}
          label="Catalogue"
          value={k ? count(k.total) : undefined}
          note={k ? `${count(k.active)} active` : undefined}
        />
        <Metric
          icon={<Wallet className="h-4 w-4" />}
          label="Inventory value"
          value={k ? currencyCompact(k.inventory_value) : undefined}
          note="at cost, all sites"
        />
        <Metric
          icon={<Trophy className="h-4 w-4" />}
          label="Best sellers"
          value={k ? count(k.best_sellers) : undefined}
          note={k ? `${currencyCompact(k.best_seller_revenue)} earned` : undefined}
          tone="success"
        />
        <Metric
          icon={<TrendingUp className="h-4 w-4" />}
          label="Growing"
          value={k ? count(k.growing) : undefined}
          note={data ? `over ${percent(data.definitions.growth_threshold * 100, 0)} up` : undefined}
          tone="info"
        />
        <Metric
          icon={<PackageX className="h-4 w-4" />}
          label="Stockout risk"
          value={k ? count(k.at_risk) : undefined}
          note={k ? `${count(k.critical)} already out` : undefined}
          tone={k && k.critical > 0 ? "danger" : "warning"}
        />
        <Metric
          icon={<Ban className="h-4 w-4" />}
          label="Capital stuck"
          value={k ? currencyCompact(k.dead_value + k.overstock_value) : undefined}
          note={k ? `${count(k.dead)} dead · ${count(k.overstocked)} overstocked` : undefined}
          tone="capacity"
        />
      </div>

      {/* ---------------- Distribution + workspaces ---------------- */}
      <div className="grid gap-4 xl:grid-cols-[21rem_1fr]">
        <HealthRing
          data={data}
          selected={filter}
          onSelect={(key) => setFilter((prev) => (prev === key ? null : key))}
        />
        <Workspaces
          data={data}
          days={days}
          selected={filter}
          onSelect={(key) => setFilter((prev) => (prev === key ? null : key))}
        />
      </div>

      {/* ---------------- The catalogue itself ---------------- */}
      <Catalogue
        rows={rows}
        loading={query.isLoading}
        days={days}
        filter={filter}
        onClear={() => setFilter(null)}
        total={data?.products.length ?? 0}
      />
    </>
  );
}

/* -------------------------------------------------------------------------- */
/* Bucket vocabulary — one place, so the ring, the badges and the cards agree.  */
/* -------------------------------------------------------------------------- */

const BUCKET: Record<
  Bucket,
  { label: string; ring: string; dot: string; soft: string; text: string; hint: string }
> = {
  critical: {
    label: "Out of stock",
    ring: "var(--color-danger)",
    dot: "bg-danger",
    soft: "bg-danger-soft",
    text: "text-danger",
    hint: "Selling, nothing on any shelf",
  },
  at_risk: {
    label: "Low cover",
    ring: "var(--color-warning)",
    dot: "bg-warning",
    soft: "bg-warning-soft",
    text: "text-warning",
    hint: "Under two weeks left",
  },
  dead: {
    label: "Dead",
    ring: "var(--color-ink-subtle)",
    dot: "bg-ink-subtle",
    soft: "bg-sunken",
    text: "text-ink-muted",
    hint: "No sale in two months",
  },
  overstocked: {
    label: "Overstocked",
    ring: "var(--color-capacity)",
    dot: "bg-capacity",
    soft: "bg-capacity-soft",
    text: "text-capacity",
    hint: "Over six months of cover",
  },
  growing: {
    label: "Growing",
    ring: "var(--color-info)",
    dot: "bg-info",
    soft: "bg-info-soft",
    text: "text-info",
    hint: "Demand up on last period",
  },
  healthy: {
    label: "Healthy",
    ring: "var(--color-success)",
    dot: "bg-success",
    soft: "bg-success-soft",
    text: "text-success",
    hint: "Selling, well stocked",
  },
};

/**
 * The filter predicates.
 *
 * Bucket filters are a straight match, because the server already assigned every
 * product exactly one. The workspace filters are NOT buckets — "best sellers" is
 * a ranking and "fastest growing" includes products whose bucket is something
 * more urgent — so each one restates the server's rule rather than guessing.
 */
function applyFilter(products: ProductRow[], filter: string | null): ProductRow[] {
  if (!filter) return products;
  if (filter in BUCKET) return products.filter((p) => p.bucket === filter);

  switch (filter) {
    case "best_sellers": {
      // Top 20 by revenue, matching the server. Products arrive already sorted
      // by revenue, so this is a slice rather than a re-sort.
      return products.filter((p) => p.revenue > 0).slice(0, 20);
    }
    case "growing":
      return products.filter((p) => p.growth !== null && p.growth > 0);
    case "at_risk":
      return products.filter((p) => p.bucket === "at_risk" || p.bucket === "critical");
    case "new": {
      const cutoff = Date.now() - 30 * 86_400_000;
      return products.filter((p) => new Date(p.created_at).getTime() >= cutoff);
    }
    case "discontinued":
      return products.filter((p) => p.status !== "active");
    default:
      return products;
  }
}

/* -------------------------------------------------------------------------- */

/** The distribution as one ring. Six arcs, each clickable, total in the middle.
 *  A ring rather than a bar chart because the question is "what proportion of my
 *  catalogue is in trouble", which is a part-to-whole with a total worth stating. */
function HealthRing({
  data,
  selected,
  onSelect,
}: {
  data?: ProductIntelligence;
  selected: string | null;
  onSelect: (key: string) => void;
}) {
  const distribution = data?.distribution ?? [];
  const total = distribution.reduce((sum, d) => sum + d.count, 0);

  const r = 54;
  const circumference = 2 * Math.PI * r;
  let offset = 0;

  const arcs = distribution.map((entry) => {
    const share = total > 0 ? entry.count / total : 0;
    // A hairline gap between arcs so two adjacent colours read as two segments
    // rather than one gradient. Subtracted from the arc, not added between.
    const length = Math.max(share * circumference - 1.5, 0);
    const arc = { ...entry, length, offset, share };
    offset += share * circumference;
    return arc;
  });

  const focused = selected && selected in BUCKET ? (selected as Bucket) : null;
  const focusedEntry = focused ? distribution.find((d) => d.key === focused) : null;

  return (
    <Band className="flex flex-col p-4">
      <h3 className="font-display text-lg font-bold">Catalogue health</h3>
      <p className="mt-0.5 text-2xs text-ink-subtle">
        Every product counted once, in its most urgent state.
      </p>

      <div className="relative mx-auto my-4 grid h-44 w-44 place-items-center">
        {total === 0 ? (
          <Skeleton className="h-44 w-44 rounded-full" />
        ) : (
          <>
            <svg viewBox="0 0 128 128" className="h-44 w-44 -rotate-90">
              <circle
                cx="64"
                cy="64"
                r={r}
                fill="none"
                stroke="var(--color-sunken)"
                strokeWidth="16"
              />
              {arcs.map((arc) =>
                arc.count === 0 ? null : (
                  <circle
                    key={arc.key}
                    cx="64"
                    cy="64"
                    r={r}
                    fill="none"
                    stroke={BUCKET[arc.key].ring}
                    strokeWidth={focused === arc.key ? 20 : 16}
                    strokeDasharray={`${arc.length} ${circumference - arc.length}`}
                    strokeDashoffset={-arc.offset}
                    opacity={focused && focused !== arc.key ? 0.25 : 1}
                    className="cursor-pointer transition-all"
                    onClick={() => onSelect(arc.key)}
                  />
                ),
              )}
            </svg>
            <div className="pointer-events-none absolute text-center">
              <p className="tnum text-3xl leading-none font-extrabold">
                {focusedEntry ? focusedEntry.count : total}
              </p>
              <p className="mt-1 text-2xs font-semibold text-ink-muted">
                {focused ? BUCKET[focused].label : "products"}
              </p>
            </div>
          </>
        )}
      </div>

      <ul className="flex flex-col gap-0.5">
        {distribution.map((entry) => {
          const active = selected === entry.key;
          return (
            <li key={entry.key}>
              <button
                type="button"
                onClick={() => onSelect(entry.key)}
                className={cn(
                  "flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left transition-colors",
                  active ? "bg-sunken" : "hover:bg-sunken/60",
                )}
              >
                <span className={cn("h-2 w-2 shrink-0 rounded-full", BUCKET[entry.key].dot)} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-semibold">
                    {BUCKET[entry.key].label}
                  </span>
                  <span className="block truncate text-2xs text-ink-subtle">
                    {BUCKET[entry.key].hint}
                  </span>
                </span>
                <span className="tnum shrink-0 text-sm font-bold">{entry.count}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </Band>
  );
}

/* -------------------------------------------------------------------------- */

/** Icon and tone per workspace. The tones deliberately echo the ring: the card
 *  for the overstocked group is violet because the violet arc is the overstocked
 *  arc, so the eye connects the two halves of the page without a legend. */
const WORKSPACE_STYLE: Record<string, { icon: React.ReactNode; chip: string }> = {
  best_sellers: {
    icon: <Trophy className="h-4 w-4" />,
    chip: "bg-success-soft text-success",
  },
  growing: {
    icon: <TrendingUp className="h-4 w-4" />,
    chip: "bg-info-soft text-info",
  },
  dead: { icon: <Ban className="h-4 w-4" />, chip: "bg-sunken text-ink-muted" },
  at_risk: {
    icon: <PackageX className="h-4 w-4" />,
    chip: "bg-danger-soft text-danger",
  },
  overstocked: {
    icon: <Boxes className="h-4 w-4" />,
    chip: "bg-capacity-soft text-capacity",
  },
  new: {
    icon: <Sparkles className="h-4 w-4" />,
    chip: "bg-accent-soft text-accent",
  },
  discontinued: {
    icon: <Activity className="h-4 w-4" />,
    chip: "bg-sunken text-ink-muted",
  },
};

/** What each workspace is worth, and what the number means. The value column
 *  changes meaning between cards — revenue for the ones about selling, capital
 *  for the ones about stock — so each card says which it is rather than leaving
 *  a bare figure to be misread. */
const WORKSPACE_UNIT: Record<string, string> = {
  best_sellers: "revenue",
  growing: "revenue",
  dead: "capital tied up",
  at_risk: "stock at risk",
  overstocked: "excess capital",
  new: "inventory value",
  discontinued: "inventory value",
};

function Workspaces({
  data,
  days,
  selected,
  onSelect,
}: {
  data?: ProductIntelligence;
  days: number;
  selected: string | null;
  onSelect: (key: string) => void;
}) {
  const workspaces = data?.workspaces ?? [];

  if (!data) {
    return (
      <div className="grid gap-3 sm:grid-cols-2 2xl:grid-cols-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-36 rounded-2xl" />
        ))}
      </div>
    );
  }

  return (
    <div className="grid content-start gap-3 sm:grid-cols-2 2xl:grid-cols-3">
      {workspaces.map((workspace) => {
        const active = selected === workspace.key;
        const empty = workspace.count === 0;
        const peak = Math.max(...workspace.sparkline, 1);
        const hasPage = WORKSPACE_PAGES.has(workspace.key);

        const className = cn(
          "flex flex-col rounded-2xl border bg-surface p-4 text-left transition-all",
          empty
            ? "cursor-default border-border opacity-60"
            : "cursor-pointer border-border shadow-sm hover:-translate-y-0.5 hover:border-accent-border hover:shadow-md",
          active && "border-accent-border ring-2 ring-accent/25",
        );

        const Card = ({ children }: { children: React.ReactNode }) =>
          hasPage && !empty ? (
            <Link
              to={`/products/workspace/${workspace.key}?days=${days}`}
              className={className}
            >
              {children}
            </Link>
          ) : (
            <button
              type="button"
              disabled={empty}
              onClick={() => onSelect(workspace.key)}
              className={className}
            >
              {children}
            </button>
          );

        return (
          <Card key={workspace.key}>
            <div className="flex items-center gap-2">
              <span
                className={cn(
                  "flex h-7 w-7 items-center justify-center rounded-lg",
                  WORKSPACE_STYLE[workspace.key]?.chip ?? "bg-accent-soft text-accent",
                )}
              >
                {WORKSPACE_STYLE[workspace.key]?.icon}
              </span>
              <span className="font-display text-sm font-bold">{workspace.label}</span>
              <span className="tnum ml-auto text-lg font-extrabold">
                {count(workspace.count)}
              </span>
            </div>

            {empty ? (
              // An honest empty state. "New products" reads zero because every
              // SKU here has been selling for years, which is a fact about the
              // catalogue rather than a hole in the page.
              <p className="mt-3 flex-1 text-2xs text-ink-subtle">
                Nothing in this group right now.
              </p>
            ) : (
              <>
                <p className="tnum mt-2.5 text-sm font-bold">
                  {currencyCompact(workspace.value)}
                  <span className="ml-1 text-2xs font-medium text-ink-subtle">
                    {WORKSPACE_UNIT[workspace.key]}
                  </span>
                </p>

                {/* The shape of the group: its largest members, tallest first.
                    Not a time series — there is no time axis here, and drawing
                    one would invent a trend. */}
                <div className="mt-2 flex h-7 items-end gap-[3px]">
                  {workspace.sparkline.map((value, i) => (
                    <span
                      key={i}
                      className="flex-1 rounded-sm bg-accent/25"
                      style={{ height: `${Math.max((value / peak) * 100, 6)}%` }}
                    />
                  ))}
                </div>

                {workspace.top_product && (
                  <p className="mt-2 truncate text-2xs text-ink-subtle">
                    Top: <span className="text-ink-muted">{workspace.top_product}</span>
                  </p>
                )}
              </>
            )}
          </Card>
        );
      })}
    </div>
  );
}

/** The groups that have a screen of their own. The other two -- new and
 *  discontinued -- have nothing a dedicated page would add, so their cards
 *  narrow the list in place instead of opening an emptier version of it. */
const WORKSPACE_PAGES = new Set([
  "best_sellers",
  "growing",
  "dead",
  "at_risk",
  "overstocked",
]);

/* -------------------------------------------------------------------------- */

function Catalogue({
  rows,
  loading,
  days,
  filter,
  onClear,
  total,
}: {
  rows: ProductRow[];
  loading: boolean;
  days: number;
  filter: string | null;
  onClear: () => void;
  total: number;
}) {
  const heading =
    filter && filter in BUCKET
      ? BUCKET[filter as Bucket].label
      : filter
        ? filter.replace(/_/g, " ")
        : "All products";

  return (
    <Band className="mt-4 flex flex-col overflow-hidden">
      <div className="flex flex-wrap items-center gap-3 border-b border-border px-4 py-3">
        <h3 className="font-display text-lg font-bold capitalize">{heading}</h3>
        <span className="tnum rounded-full bg-sunken px-2 py-0.5 text-2xs font-bold text-ink-muted">
          {count(rows.length)}
          {filter && ` of ${count(total)}`}
        </span>
        {filter && (
          <button
            type="button"
            onClick={onClear}
            className="text-2xs font-bold text-accent hover:underline"
          >
            Clear filter
          </button>
        )}
        <Link
          to="/products/all"
          className="ml-auto text-2xs font-bold text-accent hover:underline"
        >
          Search the full catalogue
        </Link>
      </div>

      {loading ? (
        <div className="flex flex-col gap-2 p-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-12 rounded-xl" />
          ))}
        </div>
      ) : rows.length === 0 ? (
        <p className="px-4 py-10 text-center text-sm text-ink-muted">
          No products in this group.
        </p>
      ) : (
        <ul className="divide-y divide-border">
          {rows.slice(0, 60).map((product) => (
            <li key={product.id}>
              <Link
                to={`/products/${product.id}?days=${days}`}
                className="flex items-center gap-3 px-4 py-2.5 transition-colors hover:bg-sunken/50"
              >
                <ProductMark sku={product.sku} category={product.category} />

                <div className="min-w-0 flex-[2]">
                  <p className="truncate text-sm font-semibold">{product.name}</p>
                  <p className="truncate text-2xs text-ink-subtle">
                    {product.sku}
                    {product.category && ` · ${product.category}`}
                  </p>
                </div>

                <span
                  className={cn(
                    "hidden shrink-0 rounded-full px-2 py-0.5 text-2xs font-bold sm:inline",
                    BUCKET[product.bucket].soft,
                    BUCKET[product.bucket].text,
                  )}
                >
                  {BUCKET[product.bucket].label}
                </span>

                <div className="hidden w-24 shrink-0 text-right md:block">
                  <p className="tnum text-sm font-bold">{count(product.on_hand)}</p>
                  <p className="text-2xs text-ink-subtle">on hand</p>
                </div>

                <div className="hidden w-24 shrink-0 text-right lg:block">
                  <p className="tnum text-sm font-bold">
                    {product.days_cover === null
                      ? "—"
                      : `${Math.round(product.days_cover)}d`}
                  </p>
                  <p className="text-2xs text-ink-subtle">cover</p>
                </div>

                <div className="w-28 shrink-0 text-right">
                  <p className="tnum text-sm font-bold">
                    {currencyCompact(product.revenue)}
                  </p>
                  <Growth value={product.growth} />
                </div>

                <ChevronRight className="hidden h-4 w-4 shrink-0 text-ink-subtle sm:block" />
              </Link>
            </li>
          ))}
        </ul>
      )}

      {rows.length > 60 && (
        <p className="border-t border-border px-4 py-2.5 text-2xs text-ink-subtle">
          Showing the 60 largest by revenue.{" "}
          <Link to="/products/all" className="font-bold text-accent">
            Search the full catalogue
          </Link>{" "}
          for the rest.
        </p>
      )}
    </Band>
  );
}

/** Growth against the previous window of the same length. Renders nothing
 *  definite when there was no previous window — a product with no history to
 *  compare against has not grown infinitely, it is simply new to the data. */
function Growth({ value }: { value: number | null }) {
  if (value === null) {
    return <p className="text-2xs text-ink-subtle">no prior period</p>;
  }
  const up = value >= 0;
  return (
    <p
      className={cn(
        "tnum flex items-center justify-end gap-0.5 text-2xs font-bold",
        up ? "text-success" : "text-danger",
      )}
    >
      {up ? (
        <ArrowUpRight className="h-3 w-3" />
      ) : (
        <ArrowDownRight className="h-3 w-3" />
      )}
      {percent(Math.abs(value) * 100, 0)}
    </p>
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
  value?: string;
  note?: string;
  tone?: "success" | "info" | "warning" | "danger" | "capacity";
}) {
  const chip =
    tone === "danger"
      ? "bg-danger-soft text-danger"
      : tone === "warning"
        ? "bg-warning-soft text-warning"
        : tone === "success"
          ? "bg-success-soft text-success"
          : tone === "info"
            ? "bg-info-soft text-info"
            : tone === "capacity"
              ? "bg-capacity-soft text-capacity"
              : "bg-accent-soft text-accent";

  return (
    <Band className="p-4">
      <span className={cn("flex h-8 w-8 items-center justify-center rounded-lg", chip)}>
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
      {note && <p className="mt-1.5 text-2xs text-ink-subtle">{note}</p>}
    </Band>
  );
}
