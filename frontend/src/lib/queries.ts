/**
 * Typed API surface + React Query hooks.
 *
 * The types here mirror the FastAPI response schemas. They are hand-written for
 * now; once the surface settles, generating them from the OpenAPI document
 * removes the chance of drifting out of sync with the backend.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";

/* -------------------------------------------------------------------------- */
/* Types                                                                       */
/* -------------------------------------------------------------------------- */

export interface Paginated<T> {
  total: number;
  skip: number;
  limit: number;
  data: T[];
}

export interface Product {
  id: string;
  company_id: string;
  sku: string;
  name: string;
  category: string | null;
  unit_cost: string;
  selling_price: string;
  status: string;
  abc_class: string | null;
  abc_calculated_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface InventoryRow {
  id: string;
  product_id: string;
  warehouse_id: string;
  quantity: number;
  last_counted_at: string;
  sku: string;
  product_name: string;
  warehouse_name: string;
  category: string | null;
  abc_class: string | null;
  reorder_point: number;
  is_low: boolean;
}

export interface Warehouse {
  id: string;
  company_id: string;
  name: string;
  location_code: string;
  capacity_units: number;
  is_active: boolean;
}

export interface Recommendation {
  id: string;
  product_id: string;
  warehouse_id: string;
  suggested_action: string;
  suggested_quantity: number;
  confidence_score: number;
  evidence: Record<string, unknown>;
  business_reasoning: string;
  source: string;
  created_at: string;
}

/* -------------------------------------------------------------------------- */
/* Hooks                                                                       */
/* -------------------------------------------------------------------------- */

/** Query keys in one place so cache invalidation never guesses at a string. */
export const keys = {
  products: (params?: unknown) => ["products", params] as const,
  inventory: (params?: unknown) => ["inventory", params] as const,
  traces: (days: number) => ["inventory", "traces", days] as const,
  events: (limit: number) => ["events", limit] as const,
  outboxHealth: () => ["events", "health"] as const,
  alerts: (params?: unknown) => ["alerts", params] as const,
  overview: (days: number) => ["dashboard", "overview", days] as const,
  suggestions: () => ["insights", "recommendations"] as const,
  accuracy: () => ["insights", "accuracy"] as const,
  assistantStatus: () => ["assistant", "status"] as const,
  assistantActions: (status?: string) => ["assistant", "actions", status] as const,
  warehouses: () => ["warehouses"] as const,
  recommendations: () => ["recommendations"] as const,
};

function queryString(params: Record<string, unknown>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "" && value !== false) {
      search.set(key, String(value));
    }
  }
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

export function useProducts(
  params: {
    skip?: number;
    limit?: number;
    search?: string;
    abc_class?: string;
    status?: string;
  } = {},
) {
  return useQuery({
    queryKey: keys.products(params),
    queryFn: () =>
      api<Paginated<Product>>(`/products/${queryString({ limit: 100, ...params })}`),
    placeholderData: (previous) => previous,
  });
}

export function useInventory(
  params: {
    skip?: number;
    limit?: number;
    warehouse_id?: string;
    search?: string;
    low_only?: boolean;
  } = {},
) {
  return useQuery({
    queryKey: keys.inventory(params),
    queryFn: () =>
      api<Paginated<InventoryRow>>(
        `/inventory/${queryString({ limit: 100, ...params })}`,
      ),
    // Keep showing the previous page while the next one loads, so filtering a
    // table doesn't flash a skeleton on every keystroke.
    placeholderData: (previous) => previous,
  });
}

/**
 * Recent movement history for every stock line, keyed by inventory id.
 *
 * Deliberately a second request rather than part of the stock list. The list is
 * what blocks the table from rendering; a trace is context that can arrive a
 * moment later and fade in. Cached for a minute because a sparkline that
 * refetches on every keystroke is a sparkline nobody can read.
 */
export function useInventoryTraces(days = 30) {
  return useQuery({
    queryKey: keys.traces(days),
    queryFn: () =>
      api<{ days: number; traces: Record<string, number[]> }>(
        `/inventory/traces?days=${days}`,
      ),
    staleTime: 60_000,
  });
}

export interface AssistantStatus {
  configured: boolean;
  provider: string;
  model: string | null;
  tools: { name: string; description: string }[];
  data_mode: { mode: "demo" | "production"; masked_fields: string[]; note: string };
  max_tool_calls: number;
}

/** What the assistant can reach, published so its boundary is visible. */
export function useAssistantStatus() {
  return useQuery({
    queryKey: keys.assistantStatus(),
    queryFn: () => api<AssistantStatus>("/assistant/status"),
    staleTime: 5 * 60_000,
  });
}

export interface Suggestion {
  id: string;
  product_id: string;
  warehouse_id: string;
  sku: string;
  product_name: string;
  warehouse_name: string;
  abc_class: string | null;
  suggested_action: string;
  suggested_quantity: number;
  quantity_on_hand: number;
  estimated_cost: number;
  confidence_score: number;
  evidence: Record<string, string | number>;
  business_reasoning: string;
  source: string;
  created_at: string;
}

export interface AccuracySummary {
  scored: number;
  pending: number;
  weighted_ape: number | null;
  mae: number | null;
  within_20_pct: number | null;
  total_forecast: number;
  total_actual: number;
}

export interface ScoredForecast {
  id: string;
  sku: string;
  product_name: string;
  warehouse_name: string;
  forecast_quantity: number;
  actual_quantity: number;
  absolute_error: number;
  error: number;
  direction: "over" | "under" | "exact";
  horizon_days: number;
  horizon_end: string;
  confidence_score: number;
}

export function useSuggestions() {
  return useQuery({
    queryKey: keys.suggestions(),
    queryFn: () => api<Paginated<Suggestion>>("/insights/recommendations?limit=100"),
  });
}

export function useForecastAccuracy() {
  return useQuery({
    queryKey: keys.accuracy(),
    queryFn: () =>
      api<{
        summary: AccuracySummary;
        lookback_days: number;
        worst: ScoredForecast[];
      }>("/insights/accuracy"),
  });
}

export interface DayMetric {
  date: string;
  revenue: number;
  orders: number;
  units_sold: number;
  stock_movements: number;
  units_received: number;
}

export interface Overview {
  range_days: number;
  trading: {
    revenue: number;
    orders: number;
    units_sold: number;
    movements: number;
    revenue_change_pct: number | null;
    comparison_days: number;
  };
  series: DayMetric[];
  stock: {
    lines: number;
    units: number;
    value_at_cost: number;
    low: number;
    out: number;
  };
  alerts: Record<string, number>;
  projection: { updated_at: string | null; age_seconds: number | null };
}

export function useOverview(days = 30) {
  return useQuery({
    queryKey: keys.overview(days),
    queryFn: () => api<Overview>(`/dashboard/overview?days=${days}`),
    placeholderData: (previous) => previous,
  });
}

export interface Alert {
  id: string;
  alert_type: string;
  severity: "info" | "warning" | "critical";
  status: "open" | "resolved" | "dismissed";
  subject_type: string;
  subject_id: string;
  title: string;
  detail: Record<string, unknown>;
  triggered_by_event_id: string | null;
  created_at: string;
  resolved_at: string | null;
  dismissed_at: string | null;
}

export interface AlertPage extends Paginated<Alert> {
  open_counts: Record<string, number>;
}

export function useAlerts(params: { status?: string; severity?: string } = {}) {
  return useQuery({
    queryKey: keys.alerts(params),
    queryFn: () => api<AlertPage>(`/alerts/${queryString({ limit: 100, ...params })}`),
    placeholderData: (previous) => previous,
    // Alerts are raised by a background consumer, not by anything this tab did,
    // so the page has to go looking for them.
    refetchInterval: 10_000,
  });
}

export function useDismissAlert() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (alertId: string) =>
      api<Alert>(`/alerts/${alertId}/dismiss`, { method: "POST" }),
    // Refetch rather than patch the cache: dismissing changes the open counts
    // and can change which page of results the row belongs to.
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["alerts"] }),
  });
}

export interface OutboxHealth {
  unpublished: number;
  published: number;
  oldest_unpublished_age_seconds: number | null;
}

/** Events already committed, so the stream page is not empty before one arrives. */
export function useRecentEvents(limit = 50) {
  return useQuery({
    queryKey: keys.events(limit),
    queryFn: () =>
      api<Paginated<import("@/lib/useEventStream").DomainEvent>>(
        `/events/?limit=${limit}`,
      ),
  });
}

/** Relay lag. A backlog that grows means the relay has stopped. */
export function useOutboxHealth() {
  return useQuery({
    queryKey: keys.outboxHealth(),
    queryFn: () => api<OutboxHealth>("/events/health"),
    refetchInterval: 5_000,
  });
}

export function useWarehouses() {
  return useQuery({
    queryKey: keys.warehouses(),
    queryFn: () => api<Paginated<Warehouse>>("/warehouses/?limit=100"),
    // Warehouses change about once a year.
    staleTime: 5 * 60_000,
  });
}

export function useRecommendations() {
  return useQuery({
    queryKey: keys.recommendations(),
    queryFn: () => api<Paginated<Recommendation>>("/recommendations/?limit=50"),
  });
}

/* -------------------------------------------------------------------------- */
/* Assistant proposals                                                         */
/* -------------------------------------------------------------------------- */

export interface ProposedOrder {
  sku: string;
  product_id: string;
  product_name: string;
  quantity: number;
  unit_cost: number;
  estimated_total: number;
  warehouse_id: string;
  warehouse_name: string;
  supplier_id: string;
  supplier_name: string;
}

export interface AssistantAction {
  id: string;
  action_type: string;
  status: "proposed" | "approved" | "rejected" | "failed" | "expired";
  proposed: ProposedOrder;
  executed: ProposedOrder | null;
  rationale: string | null;
  source_question: string | null;
  model: string | null;
  proposed_at: string;
  expires_at: string;
  decided_at: string | null;
  result_id: string | null;
  error: string | null;
  is_actionable: boolean;
  /** True when the approver changed what the model asked for. */
  amended: boolean;
}

export function useAssistantActions(status?: string) {
  return useQuery({
    queryKey: keys.assistantActions(status),
    queryFn: () =>
      api<{ actions: AssistantAction[] }>(
        `/assistant/actions${status ? `?status=${status}` : ""}`,
      ),
    // Short, because a proposal made in the Assistant tab should be waiting on
    // the Approvals tab by the time the user switches to it.
    staleTime: 10_000,
  });
}

/**
 * Approve or reject one proposal.
 *
 * Both verbs share a hook because they share everything that matters: the same
 * row, the same invalidation, the same optimistic-update hazard. `quantity`
 * amends the order before it runs.
 */
export function useDecideAction() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      decision,
      quantity,
      reason,
    }: {
      id: string;
      decision: "approve" | "reject";
      quantity?: number;
      reason?: string;
    }) =>
      api<AssistantAction>(`/assistant/actions/${id}/${decision}`, {
        method: "POST",
        body: JSON.stringify({ quantity, reason }),
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["assistant", "actions"] });
      // An approval creates a purchase order, so anything counting them is now
      // wrong. Cheaper to refetch than to reason about which panels care.
      void client.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}

/* -------------------------------------------------------------------------- */
/* Stockout risk                                                               */
/* -------------------------------------------------------------------------- */

export interface StockoutRisk {
  product_id: string;
  warehouse_id: string;
  sku: string;
  product_name: string;
  warehouse_name: string;
  on_hand: number;
  reorder_point: number;
  daily_usage: number;
  days_remaining: number | null;
  stockout_date: string | null;
  days_to_reorder_point: number | null;
  severity: "critical" | "warning" | "watch" | "ok" | "idle";
  units_sold: number;
  active_days: number;
  confidence: "high" | "medium" | "low";
  lookback_days: number;
  /** One checkable sentence, computed server-side so every surface agrees. */
  explanation: string;
}

export interface StockoutSummary {
  counts: Record<StockoutRisk["severity"], number>;
  at_risk: number;
  soonest: {
    sku: string;
    days_remaining: number;
    warehouse_name: string;
  } | null;
}

export function useStockoutRisk(lookbackDays = 30) {
  return useQuery({
    queryKey: ["insights", "stockout-risk", lookbackDays] as const,
    queryFn: () =>
      api<{
        lookback_days: number;
        summary: StockoutSummary;
        data: StockoutRisk[];
      }>(`/insights/stockout-risk?lookback_days=${lookbackDays}&limit=200`),
    staleTime: 60_000,
  });
}
