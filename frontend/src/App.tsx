import { Navigate, Route, Routes, useLocation } from "react-router-dom";

import { AppShell } from "@/components/layout/AppShell";
import { useAuth } from "@/lib/auth";
import { Alerts } from "@/pages/Alerts";
import { Approvals } from "@/pages/Approvals";
import { Assistant } from "@/pages/Assistant";
import { EventStream } from "@/pages/EventStream";
import { Insights } from "@/pages/Insights";
import { Inventory } from "@/pages/Inventory";
import { Login } from "@/pages/Login";
import { Overview } from "@/pages/Overview";
import { Placeholder } from "@/pages/Placeholder";
import { Products } from "@/pages/Products";
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
        <Route
          path="sales"
          element={
            <Placeholder
              title="Sales"
              description="Orders and revenue over time."
              building="The API is live — this screen is queued behind the Overview dashboard."
            />
          }
        />
        <Route
          path="customers"
          element={
            <Placeholder
              title="Customers"
              description="Accounts and their order history."
              building="The API and lifetime-value calculation are live; the screen is queued behind the Overview dashboard."
            />
          }
        />
        <Route path="assistant" element={<Assistant />} />
        <Route path="approvals" element={<Approvals />} />
        <Route path="insights" element={<Insights />} />
        <Route path="stockout-risk" element={<StockoutRisk />} />
        <Route path="alerts" element={<Alerts />} />
        <Route path="system/events" element={<EventStream />} />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
