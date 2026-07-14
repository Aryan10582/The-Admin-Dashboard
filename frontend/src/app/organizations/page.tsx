"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useMemo, useState } from "react";

import { AppShell } from "@/components/layout/AppShell";
import { StatusBadge } from "@/components/status/StatusBadge";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { fetchProductOrganization, linkOrganizationFromProduct, listOrganizations, type OrganizationFilters } from "@/lib/organizations";
import { importAllProductOrganizations, importProductOrganizations, listDiscoveredOrganizations, listProducts } from "@/lib/products";

const limit = 10;

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
  const [selectedProductId, setSelectedProductId] = useState("");
  const [productOrganizationId, setProductOrganizationId] = useState("");
  const [manualReason, setManualReason] = useState("");
  const [manualName, setManualName] = useState("");
  const [manualCurrency, setManualCurrency] = useState("USD");
  const [manualBillingMode, setManualBillingMode] = useState("prepaid_credits");

  const queryFilters = useMemo(() => ({ ...filters, limit, offset: page * limit }), [filters, page]);
  const organizationsQuery = useQuery({ queryKey: ["organizations", queryFilters], queryFn: () => listOrganizations(queryFilters) });
  const productsQuery = useQuery({ queryKey: ["products"], queryFn: listProducts });
  const discoveriesQuery = useQuery({
    queryKey: ["product-discoveries", selectedProductId],
    queryFn: () => listDiscoveredOrganizations(selectedProductId),
    enabled: Boolean(selectedProductId)
  });

  const lookupMutation = useMutation({
    mutationFn: () => fetchProductOrganization({ product_deployment_id: selectedProductId, product_organization_id: productOrganizationId }),
    onSuccess: (response) => {
      setManualName(response.data.organization_name ?? "");
      setManualCurrency(response.data.currency ?? "USD");
      setManualBillingMode(response.data.billing_mode ?? "prepaid_credits");
    }
  });

  const linkMutation = useMutation({
    mutationFn: () =>
      linkOrganizationFromProduct({
        product_deployment_id: selectedProductId,
        product_organization_id: productOrganizationId,
        reason: manualReason || null,
        manual_name: manualName || null,
        manual_currency: manualCurrency || null,
        manual_billing_mode: manualBillingMode as "prepaid_credits" | "postpaid_manual_settlement" | "free_internal_testing"
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["organizations"] });
      await queryClient.invalidateQueries({ queryKey: ["product-discoveries", selectedProductId] });
    }
  });
  const importMutation = useMutation({
    mutationFn: (productOrgId: string) => importProductOrganizations(selectedProductId, [productOrgId]),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["organizations"] });
      await queryClient.invalidateQueries({ queryKey: ["product-discoveries", selectedProductId] });
    }
  });
  const importAllMutation = useMutation({
    mutationFn: () => importAllProductOrganizations(selectedProductId, productsQuery.data?.data.find((product) => product.id === selectedProductId)?.product_name ?? ""),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["organizations"] });
      await queryClient.invalidateQueries({ queryKey: ["product-discoveries", selectedProductId] });
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
          <h2 className="text-base font-semibold">Add / Link Organization</h2>
          <p className="mt-1 text-sm text-muted-foreground">Central organization IDs and technical sync statuses are generated and managed by the backend.</p>
          <div className="mt-4 grid gap-4 md:grid-cols-3">
            <select className="h-10 rounded-md border border-border bg-white px-3 text-sm" value={selectedProductId} onChange={(event) => setSelectedProductId(event.target.value)}>
              <option value="">Product deployment</option>
              {productsQuery.data?.data.map((product) => (
                <option key={product.id} value={product.id}>
                  {product.product_name} / {product.region} / {product.environment}
                </option>
              ))}
            </select>
            <Input placeholder="Product Organization ID" value={productOrganizationId} onChange={(event) => setProductOrganizationId(event.target.value)} />
            <Button type="button" variant="secondary" disabled={!selectedProductId || !productOrganizationId || lookupMutation.isPending} onClick={() => lookupMutation.mutate()}>
              {lookupMutation.isPending ? "Fetching..." : "Fetch Organization from Product"}
            </Button>
            <Input placeholder="Organization name" value={manualName} onChange={(event) => setManualName(event.target.value)} />
            <Input placeholder="Currency" maxLength={3} value={manualCurrency} onChange={(event) => setManualCurrency(event.target.value.toUpperCase())} />
            <select className="h-10 rounded-md border border-border bg-white px-3 text-sm" value={manualBillingMode} onChange={(event) => setManualBillingMode(event.target.value)}>
              <option value="prepaid_credits">prepaid_credits</option>
              <option value="postpaid_manual_settlement">postpaid_manual_settlement</option>
              <option value="free_internal_testing">free_internal_testing</option>
            </select>
            <Input placeholder="Reason for manual override/fallback" value={manualReason} onChange={(event) => setManualReason(event.target.value)} />
            <div className="md:col-span-3">
              {lookupMutation.data ? (
                <p className="mb-3 text-sm text-muted-foreground">
                  Fetched {lookupMutation.data.data.organization_name ?? "unnamed organization"} / {lookupMutation.data.data.currency ?? "missing currency"} / {lookupMutation.data.data.billing_mode ?? "missing billing mode"}.
                </p>
              ) : null}
              {lookupMutation.isError ? <p className="mb-3 text-sm text-red-700">{lookupMutation.error.message}. Enter business fields and a reason to use manual fallback.</p> : null}
              <Button type="button" disabled={!selectedProductId || !productOrganizationId || linkMutation.isPending} onClick={() => linkMutation.mutate()}>
                {linkMutation.isPending ? "Linking..." : "Confirm Import / Link"}
              </Button>
              {linkMutation.isError ? <p className="mt-2 text-sm text-red-700">{linkMutation.error.message}</p> : null}
              {linkMutation.data ? <p className="mt-2 text-sm text-muted-foreground">Linked. Verification {linkMutation.data.meta?.verification_success ? "succeeded" : "is pending or failed"}.</p> : null}
            </div>
          </div>
        </section>

        <section className="rounded-md border border-border bg-white">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-4">
            <div>
              <h2 className="text-base font-semibold">Discovered Organizations</h2>
              <p className="text-sm text-muted-foreground">Product-side identities are shown with deployment context; names are not used as identifiers.</p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button type="button" variant="secondary" disabled={!selectedProductId || discoveriesQuery.isFetching} onClick={() => discoveriesQuery.refetch()}>
                Refresh Status
              </Button>
              <Button type="button" variant="secondary" disabled={!selectedProductId || importAllMutation.isPending} onClick={() => importAllMutation.mutate()}>
                Import All Eligible
              </Button>
            </div>
          </div>
          {discoveriesQuery.data?.data.items.length ? (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="bg-muted text-xs uppercase text-muted-foreground">
                  <tr><th className="px-4 py-3">Organization</th><th className="px-4 py-3">Product Organization ID</th><th className="px-4 py-3">Initial Billing</th><th className="px-4 py-3">State</th><th className="px-4 py-3">Last Seen</th><th className="px-4 py-3" /></tr>
                </thead>
                <tbody>
                  {discoveriesQuery.data.data.items.map((item) => (
                    <tr key={item.id} className="border-t border-border">
                      <td className="px-4 py-3">{item.organization_name}</td>
                      <td className="px-4 py-3">{item.product_organization_id}</td>
                      <td className="px-4 py-3">{item.billing_mode_snapshot ?? "-"} / {item.currency_snapshot ?? "-"}</td>
                      <td className="px-4 py-3"><StatusBadge tone={statusTone(item.discovery_status)}>{item.discovery_status}</StatusBadge></td>
                      <td className="px-4 py-3">{item.last_seen_at ? new Date(item.last_seen_at).toLocaleString() : "-"}</td>
                      <td className="px-4 py-3">
                        {item.central_organization_id ? (
                          <Link className="text-primary hover:underline" href={`/organizations/${item.central_organization_id}`}>Open Managed Organization</Link>
                        ) : (
                          <Button type="button" variant="secondary" disabled={importMutation.isPending || !["discovered", "no_longer_returned"].includes(item.discovery_status)} onClick={() => importMutation.mutate(item.product_organization_id)}>
                            Import
                          </Button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <p className="p-5 text-sm text-muted-foreground">{selectedProductId ? "No discovered organizations for this deployment." : "Select a product deployment to view discovered organizations."}</p>}
          {importMutation.isError ? <p className="px-5 pb-4 text-sm text-red-700">{importMutation.error.message}</p> : null}
          {importAllMutation.isError ? <p className="px-5 pb-4 text-sm text-red-700">{importAllMutation.error.message}</p> : null}
        </section>

        <section className="rounded-md border border-border bg-white">
          <div className="flex items-center justify-between border-b border-border px-5 py-4">
            <h2 className="text-base font-semibold">Managed Organizations</h2>
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
                    <th className="px-4 py-3">Product Organization ID</th>
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
                      <td className="px-4 py-3">{organization.mapping?.product_organization_id ?? "-"}</td>
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
