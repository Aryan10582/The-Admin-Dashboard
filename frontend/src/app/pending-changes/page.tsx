"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";

import { AppShell } from "@/components/layout/AppShell";
import { StatusBadge } from "@/components/status/StatusBadge";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import {
  cancelPendingChange,
  listPendingChanges,
  markPendingChangeManualResolution,
  retryPendingChange,
  type PendingChangeFilters
} from "@/lib/pendingChanges";
import type { PendingChange } from "@/lib/types";

type ActionValues = {
  reason: string;
  idempotency_key: string;
};

function statusTone(status: string) {
  if (status === "saved") return "warning";
  if (status === "confirmed_and_synced") return "success";
  if (["failed", "requires_manual_resolution"].includes(status)) return "danger";
  return "neutral";
}

export default function PendingChangesPage() {
  const queryClient = useQueryClient();
  const [filters, setFilters] = useState<PendingChangeFilters>({ limit: 25, offset: 0 });
  const [selected, setSelected] = useState<PendingChange | null>(null);
  const actionForm = useForm<ActionValues>({ defaultValues: { reason: "", idempotency_key: "" } });
  const pendingQuery = useQuery({ queryKey: ["pending-changes", filters], queryFn: () => listPendingChanges(filters) });

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["pending-changes"] });
  };

  const cancelMutation = useMutation({
    mutationFn: (values: ActionValues & { id: string }) =>
      cancelPendingChange(values.id, { reason: values.reason }, values.idempotency_key),
    onSuccess: async () => {
      actionForm.reset({ reason: "", idempotency_key: "" });
      setSelected(null);
      await refresh();
    }
  });

  const manualResolutionMutation = useMutation({
    mutationFn: (values: ActionValues & { id: string }) =>
      markPendingChangeManualResolution(values.id, { reason: values.reason }, values.idempotency_key),
    onSuccess: async () => {
      actionForm.reset({ reason: "", idempotency_key: "" });
      setSelected(null);
      await refresh();
    }
  });

  const retryMutation = useMutation({
    mutationFn: (values: ActionValues & { id: string }) =>
      retryPendingChange(values.id, { reason: values.reason }, values.idempotency_key),
    onSuccess: async () => {
      actionForm.reset({ reason: "", idempotency_key: "" });
      setSelected(null);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["pending-changes"] }),
        queryClient.invalidateQueries({ queryKey: ["sync-status"] }),
        queryClient.invalidateQueries({ queryKey: ["failures"] })
      ]);
    }
  });

  const runAction = (kind: "cancel" | "manual_resolution" | "retry") => {
    if (!selected) return;
    const values = actionForm.getValues();
    if (!values.reason.trim() || !values.idempotency_key.trim()) {
      actionForm.setError("reason", { message: "Reason and idempotency key are required." });
      return;
    }
    if (kind === "cancel") {
      cancelMutation.mutate({ ...values, id: selected.id });
    } else if (kind === "manual_resolution") {
      manualResolutionMutation.mutate({ ...values, id: selected.id });
    } else {
      retryMutation.mutate({ ...values, id: selected.id });
    }
  };

  const items = pendingQuery.data?.data.items ?? [];
  const total = pendingQuery.data?.data.total ?? 0;
  const offset = filters.offset ?? 0;
  const limit = filters.limit ?? 25;

  return (
    <AppShell>
      <div className="space-y-5">
        <div>
          <h1 className="text-2xl font-semibold">Pending Changes</h1>
          <p className="mt-1 text-sm text-muted-foreground">Saved operations waiting for future product delivery or manual handling.</p>
        </div>

        <section className="rounded-md border border-border bg-white p-4">
          <div className="grid gap-3 md:grid-cols-5">
            <Input placeholder="Status" value={filters.status ?? ""} onChange={(event) => setFilters({ ...filters, status: event.target.value, offset: 0 })} />
            <Input placeholder="Action" value={filters.action ?? ""} onChange={(event) => setFilters({ ...filters, action: event.target.value, offset: 0 })} />
            <Input placeholder="Organization ID" value={filters.organization_id ?? ""} onChange={(event) => setFilters({ ...filters, organization_id: event.target.value, offset: 0 })} />
            <Input placeholder="Product" value={filters.product_name ?? ""} onChange={(event) => setFilters({ ...filters, product_name: event.target.value, offset: 0 })} />
            <Input placeholder="Region" value={filters.region ?? ""} onChange={(event) => setFilters({ ...filters, region: event.target.value, offset: 0 })} />
          </div>
        </section>

        {pendingQuery.isError ? <p className="text-sm text-red-700">{pendingQuery.error.message}</p> : null}

        <section className="overflow-x-auto rounded-md border border-border bg-white">
          <table className="w-full text-left text-sm">
            <thead className="bg-muted text-xs uppercase text-muted-foreground">
              <tr>
                <th className="px-3 py-2">Created</th>
                <th className="px-3 py-2">Action</th>
                <th className="px-3 py-2">Product</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2">Retries</th>
                <th className="px-3 py-2">Reason</th>
                <th className="px-3 py-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id} className="border-t border-border">
                  <td className="px-3 py-2">{new Date(item.created_at).toLocaleString()}</td>
                  <td className="px-3 py-2">{item.action}</td>
                  <td className="px-3 py-2">{item.product_name ?? "-"} / {item.region ?? "-"} / {item.environment ?? "-"}</td>
                  <td className="px-3 py-2"><StatusBadge tone={statusTone(item.status)}>{item.status}</StatusBadge></td>
                  <td className="px-3 py-2">{item.retry_count}</td>
                  <td className="px-3 py-2">{item.reason ?? "-"}</td>
                  <td className="px-3 py-2">
                    <Button type="button" variant="secondary" onClick={() => setSelected(item)}>Select</Button>
                  </td>
                </tr>
              ))}
              {!items.length ? (
                <tr><td className="px-3 py-4 text-muted-foreground" colSpan={7}>No pending changes found.</td></tr>
              ) : null}
            </tbody>
          </table>
        </section>

        <div className="flex items-center gap-2">
          <Button type="button" variant="secondary" disabled={offset === 0} onClick={() => setFilters({ ...filters, offset: Math.max(0, offset - limit) })}>Previous</Button>
          <span className="text-sm text-muted-foreground">{offset + 1} - {Math.min(offset + limit, total)} of {total}</span>
          <Button type="button" variant="secondary" disabled={offset + limit >= total} onClick={() => setFilters({ ...filters, offset: offset + limit })}>Next</Button>
        </div>

        {selected ? (
          <section className="rounded-md border border-border bg-white p-4">
            <h2 className="text-base font-semibold">{selected.action}</h2>
            <p className="mt-1 text-sm text-muted-foreground">Selected change {selected.id}</p>
            <div className="mt-3 grid gap-2 text-sm text-muted-foreground md:grid-cols-3">
              <p>Status: <span className="font-medium text-foreground">{selected.status}</span></p>
              <p>Product request: <span className="font-medium text-foreground">{selected.product_request_id ?? "-"}</span></p>
              <p>Last delivery: <span className="font-medium text-foreground">{selected.last_delivery_at ? new Date(selected.last_delivery_at).toLocaleString() : "-"}</span></p>
            </div>
            <div className="mt-4 grid gap-3 md:grid-cols-2">
              <Input placeholder="Reason / note" {...actionForm.register("reason", { required: true })} />
              <Input placeholder="Idempotency key" {...actionForm.register("idempotency_key", { required: true })} />
            </div>
            {actionForm.formState.errors.reason ? <p className="mt-2 text-sm text-red-700">{actionForm.formState.errors.reason.message}</p> : null}
            <div className="mt-4 flex flex-wrap gap-2">
              <Button type="button" disabled={!selected.can_cancel || cancelMutation.isPending} onClick={() => runAction("cancel")}>Cancel</Button>
              <Button type="button" variant="secondary" disabled={manualResolutionMutation.isPending} onClick={() => runAction("manual_resolution")}>Mark Manual Resolution</Button>
              <Button type="button" variant="secondary" disabled={!selected.can_retry || retryMutation.isPending} onClick={() => runAction("retry")}>Retry Delivery</Button>
            </div>
            {!selected.can_cancel ? <p className="mt-2 text-sm text-muted-foreground">This change is not safely cancellable.</p> : null}
            {!selected.can_retry ? <p className="mt-2 text-sm text-muted-foreground">This change is not eligible for retry unless the backend reports it as retryable.</p> : null}
            {cancelMutation.isError ? <p className="mt-2 text-sm text-red-700">{cancelMutation.error.message}</p> : null}
            {manualResolutionMutation.isError ? <p className="mt-2 text-sm text-red-700">{manualResolutionMutation.error.message}</p> : null}
            {retryMutation.isError ? <p className="mt-2 text-sm text-red-700">{retryMutation.error.message}</p> : null}
            {retryMutation.data ? (
              <p className="mt-2 text-sm text-muted-foreground">
                Delivery result: {retryMutation.data.data.status === "confirmed_and_synced" ? "confirmed_and_synced" : retryMutation.data.data.status}
              </p>
            ) : null}
          </section>
        ) : null}
      </div>
    </AppShell>
  );
}
