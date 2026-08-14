import { Navigate, Route, Routes, useLocation } from "react-router-dom";

import { CursorLayer } from "@/components/cursor/CursorLayer";
import { AppShell } from "@/components/layout/AppShell";
import { useAuth } from "@/lib/auth";
import { Alerts } from "@/pages/Alerts";
import { Approvals } from "@/pages/Approvals";
import { Assistant } from "@/pages/Assistant";
import { Transfers } from "@/pages/Transfers";
import { Suppliers } from "@/pages/Suppliers";
import { Reconciliation } from "@/pages/Reconciliation";
import { AuditLog } from "@/pages/AuditLog";
import { Customers } from "@/pages/Customers";
import { EventStream } from "@/pages/EventStream";
import { Insights } from "@/pages/Insights";
import { Inventory } from "@/pages/Inventory";
import { InventoryNetwork } from "@/pages/InventoryNetwork";
import { WarehouseCommand } from "@/pages/WarehouseCommand";
import { Login } from "@/pages/Login";
import { Analytics } from "@/pages/Analytics";
import { Site } from "@/pages/Site";
import { Products } from "@/pages/Products";
import { ProductsHub } from "@/pages/ProductsHub";
import { Sales } from "@/pages/Sales";
import { PurchaseOrders } from "@/pages/PurchaseOrders";
import { StockoutRisk } from "@/pages/StockoutRisk";

/** Bounce anonymous visitors to login, remembering where they were going. */
function RequireAuth({ children }: { children: React.ReactNode }) {
  const { isAuthenticated } = useAuth();
  const location = useLocation();

  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  return <>{children}</>;
}

export default function App() {
  const { session } = useAuth();
  // The label is the collaborative-cursor look from the reference. Showing
  // your OWN name is admittedly odd on a single-user session — pass no label
  // to drop it, or keep it as the visible half of the multiplayer story.
  const name = session?.email?.split("@")[0];

  return (
    <>
      <CursorLayer label={name} />
      <Routes>
      <Route path="/login" element={<Login />} />

      <Route
        element={
          <RequireAuth>
            <AppShell />
          </RequireAuth>
        }
      >
        <Route index element={<Site />} />
        <Route path="analytics" element={<Analytics />} />
        <Route path="inventory" element={<InventoryNetwork />} />
        <Route path="inventory/all" element={<Inventory />} />
        <Route path="inventory/:warehouseId" element={<WarehouseCommand />} />
        <Route path="products" element={<ProductsHub />} />
        {/* The searchable table still exists, as a drill-down rather than the
            front door — the same move Inventory made. A table answers "where is
            SKU-0142"; it cannot answer "which product needs me today". */}
        <Route path="products/all" element={<Products />} />
        <Route path="sales" element={<Sales />} />
        <Route path="customers" element={<Customers />} />
        <Route path="assistant" element={<Assistant />} />
        <Route path="approvals" element={<Approvals />} />
        <Route path="purchase-orders" element={<PurchaseOrders />} />
        <Route path="suppliers" element={<Suppliers />} />
        <Route path="transfers" element={<Transfers />} />
        <Route path="stock-counts" element={<Reconciliation />} />
        <Route path="insights" element={<Insights />} />
        <Route path="stockout-risk" element={<StockoutRisk />} />
        <Route path="alerts" element={<Alerts />} />
        <Route path="system/events" element={<EventStream />} />
        <Route path="system/audit" element={<AuditLog />} />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </>
  );
}
