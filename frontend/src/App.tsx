import { Navigate, Route, Routes, useLocation } from "react-router-dom";

import { AppShell } from "@/components/layout/AppShell";
import { useAuth } from "@/lib/auth";
import { Alerts } from "@/pages/Alerts";
import { Approvals } from "@/pages/Approvals";
import { Assistant } from "@/pages/Assistant";
import { Customers } from "@/pages/Customers";
import { EventStream } from "@/pages/EventStream";
import { Insights } from "@/pages/Insights";
import { Inventory } from "@/pages/Inventory";
import { Login } from "@/pages/Login";
import { Overview } from "@/pages/Overview";
import { Products } from "@/pages/Products";
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
  return (
    <Routes>
      <Route path="/login" element={<Login />} />

      <Route
        element={
          <RequireAuth>
            <AppShell />
          </RequireAuth>
        }
      >
        <Route index element={<Overview />} />
        <Route path="inventory" element={<Inventory />} />
        <Route path="products" element={<Products />} />
        <Route path="sales" element={<Sales />} />
        <Route path="customers" element={<Customers />} />
        <Route path="assistant" element={<Assistant />} />
        <Route path="approvals" element={<Approvals />} />
        <Route path="purchase-orders" element={<PurchaseOrders />} />
        <Route path="insights" element={<Insights />} />
        <Route path="stockout-risk" element={<StockoutRisk />} />
        <Route path="alerts" element={<Alerts />} />
        <Route path="system/events" element={<EventStream />} />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
