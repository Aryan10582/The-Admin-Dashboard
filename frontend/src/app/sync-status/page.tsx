"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { AppShell } from "@/components/layout/AppShell";
import { StatusBadge } from "@/components/status/StatusBadge";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import {
  getSyncStatus,
  listFailures,
  syncProduct,
  syncProductHealth,
  syncProductOrganizations,
  type FailureFilters
} from "@/lib/sync";

function statusTone(status: string) {
  if (["healthy", "synced", "active", "confirmed_and_synced"].includes(status)) return "success";
  if (["slow", "pending", "pending_retry", "sent_to_product", "accepted_by_product"].includes(status)) return "warning";
  if (["down", "not_responding", "failed", "requires_manual_resolution"].includes(status)) return "danger";
  return "neutral";
}

function formatDate(value: string | null) {
  return value ? new Date(value).toLocaleString() : "-";
}

function countFor(counts: Record<string, number>, key: string) {
  return counts[key] ?? 0;
}

export default function SyncStatusPage() {
  const queryClient = useQueryClient();
  const [filters, setFilters] = useState<FailureFilters>({ limit: 25, offset: 0 });
  const syncStatusQuery = useQuery({ queryKey: ["sync-status"], queryFn: getSyncStatus });
  const failuresQuery = useQuery({ queryKey: ["failures", filters], queryFn: () => listFailures(filters) });

  const refreshOperationalData = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["sync-status"] }),
      queryClient.invalidateQueries({ queryKey: ["failures"] }),
      queryClient.invalidateQueries({ queryKey: ["pending-changes"] })
    ]);
  };

  const productSyncMutation = useMutation({ mutationFn: syncProduct, onSuccess: refreshOperationalData });
  const healthSyncMutation = useMutation({ mutationFn: syncProductHealth, onSuccess: refreshOperationalData });
  const mappingSyncMutation = useMutation({ mutationFn: syncProductOrganizations, onSuccess: refreshOperationalData });

  const products = syncStatusQuery.data?.data.items ?? [];
  const failures = failuresQuery.data?.data.items ?? [];
  const total = failuresQuery.data?.data.total ?? 0;
  const offset = filters.offset ?? 0;
  const limit = filters.limit ?? 25;
  const actionError = productSyncMutation.error ?? healthSyncMutation.error ?? mappingSyncMutation.error;

  return (
    <AppShell>
      <div className="space-y-5">
        <div>
          <h1 className="text-2xl font-semibold">Sync Status</h1>
          <p className="mt-1 text-sm text-muted-foreground">Manual delivery controls for saved product-affecting changes. Product confirmation is required before a change is treated as synced.</p>
        </div>

        <section className="rounded-md border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
          Manual sync actions call product admin APIs from the backend only. Results may be partial; accepted or pending changes still require product confirmation.
        </section>

        {syncStatusQuery.isLoading ? <p className="text-sm text-muted-foreground">Loading sync status...</p> : null}
        {syncStatusQuery.isError ? <p className="text-sm text-red-700">{syncStatusQuery.error.message}</p> : null}
        {actionError ? <p className="text-sm text-red-700">{actionError.message}</p> : null}

        <section className="overflow-x-auto rounded-md border border-border bg-white">
          <table className="w-full text-left text-sm">
            <thead className="bg-muted text-xs uppercase text-muted-foreground">
              <tr>
                <th className="px-3 py-2">Product</th>
                <th className="px-3 py-2">Health</th>
                <th className="px-3 py-2">Compatibility</th>
                <th className="px-3 py-2">Last Health</th>
                <th className="px-3 py-2">Last Confirmed</th>
                <th className="px-3 py-2">Counts</th>
                <th className="px-3 py-2">Latest Failure</th>
                <th className="px-3 py-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {products.map((product) => (
                <tr key={product.product_id} className="border-t border-border align-top">
                  <td className="px-3 py-2">
                    <div className="font-medium">{product.product_name}</div>
                    <div className="text-xs text-muted-foreground">{product.region} / {product.environment}</div>
                  </td>
                  <td className="px-3 py-2"><StatusBadge tone={statusTone(product.health_status)}>{product.health_status}</StatusBadge></td>
                  <td className="px-3 py-2">{product.compatibility_status}</td>
                  <td className="px-3 py-2">{formatDate(product.last_health_check)}</td>
                  <td className="px-3 py-2">{formatDate(product.last_confirmed_delivery)}</td>
                  <td className="px-3 py-2">
                    <div className="whitespace-nowrap">saved {countFor(product.counts, "saved")} / retry {countFor(product.counts, "pending_retry")}</div>
                    <div className="whitespace-nowrap">accepted {countFor(product.counts, "accepted_by_product")} / manual {countFor(product.counts, "requires_manual_resolution")}</div>
                    {product.has_ordering_blocker ? <div className="mt-1 text-xs text-amber-700">Ordering blocker present</div> : null}
                  </td>
                  <td className="max-w-xs px-3 py-2">{product.latest_failure ?? "-"}</td>
                  <td className="px-3 py-2">
                    <div className="flex flex-wrap gap-2">
                      <Button type="button" variant="secondary" disabled={productSyncMutation.isPending} onClick={() => productSyncMutation.mutate(product.product_id)}>Sync</Button>
                      <Button type="button" variant="secondary" disabled={healthSyncMutation.isPending} onClick={() => healthSyncMutation.mutate(product.product_id)}>Health</Button>
                      <Button type="button" variant="secondary" disabled={mappingSyncMutation.isPending} onClick={() => mappingSyncMutation.mutate(product.product_id)}>Mappings</Button>
                    </div>
                  </td>
                </tr>
              ))}
              {!products.length && !syncStatusQuery.isLoading ? (
                <tr><td className="px-3 py-4 text-muted-foreground" colSpan={8}>No products found.</td></tr>
              ) : null}
            </tbody>
          </table>
        </section>

        <section className="space-y-3 rounded-md border border-border bg-white p-4">
          <div>
            <h2 className="text-base font-semibold">Failure Logs</h2>
            <p className="mt-1 text-sm text-muted-foreground">Safe product delivery and mapping failures only; secrets and raw product responses are not shown.</p>
          </div>
          <div className="grid gap-3 md:grid-cols-5">
            <Input placeholder="Product ID" value={filters.product_deployment_id ?? ""} onChange={(event) => setFilters({ ...filters, product_deployment_id: event.target.value, offset: 0 })} />
            <Input placeholder="Organization ID" value={filters.organization_id ?? ""} onChange={(event) => setFilters({ ...filters, organization_id: event.target.value, offset: 0 })} />
            <Input placeholder="Pending change ID" value={filters.pending_change_id ?? ""} onChange={(event) => setFilters({ ...filters, pending_change_id: event.target.value, offset: 0 })} />
            <Input placeholder="Failure category" value={filters.failure_category ?? ""} onChange={(event) => setFilters({ ...filters, failure_category: event.target.value, offset: 0 })} />
            <Input placeholder="Action" value={filters.action ?? ""} onChange={(event) => setFilters({ ...filters, action: event.target.value, offset: 0 })} />
          </div>
          {failuresQuery.isError ? <p className="text-sm text-red-700">{failuresQuery.error.message}</p> : null}
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-muted text-xs uppercase text-muted-foreground">
                <tr>
                  <th className="px-3 py-2">Created</th>
                  <th className="px-3 py-2">Action</th>
                  <th className="px-3 py-2">Category</th>
                  <th className="px-3 py-2">Safe Error</th>
                  <th className="px-3 py-2">Retries</th>
                  <th className="px-3 py-2">Status</th>
                  <th className="px-3 py-2">Product Request</th>
                </tr>
              </thead>
              <tbody>
                {failures.map((failure) => (
                  <tr key={failure.id} className="border-t border-border">
                    <td className="px-3 py-2">{formatDate(failure.created_at)}</td>
                    <td className="px-3 py-2">{failure.action_attempted}</td>
                    <td className="px-3 py-2">{failure.error_code ?? "-"}</td>
                    <td className="max-w-md px-3 py-2">{failure.error_message}</td>
                    <td className="px-3 py-2">{failure.retry_count}</td>
                    <td className="px-3 py-2"><StatusBadge tone={statusTone(failure.current_status)}>{failure.current_status}</StatusBadge></td>
                    <td className="px-3 py-2">{failure.product_request_id ?? "-"}</td>
                  </tr>
                ))}
                {!failures.length && !failuresQuery.isLoading ? (
                  <tr><td className="px-3 py-4 text-muted-foreground" colSpan={7}>No failure logs found.</td></tr>
                ) : null}
              </tbody>
            </table>
          </div>
          <div className="flex items-center gap-2">
            <Button type="button" variant="secondary" disabled={offset === 0} onClick={() => setFilters({ ...filters, offset: Math.max(0, offset - limit) })}>Previous</Button>
            <span className="text-sm text-muted-foreground">{total ? offset + 1 : 0} - {Math.min(offset + limit, total)} of {total}</span>
            <Button type="button" variant="secondary" disabled={offset + limit >= total} onClick={() => setFilters({ ...filters, offset: offset + limit })}>Next</Button>
          </div>
        </section>
      </div>
    </AppShell>
  );
}
