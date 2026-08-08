import { AlertTriangle, ArrowRight, Boxes, PackageX } from "lucide-react";
import { Link } from "react-router-dom";

import { PageHeader } from "@/components/layout/AppShell";
import { Band } from "@/components/ui/Band";
import { DayBars } from "@/components/ui/DayBars";
import { ErrorState, MetricSkeleton } from "@/components/ui/states";
import {
  count,
  currency,
  currencyCompact,
  percentDelta,
  relativeTime,
} from "@/lib/format";
import { useOverview } from "@/lib/queries";
import { cn } from "@/lib/utils";

export function Overview() {
  const overview = useOverview(30);
  const data = overview.data;

  if (overview.isError) {
    return (
      <>
        <PageHeader title="Overview" />
        <Band>
          <ErrorState error={overview.error} onRetry={() => overview.refetch()} />
        </Band>
      </>
    );
  }

  const trading = data?.trading;
  const stock = data?.stock;
  const alerts = data?.alerts ?? {};
  const openAlerts =
    (alerts.critical ?? 0) + (alerts.warning ?? 0) + (alerts.info ?? 0);

  return (
    <>
      <PageHeader
        title="Overview"
        description={
          data
            ? `Trading over the last ${data.range_days} days, against the ${trading?.comparison_days} before it.`
            : "Trading, stock position and anything that needs attention."
        }
      />

      {/* The headline. One number gets to be big; the rest support it. */}
      <div className="mb-4 grid gap-3 lg:grid-cols-3">
        {overview.isPending ? (
          <>
            <MetricSkeleton />
            <MetricSkeleton />
            <MetricSkeleton />
          </>
        ) : (
          <>
            <Band className="p-4 lg:col-span-1">
              <p className="eyebrow">Revenue, last {data?.range_days ?? 30} days</p>
              <p className="mt-2 font-display text-4xl leading-none font-semibold">
                {currencyCompact(trading?.revenue ?? 0)}
              </p>
              <p className="mt-2 text-2xs text-ink-muted">
                {trading?.revenue_change_pct == null ? (
                  "No prior period to compare against"
                ) : (
                  <>
                    <span
                      className={cn(
                        "tnum font-medium",
                        trading.revenue_change_pct >= 0
                          ? "text-success"
                          : "text-warning",
                      )}
                    >
                      {percentDelta(trading.revenue_change_pct)}
                    </span>{" "}
                    on the previous {trading.comparison_days} days
                  </>
                )}
              </p>
              <dl className="mt-4 grid grid-cols-2 gap-3 border-t border-border pt-3">
                <Pair label="Orders" value={count(trading?.orders ?? 0)} />
                <Pair label="Units sold" value={count(trading?.units_sold ?? 0)} />
              </dl>
            </Band>

            <Band className="p-4 lg:col-span-2">
              <DayBars
                label="Revenue per day"
                points={(data?.series ?? []).map((d) => ({
                  date: d.date,
                  value: d.revenue,
                }))}
                format={(v) => currency(v)}
                height="h-36"
              />
            </Band>
          </>
        )}
      </div>

      <div className="grid gap-3 lg:grid-cols-3">
        {/* self-start so the band hugs its chart. Left to stretch, it matches
            the height of the two stacked cards beside it and leaves a couple
            of hundred pixels of empty paper under a 5rem chart. */}
        <Band className="self-start p-4 lg:col-span-2">
          {overview.isPending ? (
            <div className="h-20" />
          ) : (
            <DayBars
              label="Stock movements per day"
              points={(data?.series ?? []).map((d) => ({
                date: d.date,
                value: d.stock_movements,
              }))}
              format={(v) => `${count(v)}`}
              tone="muted"
              height="h-20"
            />
          )}
        </Band>

        <div className="grid gap-3">
          <Band className="p-4">
            <p className="eyebrow">Stock position</p>
            <p className="mt-2 font-display text-2xl leading-none font-semibold">
              {currencyCompact(stock?.value_at_cost ?? 0)}
            </p>
            {/* Named, because "stock value" silently means retail in half the
                systems that report it, and the two differ by the margin. */}
            <p className="mt-1 text-2xs text-ink-subtle">at cost</p>
            <dl className="mt-4 grid grid-cols-2 gap-3 border-t border-border pt-3">
              <Pair label="Stock lines" value={count(stock?.lines ?? 0)} />
              <Pair label="Units held" value={count(stock?.units ?? 0)} />
            </dl>
          </Band>

          <Band className="p-4">
            <p className="eyebrow">Needs attention</p>
            <ul className="mt-3 space-y-2">
              <Need
                icon={<PackageX className="h-3.5 w-3.5" />}
                label="Out of stock"
                value={stock?.out ?? 0}
                tone="danger"
              />
              <Need
                icon={<Boxes className="h-3.5 w-3.5" />}
                label="Below reorder point"
                value={stock?.low ?? 0}
                tone="warning"
              />
              <Need
                icon={<AlertTriangle className="h-3.5 w-3.5" />}
                label="Open alerts"
                value={openAlerts}
                tone={alerts.critical ? "danger" : "warning"}
              />
            </ul>
            <Link
              to="/alerts"
              className="mt-4 inline-flex items-center gap-1 text-xs text-accent underline-offset-2 hover:underline"
            >
              Review alerts
              <ArrowRight className="h-3 w-3" />
            </Link>
          </Band>
        </div>
      </div>

      {/* Said out loud rather than implied. These figures come from a read
          model a background worker maintains, so they are current to within a
          second, not to the millisecond -- and a dashboard that cannot say how
          stale it is invites you to assume it is live. */}
      {data?.projection?.updated_at && (
        <p className="mt-4 text-2xs text-ink-subtle">
          Trading figures from the daily projection, last updated{" "}
          {relativeTime(data.projection.updated_at)}. Stock position is queried
          live.
        </p>
      )}
    </>
  );
}

function Pair({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-2xs text-ink-subtle">{label}</dt>
      <dd className="tnum mt-0.5 text-lg font-medium">{value}</dd>
    </div>
  );
}

function Need({
  icon,
  label,
  value,
  tone,
}: {
  icon: React.ReactNode;
  label: string;
  value: number;
  tone: "danger" | "warning";
}) {
  const quiet = value === 0;
  return (
    <li className="flex items-center gap-2.5">
      <span
        className={cn(
          "flex h-6 w-6 shrink-0 items-center justify-center rounded-sm border",
          // Zero is not a problem, so it does not get a colour. Only what
          // needs doing is inked.
          quiet
            ? "border-border bg-sunken text-ink-subtle"
            : tone === "danger"
              ? "border-danger/25 bg-danger-soft text-danger"
              : "border-warning/25 bg-warning-soft text-warning",
        )}
      >
        {icon}
      </span>
      <span className="flex-1 text-sm">{label}</span>
      <span
        className={cn(
          "tnum font-medium",
          quiet
            ? "text-ink-subtle"
            : tone === "danger"
              ? "text-danger"
              : "text-warning",
        )}
      >
        {count(value)}
      </span>
    </li>
  );
}
