import { ScrollText } from "lucide-react";
import { useState } from "react";

import { PageHeader } from "@/components/layout/AppShell";
import { Badge } from "@/components/ui/Badge";
import { Band, BandHeader } from "@/components/ui/Band";
import { Table, TableWrap, TD, TH, THead, TR } from "@/components/ui/Table";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states";
import { count, dateTime } from "@/lib/format";
import { useAuditTrail, type AuditEntry } from "@/lib/queries";
import { cn } from "@/lib/utils";
import { Fragment } from "react";

/**
 * The audit trail.
 *
 * Every create, update and delete on a tracked entity is already recorded by a
 * SQLAlchemy flush listener, inside the same transaction as the change — so a
 * rolled-back operation leaves no trace, and nothing can be written without
 * being written down. All of that has been true for months and entirely
 * invisible, which is the same as not having it when somebody asks.
 *
 * The row expands to the before-and-after values, because that is the only part
 * of an audit trail anyone actually needs: not that a product changed, but what
 * it changed from. Fields that did not change are dropped from the comparison —
 * a diff that lists forty identical values is a diff nobody reads.
 */
export function AuditLog() {
  const [entity, setEntity] = useState("");
  const [action, setAction] = useState("");
  const trail = useAuditTrail({
    entity_name: entity || undefined,
    action: action || undefined,
  });
  const [openRow, setOpenRow] = useState<string | null>(null);

  const rows = trail.data?.data ?? [];

  return (
    <>
      <PageHeader
        title="Audit trail"
        description="Every tracked change, who made it, and what it changed from. Written in the same transaction as the change itself."
      />

      <Band>
        <BandHeader
          label="Compliance log"
          description={
            trail.data
              ? `${count(trail.data.total)} recorded changes. Newest first.`
              : undefined
          }
          action={
            <div className="flex flex-wrap items-center gap-2">
              <Select
                label="Entity"
                value={entity}
                onChange={setEntity}
                options={trail.data?.entities ?? []}
              />
              <Select
                label="Action"
                value={action}
                onChange={setAction}
                options={trail.data?.actions ?? []}
              />
            </div>
          }
        />

        {trail.isError ? (
          <ErrorState error={trail.error} onRetry={() => void trail.refetch()} />
        ) : trail.isLoading ? (
          <TableSkeleton rows={10} cols={5} />
        ) : rows.length === 0 ? (
          <EmptyState
            icon={<ScrollText className="h-5 w-5" />}
            title={entity || action ? "Nothing matches" : "No changes recorded"}
            description={
              entity || action
                ? "Try clearing the filters."
                : "Changes to products, stock and orders are recorded here automatically."
            }
          />
        ) : (
          <TableWrap className="max-h-[70vh]">
            <Table>
              <THead>
                <TR>
                  <TH>When</TH>
                  <TH>Who</TH>
                  <TH>Action</TH>
                  <TH>Entity</TH>
                  <TH>Record</TH>
                </TR>
              </THead>
              <tbody className="zebra">
                {rows.map((row) => (
                  <Fragment key={row.id}>
                    <TR
                      className="cursor-pointer hover:bg-accent-soft/50"
                      onClick={() => setOpenRow(openRow === row.id ? null : row.id)}
                    >
                      <TD className="tnum text-ink-muted">
                        {dateTime(row.timestamp)}
                      </TD>
                      <TD>{row.actor}</TD>
                      <TD>
                        <ActionBadge action={row.action} />
                      </TD>
                      <TD className="text-ink-muted">{row.entity_name}</TD>
                      <TD className="tnum text-2xs text-ink-subtle">
                        {row.entity_id.slice(0, 8)}
                      </TD>
                    </TR>
                    {openRow === row.id && (
                      <tr>
                        <td colSpan={5} className="bg-surface px-3 pb-3">
                          <Diff entry={row} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </Table>
          </TableWrap>
        )}
      </Band>
    </>
  );
}

/**
 * DELETE is the only action that gets a colour, and it borrows danger
 * legitimately: it is the one entry a compliance reader is scanning for.
 * Creates and updates are the ordinary business of the day and stay unmarked,
 * which is the same rule the rest of the product follows.
 */
function ActionBadge({ action }: { action: string }) {
  if (action === "DELETE") return <Badge tone="danger">delete</Badge>;
  return (
    <span className="font-mono text-2xs text-ink-muted lowercase">{action}</span>
  );
}

/**
 * Before and after, limited to what actually moved.
 *
 * Comparing the two payloads rather than printing both: an update that touched
 * one field would otherwise render forty identical lines and bury it.
 */
function Diff({ entry }: { entry: AuditEntry }) {
  const before = entry.old_values ?? {};
  const after = entry.new_values ?? {};
  const fields = [...new Set([...Object.keys(before), ...Object.keys(after)])];
  const changed = fields.filter(
    (key) => JSON.stringify(before[key]) !== JSON.stringify(after[key]),
  );

  if (changed.length === 0) {
    return (
      <p className="py-2 text-2xs text-ink-subtle">
        No field-level values were recorded for this entry.
      </p>
    );
  }

  return (
    <div className="border-l-2 border-accent-border py-1 pl-3">
      <p className="eyebrow mb-1.5">
        {entry.action === "DELETE"
          ? "Removed"
          : entry.action === "CREATE"
            ? "Created with"
            : "Changed"}
      </p>
      <dl className="space-y-1">
        {changed.map((key) => (
          <div key={key} className="flex flex-wrap items-baseline gap-x-2 text-sm">
            <dt className="font-mono text-2xs text-ink-subtle">{key}</dt>
            <dd className="flex flex-wrap items-baseline gap-x-2">
              {key in before && (
                <span className="tnum text-ink-subtle line-through">
                  {render(before[key])}
                </span>
              )}
              {key in after && (
                <span className={cn("tnum", key in before && "font-medium")}>
                  {render(after[key])}
                </span>
              )}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function render(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function Select({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: string[];
}) {
  return (
    <label className="flex items-center gap-1.5">
      <span className="eyebrow">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-md border border-border-strong bg-surface px-2 py-1 text-xs text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      >
        <option value="">All</option>
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    </label>
  );
}
