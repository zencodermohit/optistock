import { ArrowLeft, Download } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, Navigate, useParams, useSearchParams } from "react-router-dom";

import { ProductMark } from "@/components/products/ProductMark";
import { Band } from "@/components/ui/Band";
import { ErrorState, Skeleton } from "@/components/ui/states";
import { count, currencyCompact, percent } from "@/lib/format";
import {
  useProductIntelligence,
  type ProductIntelligence,
  type ProductRow,
} from "@/lib/queries";
import { cn } from "@/lib/utils";

/**
 * Layer 3 — one group, worked through.
 *
 * The hub already filters in place, so a separate screen has to earn itself. It
 * does that by asking a different question. The hub asks "how big is this
 * problem"; a workspace asks "what do I do about it", and the answer needs
 * columns the hub does not have — cumulative revenue share for best sellers,
 * capital tied up and for how long for dead stock, units short for stockout
 * risk, months to clear for overstock.
 *
 * One component, five configurations. Five files differing only in their
 * columns would drift apart within a month, and the fourth one would quietly
 * get a subtly different definition of the same word.
 */

type Row = ProductRow & { rank: number; cumulative: number };

interface Column {
  key: string;
  label: string;
  /** Right-aligned by default; names and labels read better left. */
  align?: "left";
  hideBelow?: "sm" | "md" | "lg";
  render: (row: Row, data: ProductIntelligence) => React.ReactNode;
}

interface Spec {
  label: string;
  question: string;
  /** What the total across the group means, stated because the same figure is
   *  revenue in one workspace and capital in another. */
  totalLabel: string;
  total: (rows: Row[]) => string;
  columns: Column[];
  empty: string;
}

/* -------------------------------------------------------------------------- */
/* Shared cells                                                                */
/* -------------------------------------------------------------------------- */

function Growth({ value }: { value: number | null }) {
  if (value === null) {
    return <span className="text-2xs text-ink-subtle">no prior period</span>;
  }
  return (
    <span
      className={cn(
        "tnum text-sm font-bold",
        value >= 0 ? "text-success" : "text-danger",
      )}
    >
      {value >= 0 ? "+" : "−"}
      {percent(Math.abs(value) * 100, 0)}
    </span>
  );
}

const REVENUE: Column = {
  key: "revenue",
  label: "Revenue",
  render: (r) => (
    <span className="tnum text-sm font-bold">{currencyCompact(r.revenue)}</span>
  ),
};

const ON_HAND: Column = {
  key: "on_hand",
  label: "On hand",
  hideBelow: "md",
  render: (r) => <span className="tnum text-sm">{count(r.on_hand)}</span>,
};

const COVER: Column = {
  key: "cover",
  label: "Cover",
  hideBelow: "sm",
  render: (r) => (
    <span
      className={cn(
        "tnum text-sm font-bold",
        r.days_cover !== null && r.days_cover <= 14 && "text-danger",
      )}
    >
      {r.days_cover === null ? "—" : `${Math.round(r.days_cover)}d`}
    </span>
  ),
};

/* -------------------------------------------------------------------------- */
/* The five configurations                                                     */
/* -------------------------------------------------------------------------- */

const SPECS: Record<string, Spec> = {
  best_sellers: {
    label: "Best sellers",
    question: "Which products earn the money, and how concentrated is that?",
    totalLabel: "revenue in this window",
    total: (rows) => currencyCompact(rows.reduce((s, r) => s + r.revenue, 0)),
    empty: "Nothing has sold in this window.",
    columns: [
      REVENUE,
      {
        key: "cumulative",
        label: "Running share",
        hideBelow: "md",
        // The Pareto line. A single product's revenue says little; the running
        // share says whether this catalogue is carried by five products or
        // fifty, which is the number that decides how much a stockout costs.
        render: (r) => (
          <span className="flex items-center justify-end gap-2">
            <span className="hidden h-1.5 w-16 overflow-hidden rounded-full bg-sunken lg:block">
              <span
                className="block h-full rounded-full bg-accent"
                style={{ width: `${Math.min(r.cumulative * 100, 100)}%` }}
              />
            </span>
            <span className="tnum text-sm">{percent(r.cumulative * 100, 0)}</span>
          </span>
        ),
      },
      {
        key: "units",
        label: "Units",
        hideBelow: "lg",
        render: (r) => <span className="tnum text-sm">{count(r.units_sold)}</span>,
      },
      COVER,
      {
        key: "growth",
        label: "Trend",
        hideBelow: "sm",
        render: (r) => <Growth value={r.growth} />,
      },
    ],
  },

  growing: {
    label: "Fastest growing",
    question: "What is accelerating, and is there enough stock behind it?",
    totalLabel: "revenue in this window",
    total: (rows) => currencyCompact(rows.reduce((s, r) => s + r.revenue, 0)),
    empty: "Nothing grew against the previous period.",
    columns: [
      {
        key: "growth",
        label: "Growth",
        render: (r) => <Growth value={r.growth} />,
      },
      {
        key: "units",
        label: "Units",
        hideBelow: "md",
        render: (r) => <span className="tnum text-sm">{count(r.units_sold)}</span>,
      },
      REVENUE,
      COVER,
      {
        key: "flag",
        label: "",
        hideBelow: "lg",
        // Growth plus thin cover is the expensive combination, and neither
        // column says it alone. Called out because a product growing into a
        // stockout is the one worth reordering first.
        render: (r) =>
          r.days_cover !== null && r.days_cover <= 30 ? (
            <span className="rounded-full bg-danger-soft px-2 py-0.5 text-2xs font-bold text-danger">
              Growing into a stockout
            </span>
          ) : null,
      },
    ],
  },

  dead: {
    label: "Dead inventory",
    question: "How much capital is standing still, and for how long has it been?",
    totalLabel: "capital tied up",
    total: (rows) =>
      currencyCompact(rows.reduce((s, r) => s + r.inventory_value, 0)),
    empty:
      "Nothing is dead. Every product in the catalogue has sold recently.",
    columns: [
      {
        key: "value",
        label: "Capital",
        render: (r) => (
          <span className="tnum text-sm font-bold">
            {currencyCompact(r.inventory_value)}
          </span>
        ),
      },
      {
        key: "cumulative",
        label: "Running share",
        hideBelow: "md",
        render: (r) => (
          <span className="tnum text-sm">{percent(r.cumulative * 100, 0)}</span>
        ),
      },
      ON_HAND,
      {
        key: "silent",
        label: "Last sold",
        render: (r) => (
          <span className="tnum text-sm font-bold text-danger">
            {r.days_since_sale === null
              ? "never"
              : `${count(r.days_since_sale)}d ago`}
          </span>
        ),
      },
      {
        key: "sites",
        label: "Sites",
        hideBelow: "lg",
        render: (r) => <span className="tnum text-sm">{count(r.sites)}</span>,
      },
    ],
  },

  at_risk: {
    label: "Stockout risk",
    question: "What runs out first, and how much is needed to cover a month?",
    totalLabel: "revenue at risk this window",
    total: (rows) => currencyCompact(rows.reduce((s, r) => s + r.revenue, 0)),
    empty: "Nothing is close to running out.",
    columns: [
      COVER,
      ON_HAND,
      {
        key: "rate",
        label: "Selling",
        hideBelow: "lg",
        render: (r) => (
          <span className="tnum text-sm">{r.daily_rate.toFixed(1)}/day</span>
        ),
      },
      {
        key: "short",
        label: "Short of 30d",
        // The actionable number. "11 days of cover" tells you there is a
        // problem; "order 240" tells you what to do, and it is the same fact.
        render: (r) => {
          const needed = Math.ceil(r.daily_rate * 30 - r.on_hand);
          return needed > 0 ? (
            <span className="tnum text-sm font-bold text-danger">
              {count(needed)}
            </span>
          ) : (
            <span className="text-2xs text-ink-subtle">covered</span>
          );
        },
      },
      REVENUE,
    ],
  },

  overstocked: {
    label: "Overstocked",
    question: "Where is the excess, and how long would it take to sell through?",
    totalLabel: "capital in excess stock",
    total: (rows) =>
      currencyCompact(rows.reduce((s, r) => s + r.inventory_value, 0)),
    empty: "Nothing is carrying more than six months of cover.",
    columns: [
      {
        key: "value",
        label: "Capital",
        render: (r) => (
          <span className="tnum text-sm font-bold">
            {currencyCompact(r.inventory_value)}
          </span>
        ),
      },
      COVER,
      ON_HAND,
      {
        key: "excess",
        label: "Excess over 90d",
        render: (r) => {
          const excess = Math.floor(r.on_hand - r.daily_rate * 90);
          return excess > 0 ? (
            <span className="tnum text-sm font-bold text-capacity">
              {count(excess)}
            </span>
          ) : (
            <span className="text-2xs text-ink-subtle">—</span>
          );
        },
      },
      {
        key: "clear",
        label: "Clears in",
        hideBelow: "lg",
        render: (r) =>
          r.days_cover === null ? (
            // No demand at all. "Never" is the honest answer and a far more
            // useful one than a blank cell or a very large number of months.
            <span className="text-2xs font-bold text-danger">never at this rate</span>
          ) : (
            <span className="tnum text-sm">
              {(r.days_cover / 30).toFixed(1)} months
            </span>
          ),
      },
    ],
  },
};

/* -------------------------------------------------------------------------- */

export function ProductWorkspace() {
  const { workspaceKey } = useParams<{ workspaceKey: string }>();
  const [params] = useSearchParams();

  const incoming = Number(params.get("days"));
  const [days, setDays] = useState([30, 90, 180].includes(incoming) ? incoming : 30);

  const spec = workspaceKey ? SPECS[workspaceKey] : undefined;
  const query = useProductIntelligence(days, workspaceKey);
  const data = query.data;

  // The running share needs the group total, so it is computed once here
  // rather than per row -- a per-row reduce over a 500-row list is quadratic
  // and the number would be identical.
  const rows = useMemo<Row[]>(() => {
    if (!data) return [];
    const basis = SPECS[workspaceKey ?? ""]?.totalLabel.includes("capital")
      ? (r: ProductRow) => r.inventory_value
      : (r: ProductRow) => r.revenue;
    const total = data.products.reduce((s, r) => s + basis(r), 0);
    let running = 0;
    return data.products.map((row, i) => {
      running += basis(row);
      return {
        ...row,
        rank: i + 1,
        cumulative: total > 0 ? running / total : 0,
      };
    });
  }, [data, workspaceKey]);

  if (!spec) return <Navigate to="/products" replace />;

  if (query.isError) {
    return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  }

  const card = data?.workspaces.find((w) => w.key === workspaceKey);

  return (
    <>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex items-start gap-4">
          <Link
            to="/products"
            className="mt-1 flex h-9 w-9 items-center justify-center rounded-xl border border-border bg-surface text-ink-muted transition-colors hover:text-ink"
            aria-label="Back to products"
          >
            <ArrowLeft className="h-4 w-4" />
          </Link>
          <div>
            <h1 className="text-2xl leading-tight font-semibold">{spec.label}</h1>
            <p className="mt-1.5 text-base text-ink-muted">{spec.question}</p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => downloadCsv(rows, workspaceKey ?? "workspace")}
            disabled={rows.length === 0}
            className="flex items-center gap-1.5 rounded-xl border border-border bg-surface px-3 py-2 text-xs font-bold text-ink-muted transition-colors hover:text-ink disabled:opacity-50"
          >
            <Download className="h-3.5 w-3.5" />
            CSV
          </button>
          <div className="flex items-center gap-1 rounded-xl border border-border bg-surface p-1">
            {[30, 90, 180].map((option) => (
              <button
                key={option}
                type="button"
                onClick={() => setDays(option)}
                className={cn(
                  "rounded-lg px-3 py-1.5 text-xs font-bold transition-colors",
                  days === option
                    ? "bg-accent text-on-accent"
                    : "text-ink-muted hover:text-ink",
                )}
              >
                {option}d
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Two figures, because a group's size means nothing without its share.
          "13 products" is a fact; "13 of 200, holding ₹23.5L" is a decision. */}
      <div className="mt-5 grid gap-3 sm:grid-cols-3">
        <Summary
          label="Products in this group"
          value={data ? count(rows.length) : undefined}
          note={data ? `of ${count(data.kpis.total)} in the catalogue` : undefined}
        />
        <Summary
          label={spec.totalLabel}
          value={data ? spec.total(rows) : undefined}
          note={
            data && data.kpis.inventory_value > 0 && spec.totalLabel.includes("capital")
              ? `${percent(
                  (rows.reduce((s, r) => s + r.inventory_value, 0) /
                    data.kpis.inventory_value) *
                    100,
                  1,
                )} of all inventory value`
              : undefined
          }
        />
        <Summary
          label="Largest"
          value={card?.top_product ?? undefined}
          note={data ? `over the last ${days} days` : undefined}
          small
        />
      </div>

      <Band className="mt-4 flex flex-col overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[44rem]">
            <thead>
              <tr className="border-b border-border">
                <th className="w-10 px-3 py-2.5 text-left text-2xs font-bold text-ink-subtle">
                  #
                </th>
                <th className="px-3 py-2.5 text-left text-2xs font-bold text-ink-subtle">
                  Product
                </th>
                {spec.columns.map((column) => (
                  <th
                    key={column.key}
                    className={cn(
                      "px-3 py-2.5 text-right text-2xs font-bold whitespace-nowrap text-ink-subtle",
                      column.hideBelow === "sm" && "hidden sm:table-cell",
                      column.hideBelow === "md" && "hidden md:table-cell",
                      column.hideBelow === "lg" && "hidden lg:table-cell",
                    )}
                  >
                    {column.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {query.isLoading ? (
                Array.from({ length: 8 }).map((_, i) => (
                  <tr key={i}>
                    <td colSpan={spec.columns.length + 2} className="px-3 py-2">
                      <Skeleton className="h-8 rounded-lg" />
                    </td>
                  </tr>
                ))
              ) : rows.length === 0 ? (
                <tr>
                  <td
                    colSpan={spec.columns.length + 2}
                    className="px-3 py-12 text-center text-sm text-ink-muted"
                  >
                    {spec.empty}
                  </td>
                </tr>
              ) : (
                rows.map((row) => (
                  <tr key={row.id} className="transition-colors hover:bg-sunken/50">
                    <td className="tnum px-3 py-2.5 text-2xs text-ink-subtle">
                      {row.rank}
                    </td>
                    <td className="px-3 py-2.5">
                      <Link
                        to={`/products/${row.id}?days=${days}`}
                        className="flex items-center gap-2.5"
                      >
                        <ProductMark sku={row.sku} category={row.category} size="sm" />
                        <span className="min-w-0">
                          <span className="block truncate text-sm font-semibold hover:text-accent">
                            {row.name}
                          </span>
                          <span className="block truncate text-2xs text-ink-subtle">
                            {row.sku}
                            {row.category && ` · ${row.category}`}
                          </span>
                        </span>
                      </Link>
                    </td>
                    {spec.columns.map((column) => (
                      <td
                        key={column.key}
                        className={cn(
                          "px-3 py-2.5 whitespace-nowrap",
                          column.align === "left" ? "text-left" : "text-right",
                          column.hideBelow === "sm" && "hidden sm:table-cell",
                          column.hideBelow === "md" && "hidden md:table-cell",
                          column.hideBelow === "lg" && "hidden lg:table-cell",
                        )}
                      >
                        {column.render(row, data!)}
                      </td>
                    ))}
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {data && (
          <p className="border-t border-border px-4 py-2.5 text-2xs text-ink-subtle">
            {definitionFor(workspaceKey ?? "", data)}
          </p>
        )}
      </Band>

      <nav className="mt-4 flex flex-wrap gap-2">
        {Object.entries(SPECS)
          .filter(([key]) => key !== workspaceKey)
          .map(([key, other]) => (
            <Link
              key={key}
              to={`/products/workspace/${key}?days=${days}`}
              className="rounded-xl border border-border bg-surface px-3 py-2 text-xs font-bold text-ink-muted transition-colors hover:border-accent-border hover:text-accent"
            >
              {other.label}
            </Link>
          ))}
      </nav>
    </>
  );
}

/** Every workspace states the rule that put a product in it. A list whose
 *  membership rule is hidden is a list nobody can argue with, and these rules
 *  are thresholds somebody will eventually want to change. */
function definitionFor(key: string, data: ProductIntelligence): string {
  const d = data.definitions;
  switch (key) {
    case "best_sellers":
      return `The twenty products with the highest revenue over the last ${data.range_days} days. Running share is cumulative, in that order.`;
    case "growing":
      return `Demand up against the previous ${data.range_days} days. The hub counts only growth over ${percent(d.growth_threshold * 100, 0)} as a state; this list shows every product that grew at all.`;
    case "dead":
      return `No sale in ${d.dead_days} days, with stock still on a shelf. A discontinued line at zero costs nothing and is not counted.`;
    case "at_risk":
      return `${d.at_risk_cover_days} days of cover or less at the current rate, including products already at zero. "Short of 30d" is what it would take to reach a month of cover.`;
    case "overstocked":
      return `More than ${d.overstock_cover_days} days of cover. Excess is measured against a ninety-day target, which is a choice rather than a law.`;
    default:
      return d.note;
  }
}

function Summary({
  label,
  value,
  note,
  small,
}: {
  label: string;
  value?: string;
  note?: string;
  small?: boolean;
}) {
  return (
    <Band className="p-4">
      <p className="eyebrow">{label}</p>
      {value === undefined ? (
        <Skeleton className="mt-1.5 h-7 w-24" />
      ) : (
        <p
          className={cn(
            "tnum mt-1 leading-tight font-extrabold",
            small ? "truncate text-base" : "text-2xl",
          )}
        >
          {value}
        </p>
      )}
      {note && <p className="mt-1.5 text-2xs text-ink-subtle">{note}</p>}
    </Band>
  );
}

/** Every measure, not only the visible columns.
 *
 *  The table hides columns on narrow screens and shows different ones per
 *  workspace; a file that inherited those choices would mean a download taken
 *  on a phone was missing data a laptop would have included. A spreadsheet is
 *  where somebody goes to ask a question the screen did not answer, so it
 *  carries the whole row and the rank the workspace put it in. */
function downloadCsv(rows: Row[], name: string) {
  const header = ["Rank", "SKU", "Product", "Category", "On hand", "Days cover", "Units sold", "Revenue", "Inventory value", "Growth"];
  const lines = rows.map((r) =>
    [
      r.rank,
      r.sku,
      r.name,
      r.category ?? "",
      r.on_hand,
      r.days_cover ?? "",
      r.units_sold,
      r.revenue,
      r.inventory_value,
      r.growth ?? "",
    ]
      .map((cell) => {
        const text = String(cell);
        return text.includes(",") || text.includes('"')
          ? `"${text.replace(/"/g, '""')}"`
          : text;
      })
      .join(","),
  );

  const blob = new Blob([[header.join(","), ...lines].join("\n")], {
    type: "text/csv;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `optistock-${name}.csv`;
  link.click();
  URL.revokeObjectURL(url);
}
