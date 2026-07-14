"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";

import { AppShell } from "@/components/layout/AppShell";
import { StatusBadge } from "@/components/status/StatusBadge";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { listOrganizations, createOrganization, type OrganizationFilters } from "@/lib/organizations";
import { listProducts } from "@/lib/products";
import type { OrganizationPayload } from "@/lib/types";

const limit = 10;

const defaultValues: OrganizationPayload = {
  central_organization_id: "",
  name: "",
  product_deployment_id: "",
  currency: "USD",
  lifecycle_status: "trial",
  billing_mode: "prepaid_credits",
  billing_calculation_status: "usage_tracking_only",
  credit_status: "not_applicable",
  service_status: "pending_sync",
  sync_status: "pending",
  last_active_at: null
};

function statusTone(status: string) {
  if (["active", "healthy_balance", "running", "synced"].includes(status)) return "success";
  if (["trial", "pending", "pending_sync", "requires_manual_review", "low_balance"].includes(status)) return "warning";
  if (["suspended", "churned", "failed", "product_mismatch", "verification_failed", "balance_exhausted"].includes(status)) {
    return "danger";
  }
  return "neutral";
}

export default function OrganizationsPage() {
  const queryClient = useQueryClient();
  const [page, setPage] = useState(0);
  const [filters, setFilters] = useState<OrganizationFilters>({});
  const form = useForm<OrganizationPayload>({ defaultValues });

  const queryFilters = useMemo(() => ({ ...filters, limit, offset: page * limit }), [filters, page]);
  const organizationsQuery = useQuery({ queryKey: ["organizations", queryFilters], queryFn: () => listOrganizations(queryFilters) });
  const productsQuery = useQuery({ queryKey: ["products"], queryFn: listProducts });

  const createMutation = useMutation({
    mutationFn: createOrganization,
    onSuccess: async () => {
      form.reset(defaultValues);
      await queryClient.invalidateQueries({ queryKey: ["organizations"] });
    }
  });

  const total = organizationsQuery.data?.data.total ?? 0;
  const canGoBack = page > 0;
  const canGoForward = (page + 1) * limit < total;

  return (
    <AppShell>
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-semibold">Organizations</h1>
          <p className="mt-1 text-sm text-muted-foreground">Manage central organizations and product-side identity mapping.</p>
        </div>

        <section className="rounded-md border border-border bg-white p-5">
          <h2 className="text-base font-semibold">Filters</h2>
          <div className="mt-4 grid gap-3 md:grid-cols-4">
            <Input placeholder="Search name" onChange={(event) => setFilters((value) => ({ ...value, search: event.target.value }))} />
            <Input placeholder="Product name" onChange={(event) => setFilters((value) => ({ ...value, product_name: event.target.value }))} />
            <Input placeholder="Region" onChange={(event) => setFilters((value) => ({ ...value, region: event.target.value }))} />
            <Input placeholder="Currency" onChange={(event) => setFilters((value) => ({ ...value, currency: event.target.value }))} />
            <select className="h-10 rounded-md border border-border bg-white px-3 text-sm" onChange={(event) => setFilters((value) => ({ ...value, environment: event.target.value }))}>
              <option value="">Environment</option>
              <option value="production">production</option>
              <option value="staging">staging</option>
              <option value="testing">testing</option>
              <option value="development">development</option>
            </select>
            <select className="h-10 rounded-md border border-border bg-white px-3 text-sm" onChange={(event) => setFilters((value) => ({ ...value, lifecycle_status: event.target.value }))}>
              <option value="">Lifecycle</option>
              <option value="active">active</option>
              <option value="trial">trial</option>
              <option value="suspended">suspended</option>
              <option value="churned">churned</option>
              <option value="internal_testing">internal_testing</option>
              <option value="demo">demo</option>
            </select>
            <select className="h-10 rounded-md border border-border bg-white px-3 text-sm" onChange={(event) => setFilters((value) => ({ ...value, mapping_status: event.target.value }))}>
              <option value="">Mapping</option>
              <option value="active">active</option>
              <option value="missing_product_id">missing_product_id</option>
              <option value="product_mismatch">product_mismatch</option>
              <option value="verification_failed">verification_failed</option>
              <option value="requires_manual_review">requires_manual_review</option>
            </select>
            <Button type="button" variant="secondary" onClick={() => { setFilters({}); setPage(0); }}>
              Clear
            </Button>
          </div>
        </section>

        <section className="rounded-md border border-border bg-white p-5">
          <h2 className="text-base font-semibold">Create Organization</h2>
          <form className="mt-4 grid gap-4 md:grid-cols-3" onSubmit={form.handleSubmit((values) => createMutation.mutate(values))}>
            <Input placeholder="Central organization ID" {...form.register("central_organization_id", { required: true })} />
            <Input placeholder="Organization name" {...form.register("name", { required: true })} />
            <select className="h-10 rounded-md border border-border bg-white px-3 text-sm" {...form.register("product_deployment_id", { required: true })}>
              <option value="">Product deployment</option>
              {productsQuery.data?.data.map((product) => (
                <option key={product.id} value={product.id}>
                  {product.product_name} / {product.region} / {product.environment}
                </option>
              ))}
            </select>
            <Input placeholder="Currency" maxLength={3} {...form.register("currency", { required: true })} />
            <select className="h-10 rounded-md border border-border bg-white px-3 text-sm" {...form.register("lifecycle_status")}>
              <option value="trial">trial</option>
              <option value="active">active</option>
              <option value="suspended">suspended</option>
              <option value="churned">churned</option>
              <option value="internal_testing">internal_testing</option>
              <option value="demo">demo</option>
            </select>
            <select className="h-10 rounded-md border border-border bg-white px-3 text-sm" {...form.register("billing_mode")}>
              <option value="prepaid_credits">prepaid_credits</option>
              <option value="postpaid_manual_settlement">postpaid_manual_settlement</option>
              <option value="free_internal_testing">free_internal_testing</option>
            </select>
            <select className="h-10 rounded-md border border-border bg-white px-3 text-sm" {...form.register("credit_status")}>
              <option value="not_applicable">not_applicable</option>
              <option value="healthy_balance">healthy_balance</option>
              <option value="low_balance">low_balance</option>
              <option value="zero_balance">zero_balance</option>
              <option value="balance_exhausted">balance_exhausted</option>
              <option value="outstanding_dues">outstanding_dues</option>
            </select>
            <select className="h-10 rounded-md border border-border bg-white px-3 text-sm" {...form.register("service_status")}>
              <option value="pending_sync">pending_sync</option>
              <option value="running">running</option>
              <option value="paused">paused</option>
              <option value="disabled">disabled</option>
            </select>
            <select className="h-10 rounded-md border border-border bg-white px-3 text-sm" {...form.register("sync_status")}>
              <option value="pending">pending</option>
              <option value="synced">synced</option>
              <option value="failed">failed</option>
              <option value="retrying">retrying</option>
            </select>
            <div className="md:col-span-3">
              <Button type="submit" disabled={createMutation.isPending}>
                {createMutation.isPending ? "Creating..." : "Create"}
              </Button>
              {createMutation.isError ? <p className="mt-2 text-sm text-red-700">{createMutation.error.message}</p> : null}
            </div>
          </form>
        </section>

        <section className="rounded-md border border-border bg-white">
          <div className="flex items-center justify-between border-b border-border px-5 py-4">
            <h2 className="text-base font-semibold">Organization List</h2>
            <p className="text-sm text-muted-foreground">{total} total</p>
          </div>
          {organizationsQuery.isLoading ? <p className="p-5 text-sm text-muted-foreground">Loading organizations...</p> : null}
          {organizationsQuery.isError ? <p className="p-5 text-sm text-red-700">{organizationsQuery.error.message}</p> : null}
          {organizationsQuery.data?.data.items.length === 0 ? <p className="p-5 text-sm text-muted-foreground">No organizations found.</p> : null}
          {organizationsQuery.data?.data.items.length ? (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="bg-muted text-xs uppercase text-muted-foreground">
                  <tr>
                    <th className="px-4 py-3">Organization</th>
                    <th className="px-4 py-3">Product</th>
                    <th className="px-4 py-3">Region</th>
                    <th className="px-4 py-3">Environment</th>
                    <th className="px-4 py-3">Currency</th>
                    <th className="px-4 py-3">Billing</th>
                    <th className="px-4 py-3">Credit</th>
                    <th className="px-4 py-3">Service</th>
                    <th className="px-4 py-3">Sync</th>
                    <th className="px-4 py-3">Mapping</th>
                    <th className="px-4 py-3" />
                  </tr>
                </thead>
                <tbody>
                  {organizationsQuery.data.data.items.map((organization) => (
                    <tr key={organization.id} className="border-t border-border">
                      <td className="px-4 py-3 font-medium">{organization.name}</td>
                      <td className="px-4 py-3">{organization.product_deployment.product_name}</td>
                      <td className="px-4 py-3">{organization.product_deployment.region}</td>
                      <td className="px-4 py-3">{organization.product_deployment.environment}</td>
                      <td className="px-4 py-3">{organization.currency}</td>
                      <td className="px-4 py-3">{organization.billing_mode}</td>
                      <td className="px-4 py-3"><StatusBadge tone={statusTone(organization.credit_status)}>{organization.credit_status}</StatusBadge></td>
                      <td className="px-4 py-3"><StatusBadge tone={statusTone(organization.service_status)}>{organization.service_status}</StatusBadge></td>
                      <td className="px-4 py-3"><StatusBadge tone={statusTone(organization.sync_status)}>{organization.sync_status}</StatusBadge></td>
                      <td className="px-4 py-3"><StatusBadge tone={statusTone(organization.mapping?.mapping_status ?? "missing_product_id")}>{organization.mapping?.mapping_status ?? "missing_product_id"}</StatusBadge></td>
                      <td className="px-4 py-3">
                        <Link className="text-primary hover:underline" href={`/organizations/${organization.id}`}>
                          Details
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
          <div className="flex items-center gap-3 border-t border-border p-4">
            <Button type="button" variant="secondary" disabled={!canGoBack} onClick={() => setPage((value) => Math.max(0, value - 1))}>
              Previous
            </Button>
            <span className="text-sm text-muted-foreground">Page {page + 1}</span>
            <Button type="button" variant="secondary" disabled={!canGoForward} onClick={() => setPage((value) => value + 1)}>
              Next
            </Button>
          </div>
        </section>
      </div>
    </AppShell>
  );
}
