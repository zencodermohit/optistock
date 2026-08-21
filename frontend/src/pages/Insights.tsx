import { ChevronDown, Sparkles, Target } from "lucide-react";
import { useState } from "react";

import { PageHeader } from "@/components/layout/AppShell";
import { AbcBadge, Badge } from "@/components/ui/Badge";
import { Band, BandHeader } from "@/components/ui/Band";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states";
import { count, currency, percent } from "@/lib/format";
import {
  useForecastAccuracy,
  useSuggestions,
  type ScoredForecast,
  type Suggestion,
} from "@/lib/queries";
import { cn } from "@/lib/utils";

export function Insights() {
  const suggestions = useSuggestions();
  const accuracy = useForecastAccuracy();

  const summary = accuracy.data?.summary;
  const rows = suggestions.data?.data ?? [];

  return (
    <>
      <PageHeader
        title="Insights"
        description="What the forecast concluded, the arithmetic behind each conclusion, and how well it has held up."
      />

      {/* Accuracy first. A page of recommendations with no error rate is a page
          asking to be trusted on the strength of having been built. */}
      <Band className="mb-4">
        <BandHeader
          label="Forecast accuracy"
          action={
            summary?.scored ? (
              <span className="font-mono text-2xs tracking-wider text-ink-subtle uppercase">
                {count(summary.scored)} predictions scored
              </span>
            ) : null
          }
        />

        {accuracy.isPending ? (
          <div className="h-28" />
        ) : accuracy.isError ? (
          <ErrorState error={accuracy.error} onRetry={() => accuracy.refetch()} />
        ) : !summary?.scored ? (
          <EmptyState
            icon={<Target className="h-5 w-5" />}
            title="Nothing has been scored yet"
            description="A forecast cannot be graded until the window it predicted has finished. The first results appear one horizon after the pipeline starts running."
          />
        ) : (
          <>
            <div className="grid gap-px bg-border sm:grid-cols-4">
              <Figure
                label="Weighted error"
                value={percent(summary.weighted_ape, 1)}
                hint="of units actually sold"
              />
              <Figure
                label="Average miss"
                value={`${(summary.mae ?? 0).toFixed(1)}`}
                hint="units per prediction"
              />
              <Figure
                label="Within 20%"
                value={percent(summary.within_20_pct, 0)}
                hint="of predictions"
              />
              <Figure
                label="Bias"
                value={biasLabel(summary.total_forecast, summary.total_actual)}
                hint={`${count(summary.total_forecast)} forecast vs ${count(summary.total_actual)} sold`}
              />
            </div>

            <div className="border-t border-border px-4 py-3">
              <p className="max-w-3xl text-xs text-ink-muted">
                Error is measured as the total units missed divided by the total
                units sold, not as the average of per-product percentages.
                Textbook MAPE divides by each actual, so a product forecast at 2
                that sold 1 scores 100% error and one that sold nothing is
                undefined — a catalogue of slow movers would report a terrible
                figure driven by the rows that matter least.
              </p>
            </div>

            {accuracy.data?.worst?.length ? (
              <div className="border-t border-border">
                <p className="px-4 pt-3 eyebrow">Biggest misses</p>
                <ul className="mt-1 pb-2">
                  {accuracy.data.worst.slice(0, 6).map((run, index) => (
                    <MissRow key={run.id} run={run} banded={index % 2 === 1} />
                  ))}
                </ul>
              </div>
            ) : null}
          </>
        )}
      </Band>

      <Band>
        <BandHeader
          label="Reorder suggestions"
          action={
            <span className="font-mono text-2xs tracking-wider text-ink-subtle uppercase">
              {count(suggestions.data?.total ?? 0)} open
            </span>
          }
        />

        {suggestions.isPending ? (
          <TableSkeleton rows={6} cols={4} />
        ) : suggestions.isError ? (
          <ErrorState
            error={suggestions.error}
            onRetry={() => suggestions.refetch()}
          />
        ) : rows.length === 0 ? (
          <EmptyState
            icon={<Sparkles className="h-5 w-5" />}
            title="Nothing to reorder"
            description="Forecast demand is covered by stock on hand for every product. Suggestions appear after the nightly analysis finds a shortfall."
          />
        ) : (
          <ul>
            {rows.map((row, index) => (
              <SuggestionRow
                key={row.id}
                suggestion={row}
                banded={index % 2 === 1}
              />
            ))}
          </ul>
        )}
      </Band>
    </>
  );
}

function SuggestionRow({
  suggestion,
  banded,
}: {
  suggestion: Suggestion;
  banded: boolean;
}) {
  const [open, setOpen] = useState(false);

  // Computed overnight, so stock has moved since. "Overtaken" means the
  // forecast is now covered by what is on hand -- NOT that on-hand exceeds the
  // suggested quantity, which it almost always does: the suggestion is already
  // net of stock, so 19 on hand against a suggestion of 5 is the arithmetic
  // working, not a stale row.
  const forecastQuantity = Number(suggestion.evidence.forecast_quantity ?? 0);
  const overtaken =
    forecastQuantity > 0 && suggestion.quantity_on_hand >= forecastQuantity;

  return (
    <li className={cn(banded && "bg-sunken/60")}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full flex-wrap items-center gap-x-4 gap-y-1 px-4 py-2.5 text-left hover:bg-accent-soft/60"
      >
        <span className="tnum w-32 shrink-0 text-2xs text-ink-subtle">
          {suggestion.sku}
        </span>
        <span className="w-8 shrink-0">
          <AbcBadge value={suggestion.abc_class} />
        </span>
        {/* basis-40: flex-1 alone implies basis-0, which lets the fixed
            columns beside it squeeze this one to a few characters on a phone. */}
        <span className="min-w-0 flex-1 basis-40">
          <span className="font-medium">{suggestion.product_name}</span>
          <span className="ml-2 text-xs text-ink-muted">
            {suggestion.warehouse_name}
          </span>
        </span>

        <span className="shrink-0 text-right">
          <span className="tnum font-medium">
            {count(suggestion.suggested_quantity)}
          </span>
          <span className="ml-1 text-2xs text-ink-subtle">
            {suggestion.suggested_quantity === 1 ? "unit" : "units"}
          </span>
        </span>
        <span className="w-24 shrink-0 text-right">
          <span className="tnum text-sm text-ink-muted">
            {currency(suggestion.estimated_cost)}
          </span>
        </span>
        {/* w-24, not w-16. The column is fixed so the values line up down the
            list, but 64px was narrower than the longest label it has to hold
            ("patchy" needs 80), so that word was clipped at every screen size,
            desktop included. */}
        <span className="w-24 shrink-0 text-right">
          <Confidence score={suggestion.confidence_score} />
        </span>
        <ChevronDown
          className={cn(
            "h-4 w-4 shrink-0 text-ink-subtle transition-transform",
            open && "rotate-180",
          )}
        />
      </button>

      {open && (
        <div className="border-t border-border px-4 py-3 pl-40">
          <p className="max-w-2xl text-sm text-ink-muted">
            {suggestion.business_reasoning}
          </p>

          {/* The inputs, not a paraphrase of them. Anyone doubting the number
              can redo the arithmetic from this. */}
          <dl className="mt-3 flex flex-wrap gap-x-6 gap-y-2">
            {Object.entries(suggestion.evidence).map(([key, value]) => (
              <div key={key} className="flex items-baseline gap-1.5">
                <dt className="font-mono text-2xs text-ink-subtle">
                  {key.replace(/_/g, " ")}
                </dt>
                <dd className="tnum text-xs">{String(value)}</dd>
              </div>
            ))}
          </dl>

          <p className="mt-3 text-2xs text-ink-subtle">
            {overtaken
              ? `Stock has since reached ${count(suggestion.quantity_on_hand)} units, which already covers the forecast — this suggestion has been overtaken.`
              : `${count(suggestion.quantity_on_hand)} on hand now, against forecast demand of ${count(forecastQuantity)}.`}{" "}
            Produced by {suggestion.source.replace(/_/g, " ")}.
          </p>
        </div>
      )}
    </li>
  );
}

function MissRow({ run, banded }: { run: ScoredForecast; banded: boolean }) {
  return (
    <li
      className={cn(
        "flex flex-wrap items-baseline gap-x-4 gap-y-1 px-4 py-1.5",
        banded && "bg-sunken/60",
      )}
    >
      <span className="tnum w-32 shrink-0 text-2xs text-ink-subtle">
        {run.sku}
      </span>
      <span className="min-w-0 flex-1 truncate text-sm">{run.product_name}</span>
      <span className="font-mono text-2xs text-ink-muted">
        forecast <span className="tnum text-ink">{count(run.forecast_quantity)}</span>
        {" · "}
        sold <span className="tnum text-ink">{count(run.actual_quantity)}</span>
      </span>
      <Badge tone={run.direction === "over" ? "warning" : "neutral"}>
        {run.direction} by {count(run.absolute_error)}
      </Badge>
    </li>
  );
}

/**
 * Named for what it is. This is a data-density score -- the share of days in the
 * window that had any sales -- and not a model probability, so it is never
 * shown as a bare percentage that would read as one.
 */
function Confidence({ score }: { score: number }) {
  const label = score >= 66 ? "dense" : score >= 33 ? "patchy" : "sparse";
  return (
    <span className="inline-flex items-center gap-1.5" title={`${score}/100 of days in the window had sales`}>
      <span className="h-1 w-8 overflow-hidden rounded-full bg-border-strong">
        <span
          className={cn(
            "block h-full rounded-full",
            score >= 66 ? "bg-accent" : "bg-ink-subtle",
          )}
          style={{ width: `${score}%` }}
        />
      </span>
      <span className="font-mono text-2xs text-ink-subtle">{label}</span>
    </span>
  );
}

function Figure({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint: string;
}) {
  return (
    <div className="bg-surface px-4 py-3">
      <p className="eyebrow">{label}</p>
      <p className="tnum mt-1.5 text-2xl leading-none font-medium">{value}</p>
      <p className="mt-1.5 text-2xs text-ink-subtle">{hint}</p>
    </div>
  );
}

function biasLabel(forecast: number, actual: number): string {
  if (!actual) return "—";
  const ratio = (forecast - actual) / actual;
  if (Math.abs(ratio) < 0.02) return "none";
  return `${ratio > 0 ? "over" : "under"} ${Math.abs(ratio * 100).toFixed(0)}%`;
}
