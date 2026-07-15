"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { AppShell } from "@/components/layout/AppShell";
import { StatusBadge } from "@/components/status/StatusBadge";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import {
  getAiUsageConflict,
  listAiUsage,
  markAiUsageConflictReviewed,
  resolveAiUsagePricing,
  resolveMappings,
  resolveMissingPricing,
  summarizeAiUsage,
  syncProductAiUsage,
  type AiUsageFilters
} from "@/lib/aiUsage";
import { listProducts } from "@/lib/products";
import type { AiUsageRecord } from "@/lib/types";

function tone(status: string) {
  if (["resolved", "finalized", "none", "success"].includes(status)) return "success";
  if (["requires_pricing_resolution", "requires_mapping_resolution", "non_final", "partial_success"].includes(status)) return "warning";
  if (["conflict", "invalid", "failed", "unsupported_dimensions"].includes(status)) return "danger";
  return "neutral";
}

function date(value: string | null) {
  return value ? new Date(value).toLocaleString() : "-";
}

function money(value: string | null, currency: string | null) {
  return value && currency ? `${value} ${currency}` : "-";
}

export default function AiUsagePage() {
  const queryClient = useQueryClient();
  const [filters, setFilters] = useState<AiUsageFilters>({ limit: 25, offset: 0 });
  const [action, setAction] = useState({ usageId: "", selectedProductId: "", pricingVersionId: "", reason: "", idempotencyKey: "" });
  const [conflictUsageId, setConflictUsageId] = useState("");

  const usageQuery = useQuery({ queryKey: ["ai-usage", filters], queryFn: () => listAiUsage(filters) });
  const summaryQuery = useQuery({ queryKey: ["ai-usage-summary", filters], queryFn: () => summarizeAiUsage(filters) });
  const productsQuery = useQuery({ queryKey: ["products"], queryFn: listProducts });
  const conflictQuery = useQuery({ queryKey: ["ai-usage-conflict", conflictUsageId], queryFn: () => getAiUsageConflict(conflictUsageId), enabled: Boolean(conflictUsageId) });

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["ai-usage"] });
    await queryClient.invalidateQueries({ queryKey: ["ai-usage-summary"] });
    await queryClient.invalidateQueries({ queryKey: ["ai-usage-conflict"] });
    await queryClient.invalidateQueries({ queryKey: ["sync-status"] });
  };

  const syncMutation = useMutation({
    mutationFn: () => syncProductAiUsage(action.selectedProductId, { reason: action.reason, limit: 100, max_pages: 5 }, action.idempotencyKey),
    onSuccess: refresh
  });
  const resolveOneMutation = useMutation({
    mutationFn: () => resolveAiUsagePricing(action.usageId, { reason: action.reason, pricing_version_id: action.pricingVersionId || null }, action.idempotencyKey),
    onSuccess: refresh
  });
  const resolvePricingMutation = useMutation({
    mutationFn: () => resolveMissingPricing({ reason: action.reason, product_deployment_id: filters.product_deployment_id || null, limit: 50 }, action.idempotencyKey),
    onSuccess: refresh
  });
  const resolveMappingsMutation = useMutation({
    mutationFn: () => resolveMappings({ reason: action.reason, product_deployment_id: filters.product_deployment_id || null, limit: 50 }, action.idempotencyKey),
    onSuccess: refresh
  });
  const reviewMutation = useMutation({
    mutationFn: () => markAiUsageConflictReviewed(conflictUsageId, { reason: action.reason }, action.idempotencyKey),
    onSuccess: refresh
  });

  const rows = usageQuery.data?.data.items ?? [];
  const summary = summaryQuery.data?.data;
  const products = productsQuery.data?.data ?? [];
  const offset = filters.offset ?? 0;
  const limit = filters.limit ?? 25;
  const total = usageQuery.data?.data.total ?? 0;
  const actionError = syncMutation.error ?? resolveOneMutation.error ?? resolvePricingMutation.error ?? resolveMappingsMutation.error ?? reviewMutation.error;
  const selectedProduct = products.find((product) => product.id === action.selectedProductId) ?? null;

  const updateFilter = (key: keyof AiUsageFilters, value: string) => setFilters({ ...filters, [key]: value, offset: 0 });
  const canSubmitAction = action.reason.trim() && action.idempotencyKey.trim();
  const canSyncUsage = Boolean(canSubmitAction && selectedProduct?.ai_usage_sync_configured);

  return (
    <AppShell>
      <div className="space-y-5">
        <div>
          <h1 className="text-2xl font-semibold">AI Usage</h1>
          <p className="mt-1 text-sm text-muted-foreground">Operational token usage, pricing resolution, mapping resolution, and conflict review from the Admin backend.</p>
        </div>

        <section className="grid gap-3 rounded-md border border-border bg-white p-4 md:grid-cols-4">
          <select className="h-10 rounded-md border border-border bg-white px-3 text-sm" value={filters.product_deployment_id ?? ""} onChange={(event) => updateFilter("product_deployment_id", event.target.value)}>
            <option value="">All products</option>
            {products.map((product) => <option key={product.id} value={product.id}>{product.product_name} / {product.region}</option>)}
          </select>
          <Input placeholder="Organization ID" value={filters.organization_id ?? ""} onChange={(event) => updateFilter("organization_id", event.target.value)} />
          <Input placeholder="Product organization ID" value={filters.product_organization_id ?? ""} onChange={(event) => updateFilter("product_organization_id", event.target.value)} />
          <Input placeholder="Product usage ID" value={filters.product_usage_id ?? ""} onChange={(event) => updateFilter("product_usage_id", event.target.value)} />
          <Input placeholder="Provider" value={filters.provider ?? ""} onChange={(event) => updateFilter("provider", event.target.value)} />
          <Input placeholder="Product model ID" value={filters.product_model_id ?? ""} onChange={(event) => updateFilter("product_model_id", event.target.value)} />
          <Input placeholder="Cost currency" value={filters.cost_currency ?? ""} onChange={(event) => updateFilter("cost_currency", event.target.value)} />
          <select className="h-10 rounded-md border border-border bg-white px-3 text-sm" value={filters.pricing_resolution_status ?? ""} onChange={(event) => updateFilter("pricing_resolution_status", event.target.value)}>
            <option value="">Any pricing status</option><option value="resolved">resolved</option><option value="requires_pricing_resolution">requires_pricing_resolution</option><option value="unsupported_dimensions">unsupported_dimensions</option>
          </select>
          <select className="h-10 rounded-md border border-border bg-white px-3 text-sm" value={filters.mapping_resolution_status ?? ""} onChange={(event) => updateFilter("mapping_resolution_status", event.target.value)}>
            <option value="">Any mapping status</option><option value="resolved">resolved</option><option value="requires_mapping_resolution">requires_mapping_resolution</option>
          </select>
          <select className="h-10 rounded-md border border-border bg-white px-3 text-sm" value={filters.conflict_status ?? ""} onChange={(event) => updateFilter("conflict_status", event.target.value)}>
            <option value="">Any conflict status</option><option value="none">none</option><option value="conflict">conflict</option>
          </select>
          <Input type="datetime-local" value={filters.usage_from ?? ""} onChange={(event) => updateFilter("usage_from", event.target.value)} />
          <Input type="datetime-local" value={filters.usage_to ?? ""} onChange={(event) => updateFilter("usage_to", event.target.value)} />
        </section>

        {summary ? (
          <section className="grid gap-3 md:grid-cols-4">
            <div className="rounded-md border border-border bg-white p-4"><p className="text-xs uppercase text-muted-foreground">Records</p><p className="mt-1 text-xl font-semibold">{summary.usage_record_count}</p></div>
            <div className="rounded-md border border-border bg-white p-4"><p className="text-xs uppercase text-muted-foreground">Tokens</p><p className="mt-1 text-xl font-semibold">{summary.total_tokens}</p><p className="text-xs text-muted-foreground">in {summary.input_tokens} / out {summary.output_tokens}</p></div>
            <div className="rounded-md border border-border bg-white p-4"><p className="text-xs uppercase text-muted-foreground">Unresolved</p><p className="mt-1 text-xl font-semibold">{summary.unpriced_usage_count + summary.unmapped_usage_count}</p><p className="text-xs text-muted-foreground">pricing {summary.unpriced_usage_count} / mapping {summary.unmapped_usage_count}</p></div>
            <div className="rounded-md border border-border bg-white p-4"><p className="text-xs uppercase text-muted-foreground">Conflicts</p><p className="mt-1 text-xl font-semibold">{summary.conflict_count}</p><p className="text-xs text-muted-foreground">unreviewed {summary.unreviewed_conflict_count}</p></div>
            <div className="rounded-md border border-border bg-white p-4 md:col-span-2"><p className="text-xs uppercase text-muted-foreground">Finalized Cost by Currency</p><div className="mt-2 flex flex-wrap gap-2">{summary.finalized_costs_by_currency.length ? summary.finalized_costs_by_currency.map((item) => <StatusBadge key={item.currency} tone="success">{`${item.total_cost} ${item.currency}`}</StatusBadge>) : <span className="text-sm text-muted-foreground">No finalized cost</span>}</div></div>
            <div className="rounded-md border border-border bg-white p-4 md:col-span-2"><p className="text-xs uppercase text-muted-foreground">Provider / Model Breakdown</p><div className="mt-2 space-y-1 text-sm">{summary.provider_model_breakdown.slice(0, 4).map((item) => <div key={`${item.provider}-${item.product_model_id}`}>{item.provider} / {item.product_model_id ?? "-"}: {item.total_tokens} tokens</div>)}</div></div>
          </section>
        ) : null}

        <section className="rounded-md border border-border bg-white p-4">
          <div className="grid gap-3 md:grid-cols-5">
            <Input placeholder="Usage ID for single action" value={action.usageId} onChange={(event) => setAction({ ...action, usageId: event.target.value })} />
            <select
              className="h-10 rounded-md border border-border bg-white px-3 text-sm"
              value={action.selectedProductId}
              onChange={(event) => setAction({ ...action, selectedProductId: event.target.value })}
            >
              <option value="">Select product for sync</option>
              {products.map((product) => (
                <option key={product.id} value={product.id}>
                  {product.product_name} / {product.region} / {product.environment} / {product.ai_usage_sync_configured ? "Configured" : "Not configured"}
                </option>
              ))}
            </select>
            <Input placeholder="Exact pricing version ID" value={action.pricingVersionId} onChange={(event) => setAction({ ...action, pricingVersionId: event.target.value })} />
            <Input placeholder="Reason / safe note" value={action.reason} onChange={(event) => setAction({ ...action, reason: event.target.value })} />
            <Input placeholder="Idempotency key" value={action.idempotencyKey} onChange={(event) => setAction({ ...action, idempotencyKey: event.target.value })} />
          </div>
          {!action.selectedProductId ? <p className="mt-2 text-sm text-muted-foreground">Select a product deployment to sync usage.</p> : null}
          {selectedProduct && !selectedProduct.ai_usage_sync_configured ? (
            <p className="mt-2 text-sm text-amber-700">AI usage sync is not configured for this product. Add a Token Usage API Path in Product settings.</p>
          ) : null}
          {selectedProduct?.ai_usage_sync_configured ? (
            <div className="mt-2 text-sm text-muted-foreground">
              <span>AI usage sync configured.</span>
              <span className="ml-3">Last successful import: {date(selectedProduct.last_successful_usage_sync_at)}</span>
              <span className="ml-3">Last attempt: {date(selectedProduct.last_usage_sync_attempt_at)}</span>
            </div>
          ) : null}
          <div className="mt-3 flex flex-wrap gap-2">
            <Button type="button" disabled={!canSyncUsage || syncMutation.isPending} onClick={() => syncMutation.mutate()}>Sync Usage</Button>
            <Button type="button" variant="secondary" disabled={!canSubmitAction || !action.usageId || resolveOneMutation.isPending} onClick={() => resolveOneMutation.mutate()}>Resolve Pricing</Button>
            <Button type="button" variant="secondary" disabled={!canSubmitAction || resolvePricingMutation.isPending} onClick={() => resolvePricingMutation.mutate()}>Resolve Missing Pricing</Button>
            <Button type="button" variant="secondary" disabled={!canSubmitAction || resolveMappingsMutation.isPending} onClick={() => resolveMappingsMutation.mutate()}>Resolve Mappings</Button>
            <Button type="button" variant="secondary" disabled={!canSubmitAction || !conflictUsageId || reviewMutation.isPending} onClick={() => reviewMutation.mutate()}>Mark Conflict Reviewed</Button>
          </div>
          {actionError ? <p className="mt-2 text-sm text-red-700">{actionError.message}</p> : null}
        </section>

        {usageQuery.isLoading ? <p className="text-sm text-muted-foreground">Loading AI usage...</p> : null}
        {usageQuery.isError ? <p className="text-sm text-red-700">{usageQuery.error.message}</p> : null}

        <section className="overflow-x-auto rounded-md border border-border bg-white">
          <table className="w-full text-left text-sm">
            <thead className="bg-muted text-xs uppercase text-muted-foreground">
              <tr><th className="px-3 py-2">Usage</th><th className="px-3 py-2">Product Org</th><th className="px-3 py-2">Provider / Model</th><th className="px-3 py-2">Tokens</th><th className="px-3 py-2">Pricing</th><th className="px-3 py-2">Cost</th><th className="px-3 py-2">Status</th><th className="px-3 py-2">Conflict</th></tr>
            </thead>
            <tbody>
              {rows.map((row: AiUsageRecord) => (
                <tr key={row.id} className="border-t border-border align-top">
                  <td className="px-3 py-2"><div>{date(row.usage_at)}</div><div className="text-xs text-muted-foreground">{row.product_usage_id}</div></td>
                  <td className="px-3 py-2"><div>{row.product_organization_id ?? "-"}</div><div className="text-xs text-muted-foreground">{row.organization_id ?? "unmapped"}</div></td>
                  <td className="px-3 py-2">{row.provider} / {row.product_model_id ?? row.model_name}</td>
                  <td className="px-3 py-2">{row.total_tokens}<div className="text-xs text-muted-foreground">{row.input_tokens} in / {row.output_tokens} out</div></td>
                  <td className="px-3 py-2"><div>{row.pricing_version_id ?? "-"}</div><div className="text-xs text-muted-foreground">unit {row.pricing_unit_tokens ?? "-"}</div></td>
                  <td className="px-3 py-2">{money(row.total_cost, row.cost_currency)}<div className="text-xs text-muted-foreground">{money(row.input_cost, row.cost_currency)} / {money(row.output_cost, row.cost_currency)}</div></td>
                  <td className="space-y-1 px-3 py-2"><StatusBadge tone={tone(row.finalization_status)}>{row.finalization_status}</StatusBadge><StatusBadge tone={tone(row.pricing_resolution_status)}>{row.pricing_resolution_status}</StatusBadge><StatusBadge tone={tone(row.mapping_resolution_status)}>{row.mapping_resolution_status}</StatusBadge></td>
                  <td className="px-3 py-2"><button className="text-primary hover:underline" type="button" onClick={() => setConflictUsageId(row.id)}>{row.conflict_status}</button><div className="text-xs text-muted-foreground">{row.conflict_reviewed_at ? "reviewed" : "unreviewed"}</div></td>
                </tr>
              ))}
              {!rows.length && !usageQuery.isLoading ? <tr><td className="px-3 py-4 text-muted-foreground" colSpan={8}>No AI usage records match the filters.</td></tr> : null}
            </tbody>
          </table>
        </section>

        {conflictQuery.data ? (
          <section className="rounded-md border border-amber-200 bg-amber-50 p-4 text-sm">
            <h2 className="text-base font-semibold">Conflict Review</h2>
            <p className="mt-1 text-amber-800">Detected fields: {conflictQuery.data.data.detected_fields.join(", ") || "fingerprint only"}</p>
            <pre className="mt-3 max-h-64 overflow-auto rounded-md bg-white p-3 text-xs">{JSON.stringify({ original: conflictQuery.data.data.original, candidate: conflictQuery.data.data.candidate }, null, 2)}</pre>
          </section>
        ) : null}

        <div className="flex items-center gap-2">
          <Button type="button" variant="secondary" disabled={offset === 0} onClick={() => setFilters({ ...filters, offset: Math.max(0, offset - limit) })}>Previous</Button>
          <span className="text-sm text-muted-foreground">{total ? offset + 1 : 0} - {Math.min(offset + limit, total)} of {total}</span>
          <Button type="button" variant="secondary" disabled={offset + limit >= total} onClick={() => setFilters({ ...filters, offset: offset + limit })}>Next</Button>
        </div>
      </div>
    </AppShell>
  );
}
