import {
  AlertTriangle,
  Check,
  Clock,
  Pencil,
  ShieldCheck,
  X,
} from "lucide-react";
import { useState } from "react";

import { PageHeader } from "@/components/layout/AppShell";
import { Badge } from "@/components/ui/Badge";
import { Band, BandHeader } from "@/components/ui/Band";
import { Button } from "@/components/ui/Button";
import {
  useAssistantActions,
  useDecideAction,
  type AssistantAction,
} from "@/lib/queries";
import { cn } from "@/lib/utils";

/**
 * Where the assistant's suggestions wait for a person.
 *
 * The screen has one job and it is a job of framing: make it obvious that
 * nothing here has happened. Everything on this page is in the conditional
 * tense until someone clicks, and the design says so — proposals are rendered
 * as a quotation of what the model asked for, with the numbers it based that on
 * sitting next to it, rather than as a record of an order.
 *
 * The amend field is the part worth defending. It would be simpler to offer
 * approve and reject and nothing else, but the realistic outcome of a good
 * suggestion is "yes, but forty, not two hundred" — and a workflow that cannot
 * express that turns every partial agreement into a rejection and a manual
 * re-entry. Amending also produces the most useful record in the system: the
 * gap between what the machine wanted and what the human signed.
 */
export function Approvals() {
  const actions = useAssistantActions();
  const pending = (actions.data?.actions ?? []).filter(
    (a) => a.status === "proposed" && a.is_actionable,
  );
  const settled = (actions.data?.actions ?? []).filter(
    (a) => a.status !== "proposed" || !a.is_actionable,
  );

  return (
    <>
      <PageHeader
        title="Approvals"
        description="Purchase orders the assistant has suggested. Nothing here is ordered until you say so."
      />

      <Band className="mb-4 p-4">
        <p className="inline-flex items-center gap-1.5">
          <ShieldCheck className="h-3.5 w-3.5 text-accent" />
          <span className="eyebrow">How this works</span>
        </p>
        <p className="mt-2 max-w-3xl text-sm text-ink-muted">
          The assistant can read your data and suggest an order. It cannot place
          one. Approving here runs the same code as creating a purchase order by
          hand, and the order arrives as a draft — approving a suggestion means
          it is worth ordering, not that it has been delivered. Suggestions
          expire after 24 hours, because a reorder is only as good as the stock
          level it was calculated from.
        </p>
      </Band>

      <Band className="mb-4">
        <BandHeader
          label="Awaiting your decision"
          action={
            <span className="tnum text-2xs text-ink-subtle">
              {pending.length} pending
            </span>
          }
        />
        {actions.isLoading ? (
          <p className="px-4 py-8 text-sm text-ink-subtle">Loading…</p>
        ) : pending.length === 0 ? (
          <p className="px-4 py-8 text-sm text-ink-muted">
            Nothing waiting. Ask the assistant to reorder something and it will
            appear here.
          </p>
        ) : (
          <ul className="divide-y divide-border">
            {pending.map((action) => (
              <li key={action.id}>
                <PendingRow action={action} />
              </li>
            ))}
          </ul>
        )}
      </Band>

      {settled.length > 0 && (
        <Band>
          <BandHeader
            label="Decided"
            description="Kept, including the rejections. A suggestion nobody accepted is the clearest evidence of where the model is wrong."
          />
          <ul className="divide-y divide-border">
            {settled.map((action) => (
              <li key={action.id}>
                <SettledRow action={action} />
              </li>
            ))}
          </ul>
        </Band>
      )}
    </>
  );
}

function PendingRow({ action }: { action: AssistantAction }) {
  const decide = useDecideAction();
  const [amending, setAmending] = useState(false);
  const [quantity, setQuantity] = useState(action.proposed.quantity);

  const amended = quantity !== action.proposed.quantity;
  const total = quantity * action.proposed.unit_cost;

  return (
    <div className="px-4 py-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="tnum text-sm font-semibold">
              {action.proposed.sku}
            </span>
            <span className="truncate text-sm text-ink-muted">
              {action.proposed.product_name}
            </span>
            <Badge tone="warning">Proposed</Badge>
          </div>

          <p className="mt-1.5 text-sm">
            <span className="tnum font-semibold">
              {action.proposed.quantity.toLocaleString()}
            </span>{" "}
            units to {action.proposed.warehouse_name} from{" "}
            {action.proposed.supplier_name} —{" "}
            <span className="tnum">
              {action.proposed.estimated_total.toLocaleString(undefined, {
                style: "currency",
                currency: "USD",
              })}
            </span>
          </p>

          {action.rationale && (
            /* The model's reasoning, quoted rather than asserted. An approver
               needs to judge the argument, not be told the conclusion. */
            <blockquote className="mt-2 border-l-2 border-accent-border pl-2.5 text-sm text-ink-muted">
              {action.rationale}
            </blockquote>
          )}

          <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-2xs text-ink-subtle">
            <span className="inline-flex items-center gap-1">
              <Clock className="h-3 w-3" />
              expires {new Date(action.expires_at).toLocaleString()}
            </span>
            {action.model && <span className="font-mono">{action.model}</span>}
            {action.source_question && (
              <span className="italic">“{action.source_question}”</span>
            )}
          </p>
        </div>

        <div className="flex shrink-0 flex-wrap items-center gap-2">
          {!amending && (
            <Button
              variant="secondary"
              onClick={() => setAmending(true)}
              icon={<Pencil className="h-3.5 w-3.5" />}
            >
              Amend
            </Button>
          )}
          <Button
            variant="secondary"
            disabled={decide.isPending}
            onClick={() =>
              decide.mutate({ id: action.id, decision: "reject" })
            }
            icon={<X className="h-3.5 w-3.5" />}
          >
            Reject
          </Button>
          <Button
            disabled={decide.isPending}
            onClick={() =>
              decide.mutate({
                id: action.id,
                decision: "approve",
                quantity: amended ? quantity : undefined,
              })
            }
            icon={<Check className="h-4 w-4" />}
          >
            Approve
          </Button>
        </div>
      </div>

      {amending && (
        <div className="mt-3 flex flex-wrap items-center gap-3 rounded-md border border-border bg-sunken px-3 py-2.5">
          <label className="text-sm text-ink-muted" htmlFor={`qty-${action.id}`}>
            Order instead
          </label>
          <input
            id={`qty-${action.id}`}
            type="number"
            min={1}
            max={10000}
            value={quantity}
            onChange={(e) => setQuantity(Number(e.target.value))}
            className="tnum w-28 rounded-md border border-border-strong bg-surface px-2 py-1 text-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          />
          <span className="tnum text-sm text-ink-muted">
            ={" "}
            {total.toLocaleString(undefined, {
              style: "currency",
              currency: "USD",
            })}
          </span>
          {amended && (
            <span className="text-2xs text-ink-subtle">
              The suggestion of {action.proposed.quantity.toLocaleString()} is
              kept on the record.
            </span>
          )}
          <button
            type="button"
            onClick={() => {
              setAmending(false);
              setQuantity(action.proposed.quantity);
            }}
            className="ml-auto text-2xs text-ink-subtle underline underline-offset-2"
          >
            Cancel
          </button>
        </div>
      )}

      {decide.isError && (
        <p
          role="alert"
          className="mt-2 rounded-sm border border-danger/25 bg-danger-soft px-2.5 py-1.5 text-xs text-danger"
        >
          {decide.error instanceof Error
            ? decide.error.message
            : "That didn't work."}
        </p>
      )}
    </div>
  );
}

const TONE: Record<
  AssistantAction["status"],
  "success" | "neutral" | "danger" | "warning"
> = {
  approved: "success",
  rejected: "neutral",
  failed: "danger",
  expired: "neutral",
  proposed: "warning",
};

function SettledRow({ action }: { action: AssistantAction }) {
  const executed = action.executed ?? action.proposed;
  // An expired proposal still reads as "proposed" in the database until someone
  // tries to act on it, so the badge is computed from what is true now.
  const status = action.status === "proposed" ? "expired" : action.status;

  return (
    <div className="flex flex-wrap items-start justify-between gap-3 px-4 py-3">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <span className="tnum text-sm">{action.proposed.sku}</span>
          <Badge tone={TONE[status]}>{status}</Badge>
          {action.amended && (
            <Badge tone="outline" className="normal-case">
              amended by approver
            </Badge>
          )}
        </div>

        <p className="mt-1 text-sm text-ink-muted">
          {action.amended ? (
            <>
              Model asked for{" "}
              <span className="tnum line-through">
                {action.proposed.quantity.toLocaleString()}
              </span>
              , approved at{" "}
              <span className="tnum font-semibold text-ink">
                {executed.quantity.toLocaleString()}
              </span>
            </>
          ) : (
            <>
              <span className="tnum">{executed.quantity.toLocaleString()}</span>{" "}
              units · {executed.product_name}
            </>
          )}
        </p>

        {action.error && (
          <p
            className={cn(
              "mt-1 text-2xs",
              status === "failed" ? "text-danger" : "text-ink-subtle",
            )}
          >
            {status === "failed" && (
              <AlertTriangle className="mr-1 inline h-3 w-3" />
            )}
            {action.error}
          </p>
        )}
      </div>

      <span className="tnum shrink-0 text-2xs text-ink-subtle">
        {action.decided_at
          ? new Date(action.decided_at).toLocaleString()
          : new Date(action.proposed_at).toLocaleString()}
      </span>
    </div>
  );
}
