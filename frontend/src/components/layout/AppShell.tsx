import {
  Activity,
  AlertTriangle,
  ArrowLeftRight,
  Boxes,
  Building2,
  ChevronDown,
  ClipboardCheck,
  ClipboardList,
  Factory,
  Hourglass,
  LayoutDashboard,
  LogOut,
  Menu,
  MessageSquare,
  Package,
  ScrollText,
  ShoppingCart,
  Sparkles,
  Truck,
  Users,
  X,
  type LucideIcon,
} from "lucide-react";
import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";

import { Button } from "@/components/ui/Button";
import { Mark } from "@/components/ui/Mark";
import { useAuth } from "@/lib/auth";
import { useAlerts } from "@/lib/queries";
import { cn } from "@/lib/utils";

/**
 * Navigation is grouped by what the user is trying to DO, not by which backend
 * module serves it. "System" is deliberately top-level rather than buried in
 * settings — the live event stream and the concurrency proof are the most
 * interesting things here, and hidden pages don't get looked at.
 */
interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  /** Match this path exactly. Without it "/" stays active on every route. */
  end?: boolean;
  /** Show the open-alert count here. Alerts arrive from a background consumer,
   *  so the one place they must be visible is the page you are NOT on. */
  showAlertCount?: boolean;
}

interface NavGroup {
  heading?: string;
  items: NavItem[];
}

const NAV: NavGroup[] = [
  {
    items: [
      { to: "/", label: "Site", icon: Building2, end: true },
      { to: "/analytics", label: "Analytics", icon: LayoutDashboard },
      { to: "/assistant", label: "Assistant", icon: MessageSquare },
      { to: "/approvals", label: "Approvals", icon: ClipboardCheck },
    ],
  },
  {
    heading: "Operations",
    items: [
      { to: "/inventory", label: "Inventory", icon: Boxes },
      { to: "/products", label: "Products", icon: Package },
      { to: "/purchase-orders", label: "Purchase orders", icon: Truck },
      { to: "/suppliers", label: "Suppliers", icon: Factory },
      { to: "/transfers", label: "Transfers", icon: ArrowLeftRight },
      { to: "/stock-counts", label: "Stock counts", icon: ClipboardList },
      { to: "/sales", label: "Sales", icon: ShoppingCart },
      { to: "/customers", label: "Customers", icon: Users },
    ],
  },
  {
    heading: "Intelligence",
    items: [
      { to: "/insights", label: "Insights", icon: Sparkles },
      { to: "/stockout-risk", label: "Stockout risk", icon: Hourglass },
      {
        to: "/alerts",
        label: "Alerts",
        icon: AlertTriangle,
        showAlertCount: true,
      },
    ],
  },
  {
    heading: "System",
    items: [
      { to: "/system/events", label: "Event stream", icon: Activity },
      { to: "/system/audit", label: "Audit trail", icon: ScrollText },
    ],
  },
];

export function AppShell() {
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <div className="min-h-screen">
      {/* Backdrop for the mobile drawer */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-30 bg-ink/20 lg:hidden"
          onClick={() => setMobileOpen(false)}
          aria-hidden
        />
      )}

      <Sidebar open={mobileOpen} onClose={() => setMobileOpen(false)} />

      <div className="lg:pl-60">
        <TopBar onMenu={() => setMobileOpen(true)} />
        <main className="px-6 py-7">
          <div className="mx-auto max-w-[1400px]">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}

function Sidebar({ open, onClose }: { open: boolean; onClose: () => void }) {
  // Polled here rather than on the alerts page, because the whole point is to
  // be visible from wherever you are. Shares a cache key with the page, so
  // opening it costs no extra request.
  const alerts = useAlerts({ status: "open" });
  const counts = alerts.data?.open_counts ?? {};
  const criticalAlerts = counts.critical ?? 0;
  const openAlerts =
    criticalAlerts + (counts.warning ?? 0) + (counts.info ?? 0);

  return (
    <aside
      className={cn(
        "fixed inset-y-0 left-0 z-40 flex w-60 flex-col border-r border-border bg-surface",
        "transition-transform duration-200 lg:translate-x-0",
        open ? "translate-x-0" : "-translate-x-full",
      )}
    >
      <div className="flex h-14 shrink-0 items-center justify-between border-b border-border px-5">
        <div className="flex items-center gap-2.5">
          <Mark />
          <span className="font-display text-lg font-semibold">OptiStock</span>
        </div>
        <Button
          variant="ghost"
          size="icon"
          className="lg:hidden"
          onClick={onClose}
          aria-label="Close navigation"
        >
          <X className="h-4 w-4" />
        </Button>
      </div>

      <nav className="flex-1 overflow-y-auto px-3 py-4">
        {NAV.map((group, index) => (
          <div key={group.heading ?? index} className={cn(index > 0 && "mt-6")}>
            {group.heading && (
              <p className="eyebrow mb-2 px-2">{group.heading}</p>
            )}
            <ul className="space-y-0.5">
              {group.items.map(({ to, label, icon: Icon, end, showAlertCount }) => (
                <li key={to}>
                  <NavLink
                    to={to}
                    end={end}
                    onClick={onClose}
                    className={({ isActive }) =>
                      cn(
                        "flex items-center gap-2.5 rounded-md px-2 py-1.5 text-base transition-colors",
                        // The active item carries a left rule as well as a
                        // tint, so the current page survives being read on a
                        // dim screen or by someone who can't separate the two
                        // background greens.
                        isActive
                          ? "border-l-2 border-accent bg-accent-soft pl-1.5 font-medium text-accent-hover"
                          : "text-ink-muted hover:bg-sunken hover:text-ink",
                      )
                    }
                  >
                    <Icon className="h-4 w-4 shrink-0" />
                    {label}
                    {showAlertCount && openAlerts > 0 && (
                      <span
                        className={cn(
                          "ml-auto rounded-sm px-1.5 py-0.5 font-mono text-2xs font-medium",
                          criticalAlerts > 0
                            ? "bg-danger-soft text-danger"
                            : "bg-warning-soft text-warning",
                        )}
                      >
                        {openAlerts}
                      </span>
                    )}
                  </NavLink>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>

      <div className="shrink-0 border-t border-border px-5 py-3">
        <p className="text-2xs text-ink-subtle">
          Seeded demo · 2 tenants
        </p>
      </div>
    </aside>
  );
}

function TopBar({ onMenu }: { onMenu: () => void }) {
  const { session, signOut } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-border bg-canvas/85 px-6 backdrop-blur-sm">
      <Button
        variant="ghost"
        size="icon"
        className="lg:hidden"
        onClick={onMenu}
        aria-label="Open navigation"
      >
        <Menu className="h-4 w-4" />
      </Button>

      <div className="ml-auto flex items-center gap-3">
        <span className="hidden text-xs text-ink-muted sm:inline">
          TechNova Industries
        </span>

        <div className="relative">
          <button
            onClick={() => setMenuOpen((v) => !v)}
            className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors hover:bg-sunken"
            aria-expanded={menuOpen}
            aria-haspopup="menu"
          >
            <span className="flex h-6 w-6 items-center justify-center rounded-sm border border-accent-border bg-accent-soft font-mono text-2xs font-semibold text-accent-hover">
              {session?.role?.[0]?.toUpperCase() ?? "?"}
            </span>
            <span className="hidden text-ink-muted sm:inline">
              {session?.role ?? "—"}
            </span>
            <ChevronDown className="h-3.5 w-3.5 text-ink-subtle" />
          </button>

          {menuOpen && (
            <>
              <div
                className="fixed inset-0 z-10"
                onClick={() => setMenuOpen(false)}
                aria-hidden
              />
              <div
                role="menu"
                className="absolute right-0 z-20 mt-1.5 w-52 rounded-lg border border-border bg-surface py-1 shadow-lg"
              >
                <div className="border-b border-border px-3 py-2">
                  <p className="truncate text-sm font-medium">
                    {session?.email ?? "Signed in"}
                  </p>
                  <p className="mt-0.5 text-2xs text-ink-subtle">
                    {session?.role}
                  </p>
                </div>
                <button
                  role="menuitem"
                  onClick={signOut}
                  className="flex w-full items-center gap-2 px-3 py-2 text-sm text-ink-muted transition-colors hover:bg-sunken hover:text-ink"
                >
                  <LogOut className="h-3.5 w-3.5" />
                  Sign out
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </header>
  );
}

/** Consistent page heading. Every screen uses it so titles never drift. */
export function PageHeader({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: React.ReactNode;
}) {
  return (
    /* Stacked on a phone, side by side from sm up.
       Side by side at every width meant the action -- a filter group, a button
       -- held its full size while the description was squeezed into whatever
       was left, which on a 390px screen was a column about two words wide. */
    <div className="mb-6 flex flex-col items-start gap-3 sm:flex-row sm:items-end sm:justify-between sm:gap-4">
      <div className="min-w-0">
        <h1 className="text-xl leading-tight font-semibold sm:text-2xl">{title}</h1>
        {description && (
          <p className="mt-1.5 text-sm text-ink-muted sm:text-base">{description}</p>
        )}
      </div>
      {action && <div className="w-full shrink-0 sm:w-auto">{action}</div>}
    </div>
  );
}
