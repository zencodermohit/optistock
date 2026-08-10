import { useState } from "react";

import { PageHeader } from "@/components/layout/AppShell";
import { Badge } from "@/components/ui/Badge";
import { Band, BandHeader } from "@/components/ui/Band";
import {
  useStockoutRisk,
  type StockoutRisk as Risk,
} from "@/lib/queries";
import { cn } from "@/lib/utils";

/**
 * What runs out first.
 *
 * The Inventory screen already answers "what is below its reorder point". This
 * one exists because that is the wrong question: a reorder point is a static
 * number typed in once, and demand is not. Two hundred units selling forty a
 * day is an emergency, two hundred selling one a day is fine, and a threshold
 * of fifty flags the second while missing the first.
 *
 * So the ranking is by days remaining, and every row shows its working. The
 * four columns before the prediction — on hand, reorder point, usage, days —
 * are the four a stock controller would ask for before believing the fifth. A
 * forecast a person cannot check is one they will either over-trust or ignore.
 *
 * Urgency is carried by a left border rather than a filled row. A page of
 * coloured backgrounds reads as an alarm and stops meaning anything by the
 * third glance; a rule in the margin lets the eye find the critical rows
 * without the table shouting.
 */

const BANDS: {
  key: Risk["severity"];
  label: string;
  rule: string;
  tone: "danger" | "warning" | "neutral" | "success";
}[] = [
  { key: "critical", label: "Critical", rule: "border-l-danger", tone: "danger" },
  { key: "warning", label: "Warning", rule: "border-l-warning", tone: "warning" },
  { key: "watch", label: "Watch", rule: "border-l-border-strong", tone: "neutral" },
  { key: "ok", label: "Healthy", rule: "border-l-transparent", tone: "success" },
  { key: "idle", label: "No usage", rule: "border-l-transparent", tone: "neutral" },
];

const RULE = Object.fromEntries(BANDS.map((b) => [b.key, b.rule])) as Record<
  Risk["severity"],
  string
>;
const TONE = Object.fromEntries(BANDS.map((b) => [b.key, b.tone])) as Record<
  Risk["severity"],
  "danger" | "warning" | "neutral" | "success"
>;

export function StockoutRisk() {
  const [filter, setFilter] = useState<Risk["severity"] | "all">("all");
  const query = useStockoutRisk();

  const rows = query.data?.data ?? [];
  const summary = query.data?.summary;
  const visible = filter === "all" ? rows : rows.filter((r) => r.severity === filter);

  return (
    <>
      <PageHeader
        title="Stockout risk"
        description="When each line runs out at its current sales rate — not whether it is under a threshold somebody set once."
      />

      <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Figure
          label="Running out within 3 weeks"
          value={summary ? summary.at_risk : "—"}
          tone={summary && summary.at_risk > 0 ? "danger" : "neutral"}
        />
        <Figure
          label="Critical (under 7 days)"
          value={summary ? summary.counts.critical : "—"}
          tone={summary && summary.counts.critical > 0 ? "danger" : "neutral"}
        />
        <Figure
          label="Soonest"
          value={
            summary?.soonest
              ? `${summary.soonest.days_remaining.toFixed(0)}d`
              : "—"
          }
          hint={summary?.soonest?.sku}
        />
        <Figure
          label="Lines with no recorded sales"
          value={summary ? summary.counts.idle : "—"}
          hint="unmeasured, not safe"
        />
      </div>

      <Band>
        <BandHeader
          label="By urgency"
          description={
            query.data
              ? `Velocity measured over the last ${query.data.lookback_days} days, divided by the whole window rather than by the days that happened to have sales. Order quantity is EOQ, assuming ${query.data.assumptions.lead_time_days}-day lead time, ${query.data.assumptions.order_cost.toLocaleString()} per order and ${(query.data.assumptions.holding_cost_rate * 100).toFixed(0)}% annual holding cost.`
              : undefined
          }
          action={
            <div className="flex flex-wrap gap-1">
              <FilterChip
                active={filter === "all"}
                onClick={() => setFilter("all")}
              >
                All
              </FilterChip>
              {BANDS.map((band) => (
                <FilterChip
                  key={band.key}
                  active={filter === band.key}
                  onClick={() => setFilter(band.key)}
                >
                  {band.label}
                  {summary ? ` ${summary.counts[band.key] ?? 0}` : ""}
                </FilterChip>
              ))}
            </div>
          }
        />

        {query.isLoading ? (
          <p className="px-4 py-10 text-sm text-ink-subtle">Loading…</p>
        ) : visible.length === 0 ? (
          <p className="px-4 py-10 text-sm text-ink-muted">
            Nothing in this band.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left">
                  <Th>Product</Th>
                  <Th align="right">On hand</Th>
                  <Th align="right">Reorder pt</Th>
                  <Th align="right">Usage/day</Th>
                  <Th align="right">Days left</Th>
                  <Th>Runs out</Th>
                  <Th align="right">Order</Th>
                  <Th align="right">Reorder at</Th>
                  <Th>Confidence</Th>
                </tr>
              </thead>
              <tbody>
                {visible.map((row) => (
                  <tr
                    key={`${row.product_id}-${row.warehouse_id}`}
                    className={cn(
                      "border-b border-border border-l-2 last:border-b-0",
                      "even:bg-sunken/40",
                      RULE[row.severity],
                    )}
                  >
                    <td className="px-3 py-2">
                      <div className="flex items-center gap-2">
                        <span className="tnum font-medium">{row.sku}</span>
                        <Badge tone={TONE[row.severity]}>{row.severity}</Badge>
                      </div>
                      <p className="mt-0.5 text-2xs text-ink-muted">
                        {row.product_name} · {row.warehouse_name}
                      </p>
                      {/* The server's sentence, not the browser's. Written once
                          so this table, the API and the assistant cannot
                          disagree about what a row means. */}
                      <p className="mt-1 max-w-xl text-2xs leading-relaxed text-ink-subtle">
                        {row.explanation}
                      </p>
                    </td>
                    <Td align="right">{row.on_hand.toLocaleString()}</Td>
                    <Td align="right" muted>
                      {row.reorder_point > 0 ? row.reorder_point.toLocaleString() : "—"}
                    </Td>
                    <Td align="right">{row.daily_usage.toFixed(1)}</Td>
                    <Td align="right">
                      {row.days_remaining === null ? (
                        <span className="text-ink-subtle">—</span>
                      ) : (
                        <span
                          className={cn(
                            row.severity === "critical" && "font-semibold text-danger",
                            row.severity === "warning" && "text-warning",
                          )}
                        >
                          {row.days_remaining.toFixed(0)}
                        </span>
                      )}
                    </Td>
                    <Td muted>{row.stockout_date ?? "—"}</Td>
                    {/* What to do about it. EOQ balances the cost of ordering
                        against the cost of holding; the reorder point covers
                        the lead time plus the days busier than average. Both
                        are blank rather than zero where there is no demand or
                        no unit cost to optimise against. */}
                    <Td align="right">
                      {row.order_quantity != null ? (
                        <span className="font-medium">
                          {row.order_quantity.toLocaleString()}
                        </span>
                      ) : (
                        <span className="text-ink-subtle">—</span>
                      )}
                    </Td>
                    <Td align="right" muted>
                      {row.suggested_reorder_point != null
                        ? row.suggested_reorder_point.toLocaleString()
                        : "—"}
                    </Td>
                    <Td muted>
                      {row.confidence}
                      <span className="ml-1 text-ink-subtle">
                        ({row.active_days}/{row.lookback_days}d)
                      </span>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Band>
    </>
  );
}

function Figure({
  label,
  value,
  hint,
  tone = "neutral",
}: {
  label: string;
  value: string | number;
  hint?: string;
  tone?: "danger" | "neutral";
}) {
  return (
    <Band className="p-3">
      <p className="eyebrow">{label}</p>
      <p
        className={cn(
          "tnum mt-1 text-2xl leading-none font-semibold",
          tone === "danger" && "text-danger",
        )}
      >
        {value}
      </p>
      {hint && <p className="mt-1 text-2xs text-ink-subtle">{hint}</p>}
    </Band>
  );
}

function FilterChip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded-sm border px-2 py-0.5 font-mono text-2xs uppercase transition-colors",
        active
          ? "border-accent bg-accent text-white"
          : "border-border bg-surface text-ink-muted hover:border-accent-border",
      )}
    >
      {children}
    </button>
  );
}

function Th({
  children,
  align = "left",
}: {
  children: React.ReactNode;
  align?: "left" | "right";
}) {
  return (
    <th
      className={cn(
        "px-3 py-2 font-mono text-2xs font-medium tracking-wide text-ink-subtle uppercase",
        align === "right" && "text-right",
      )}
    >
      {children}
    </th>
  );
}

function Td({
  children,
  align = "left",
  muted,
}: {
  children: React.ReactNode;
  align?: "left" | "right";
  muted?: boolean;
}) {
  return (
    <td
      className={cn(
        "tnum px-3 py-2 align-top",
        align === "right" && "text-right",
        muted && "text-ink-muted",
      )}
    >
      {children}
    </td>
  );
}
