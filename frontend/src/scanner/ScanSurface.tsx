/**
 * Aim, scan, move stock.
 *
 * ONE PRESENTATION IS ONE SCAN. A camera decodes the same barcode on every
 * frame it can see it, perhaps thirty times a second. Two guards, deliberately
 * overlapping: a per-barcode cooldown stops the requests being made, and a
 * `scan_reference` that is stable for the accepted scan means any that escape
 * -- a retry, a double submit -- are a no-op server side rather than thirty
 * units of stock. The second guard is the one that matters, because it holds
 * even when the first is wrong.
 *
 * AN UNKNOWN BARCODE IS NOT AN ERROR. It is the commonest thing that will
 * happen the first time anyone uses this, because the catalogue has never seen
 * the article. The server says so in a shape this page can act on, and the
 * answer is to offer to link it rather than to display a failure and leave the
 * operator holding a tin of paint.
 */

import { Camera, CameraOff, Keyboard, Link2, PackageCheck, X } from "lucide-react";
import { useCallback, useMemo, useRef, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/Button";
import { ApiError } from "@/lib/api";
import {
  useLinkBarcode,
  useProducts,
  useRecordScan,
  useWarehouses,
  type ScanResult,
} from "@/lib/queries";
import { useBarcodeScanner } from "@/lib/useBarcodeScanner";
import { cn } from "@/lib/utils";

/** Long enough to lift one carton away and bring the next one up. */
const COOLDOWN_MS = 3_000;
const HISTORY = 10;
const DEVICE_KEY = "optistock.device";

/**
 * A stable id for this phone. localStorage can throw outright in a locked-down
 * browser, so the in-memory value is the real one and storage is only an
 * attempt to make it survive a reload.
 */
let deviceInMemory: string | null = null;
function deviceId(): string {
  if (deviceInMemory) return deviceInMemory;
  try {
    const saved = window.localStorage.getItem(DEVICE_KEY);
    if (saved) return (deviceInMemory = saved);
  } catch {
    /* private mode: mint a fresh one and carry on */
  }
  deviceInMemory = `phone-${crypto.randomUUID().slice(0, 8)}`;
  try {
    window.localStorage.setItem(DEVICE_KEY, deviceInMemory);
  } catch {
    /* not persisting is survivable */
  }
  return deviceInMemory;
}

/** The one failure this page can fix rather than merely report. */
function unknownBarcode(error: unknown): string | null {
  if (!(error instanceof ApiError) || error.status !== 422) return null;
  const detail = error.detail as { reason?: string; barcode?: string } | null;
  if (detail && detail.reason === "unknown_barcode" && detail.barcode) {
    return detail.barcode;
  }
  return null;
}

type Outcome = "ok" | "duplicate" | "error";

interface Entry {
  key: string;
  sku: string;
  outcome: Outcome;
  detail: string;
}

export function ScanSurface() {
  const warehouses = useWarehouses();
  const record = useRecordScan();

  const [warehouseId, setWarehouseId] = useState("");
  const [direction, setDirection] = useState<"in" | "out">("in");
  const [quantity, setQuantity] = useState(1);
  const [scanning, setScanning] = useState(false);
  const [entries, setEntries] = useState<Entry[]>([]);
  const [flash, setFlash] = useState<Outcome | null>(null);
  const [typed, setTyped] = useState("");
  const [teaching, setTeaching] = useState<string | null>(null);

  const cooldown = useRef(new Map<string, number>());
  const audio = useRef<AudioContext | null>(null);

  const chosen = warehouseId || warehouses.data?.data?.[0]?.id || "";

  /** On a warehouse floor nobody is watching the screen. */
  const beep = useCallback((outcome: Outcome) => {
    try {
      audio.current ??= new AudioContext();
      const ctx = audio.current;
      if (ctx.state === "suspended") void ctx.resume();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.frequency.value =
        outcome === "ok" ? 880 : outcome === "duplicate" ? 520 : 220;
      gain.gain.setValueAtTime(0.0001, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.25, ctx.currentTime + 0.01);
      gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.16);
      osc.connect(gain).connect(ctx.destination);
      osc.start();
      osc.stop(ctx.currentTime + 0.18);
    } catch {
      /* no audio is not a reason to stop scanning */
    }
  }, []);

  const report = useCallback(
    (entry: Entry) => {
      setEntries((prev) => [entry, ...prev].slice(0, HISTORY));
      setFlash(entry.outcome);
      beep(entry.outcome);
      window.setTimeout(() => setFlash(null), 500);
    },
    [beep]
  );

  const send = useCallback(
    (code: string, as: "barcode" | "sku") => {
      const value = code.trim();
      if (!value || !chosen) return;

      const now = Date.now();
      const last = cooldown.current.get(value);
      if (last !== undefined && now - last < COOLDOWN_MS) return;
      cooldown.current.set(value, now);

      record.mutate(
        {
          ...(as === "barcode" ? { barcode: value } : { sku: value }),
          warehouse_id: chosen,
          direction,
          quantity,
          scan_reference: `${deviceId()}:${value}:${now}`,
          device_id: deviceId(),
        },
        {
          onSuccess: (result: ScanResult) => {
            report({
              key: `${value}-${now}`,
              sku: result.sku,
              outcome: result.duplicate ? "duplicate" : "ok",
              detail: result.duplicate
                ? "already counted"
                : `now ${result.quantity_after} on hand`,
            });
          },
          onError: (error: unknown) => {
            // Let it be retried at once: the operator is still holding the
            // article and will point the camera straight back at it.
            cooldown.current.delete(value);

            const unknown = unknownBarcode(error);
            if (unknown) {
              setTeaching(unknown);
              beep("duplicate");
              return;
            }
            report({
              key: `${value}-${now}`,
              sku: value,
              outcome: "error",
              detail:
                error instanceof Error ? error.message : "did not go through",
            });
          },
        }
      );
    },
    [chosen, direction, quantity, record, report, beep]
  );

  // Decodes are ignored while the link sheet is open. The camera keeps running
  // so the preview stays live, but a barcode held in frame must not queue up
  // thirty more failures behind the question being asked about it.
  const onDecode = useCallback(
    (text: string) => {
      if (teaching) return;
      send(text, "barcode");
    },
    [teaching, send]
  );

  const scanner = useBarcodeScanner({ onDecode, active: scanning });

  const hint = useMemo(() => {
    switch (scanner.status) {
      case "starting":
        return "Starting the camera…";
      case "running":
        return "Point at a barcode";
      case "denied":
        return "Camera permission refused. Allow it, then start again.";
      case "unsupported":
      case "error":
        return scanner.detail;
      default:
        return "Camera off. You can type a code instead.";
    }
  }, [scanner.status, scanner.detail]);

  return (
    <main className="mx-auto grid max-w-lg gap-4 p-4 pb-24">
      <section
        className={cn(
          "overflow-hidden rounded-xl border-2 bg-surface transition-colors duration-200",
          flash === "ok" && "border-success",
          flash === "duplicate" && "border-warning",
          flash === "error" && "border-danger",
          flash === null && "border-border"
        )}
      >
        <div className="relative bg-black">
          {/* Always mounted: the hook needs the element to exist before
              scanning is switched on, not after the next render. */}
          <video
            ref={scanner.videoRef}
            playsInline
            muted
            className={cn(
              "aspect-[3/4] w-full object-cover",
              !scanning && "opacity-0"
            )}
          />
          {!scanning && (
            <div className="absolute inset-0 grid place-items-center text-sm text-white/60">
              Camera is off
            </div>
          )}
          {scanning && scanner.status === "running" && (
            <div
              aria-hidden
              className="pointer-events-none absolute inset-x-[10%] inset-y-[35%] rounded-lg border-2 border-white/80"
            />
          )}
        </div>
        <div className="flex items-center justify-between gap-3 p-3">
          <p className="text-xs text-ink-muted">{hint}</p>
          <Button
            variant={scanning ? "secondary" : "primary"}
            onClick={() => setScanning((on) => !on)}
          >
            {scanning ? (
              <>
                <CameraOff className="mr-2 h-4 w-4" /> Stop
              </>
            ) : (
              <>
                <Camera className="mr-2 h-4 w-4" /> Start
              </>
            )}
          </Button>
        </div>
      </section>

      <section className="grid gap-3 rounded-xl border border-border bg-surface p-3">
        <div className="grid grid-cols-2 gap-2">
          {(["in", "out"] as const).map((value) => (
            <Button
              key={value}
              size="lg"
              variant={direction === value ? "primary" : "secondary"}
              onClick={() => setDirection(value)}
            >
              {value === "in" ? "Stock in" : "Stock out"}
            </Button>
          ))}
        </div>

        <label className="grid gap-1 text-sm">
          <span className="text-ink-muted">Warehouse</span>
          <select
            value={chosen}
            onChange={(event) => setWarehouseId(event.target.value)}
            className="h-11 rounded-md border border-border-strong bg-surface px-2 text-ink"
          >
            {(warehouses.data?.data ?? []).map((warehouse) => (
              <option key={warehouse.id} value={warehouse.id}>
                {warehouse.name}
              </option>
            ))}
          </select>
        </label>

        <label className="grid gap-1 text-sm">
          <span className="text-ink-muted">Quantity per scan</span>
          <input
            type="number"
            min={1}
            max={10000}
            inputMode="numeric"
            value={quantity}
            onChange={(event) =>
              setQuantity(Math.max(1, Number(event.target.value) || 1))
            }
            className="h-11 rounded-md border border-border-strong bg-surface px-2 text-ink"
          />
        </label>

        <form
          className="flex gap-2"
          onSubmit={(event: FormEvent) => {
            event.preventDefault();
            // Typed by hand, so it is one of ours: a SKU, not a barcode.
            send(typed, "sku");
            setTyped("");
          }}
        >
          <input
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
            placeholder="Or type a SKU"
            className="h-11 min-w-0 flex-1 rounded-md border border-border-strong bg-surface px-2 font-mono text-sm text-ink"
          />
          <Button type="submit" variant="secondary" size="lg">
            <Keyboard className="h-4 w-4" />
          </Button>
        </form>
      </section>

      {entries.length > 0 && (
        <ul className="grid gap-1.5">
          {entries.map((entry) => (
            <li
              key={entry.key}
              className="flex items-center justify-between gap-2 rounded-lg border border-border bg-surface px-3 py-2 text-sm"
            >
              <span className="flex min-w-0 items-center gap-2 font-mono">
                <PackageCheck
                  className={cn(
                    "h-4 w-4 shrink-0",
                    entry.outcome === "ok" && "text-success",
                    entry.outcome === "duplicate" && "text-warning",
                    entry.outcome === "error" && "text-danger"
                  )}
                />
                <span className="truncate">{entry.sku}</span>
              </span>
              <span className="shrink-0 text-xs text-ink-muted">
                {entry.detail}
              </span>
            </li>
          ))}
        </ul>
      )}

      {teaching && (
        <LinkSheet
          barcode={teaching}
          onClose={() => setTeaching(null)}
          onLinked={() => {
            const code = teaching;
            setTeaching(null);
            // Straight back round the loop, so linking and scanning feel like
            // one action rather than two.
            cooldown.current.delete(code);
            send(code, "barcode");
          }}
        />
      )}
    </main>
  );
}

/** Ask which product this article is, and remember the answer. */
function LinkSheet({
  barcode,
  onClose,
  onLinked,
}: {
  barcode: string;
  onClose: () => void;
  onLinked: () => void;
}) {
  const [search, setSearch] = useState("");
  const products = useProducts({ search: search || undefined, limit: 20 });
  const link = useLinkBarcode();
  const [problem, setProblem] = useState("");

  return (
    <div className="fixed inset-0 z-50 grid items-end bg-black/60">
      <div className="max-h-[80dvh] overflow-y-auto rounded-t-2xl border-t border-border bg-canvas p-4">
        <div className="mb-3 flex items-start justify-between gap-3">
          <div>
            <h2 className="font-semibold">New article</h2>
            <p className="font-mono text-xs text-ink-muted">{barcode}</p>
            <p className="mt-1 text-sm text-ink-muted">
              Nothing carries this barcode yet. Which product is it?
            </p>
          </div>
          <button onClick={onClose} aria-label="Close">
            <X className="h-5 w-5 text-ink-muted" />
          </button>
        </div>

        <input
          autoFocus
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search by name or SKU"
          className="mb-3 h-11 w-full rounded-md border border-border-strong bg-surface px-3 text-ink"
        />

        {problem && <p className="mb-2 text-sm text-danger">{problem}</p>}

        <ul className="grid gap-1.5">
          {(products.data?.data ?? []).map((product) => (
            <li key={product.id}>
              <button
                disabled={link.isPending}
                onClick={() => {
                  setProblem("");
                  link.mutate(
                    { productId: product.id, barcode },
                    {
                      onSuccess: onLinked,
                      onError: (error: unknown) =>
                        setProblem(
                          error instanceof Error
                            ? error.message
                            : "Could not link that."
                        ),
                    }
                  );
                }}
                className="flex w-full items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2 text-left disabled:opacity-50"
              >
                <Link2 className="h-4 w-4 shrink-0 text-accent" />
                <span className="min-w-0">
                  <span className="block truncate text-sm">{product.name}</span>
                  <span className="block font-mono text-xs text-ink-muted">
                    {product.sku}
                    {product.barcode && " · already has a barcode"}
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>

        {products.data?.data?.length === 0 && (
          <p className="py-6 text-center text-sm text-ink-muted">
            No product matches that.
          </p>
        )}
      </div>
    </div>
  );
}
