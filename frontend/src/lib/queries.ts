/**
 * Typed API surface + React Query hooks.
 *
 * The types here mirror the FastAPI response schemas. They are hand-written for
 * now; once the surface settles, generating them from the OpenAPI document
 * removes the chance of drifting out of sync with the backend.
 */

import { useQuery } from "@tanstack/react-query";

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
