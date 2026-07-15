"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";

import { AppShell } from "@/components/layout/AppShell";
import { StatusBadge } from "@/components/status/StatusBadge";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import {
  deleteProduct,
  discoverProductOrganizations,
  getProductPurgePreview,
  importAllProductOrganizations,
  importProductOrganizations,
  listDiscoveredOrganizations,
  getProduct,
  purgeTestProduct,
  runProductHealthCheck,
  updateProduct
} from "@/lib/products";
import type { ProductPayload } from "@/lib/types";

function statusTone(status: string) {
  if (status === "healthy" || status === "synced") return "success";
  if (status === "slow" || status === "pending" || status === "retrying" || status === "under_maintenance") return "warning";
  if (status === "down" || status === "failed" || status === "not_responding") return "danger";
  return "neutral";
}

export default function ProductDetailPage() {
  const params = useParams<{ productId: string }>();
  const productId = params.productId;
  const queryClient = useQueryClient();
  const router = useRouter();
  const productQuery = useQuery({ queryKey: ["products", productId], queryFn: () => getProduct(productId) });
  const form = useForm<ProductPayload>();
  const product = productQuery.data?.data;
  const [purgeReason, setPurgeReason] = useState("");
  const [purgeConfirmation, setPurgeConfirmation] = useState("");

  useEffect(() => {
    const product = productQuery.data?.data;
    if (!product) return;
    form.reset({
      product_name: product.product_name,
      region: product.region,
      environment: product.environment,
      currency: product.currency,
      api_base_url: product.api_base_url,
      health_check_url: product.health_check_url ?? "",
      admin_api_version: product.admin_api_version,
      organization_list_path: product.organization_list_path ?? "",
      organization_detail_path_template: product.organization_detail_path_template ?? "",
      token_usage_list_path: product.token_usage_list_path ?? "",
      is_active: product.is_active,
      is_under_maintenance: product.is_under_maintenance,
      admin_api_secret: ""
    });
  }, [form, productQuery.data]);

  const updateMutation = useMutation({
    mutationFn: (values: ProductPayload) => updateProduct(productId, values),
    onSuccess: async () => {
      form.setValue("admin_api_secret", "");
      await queryClient.invalidateQueries({ queryKey: ["products"] });
      await queryClient.invalidateQueries({ queryKey: ["products", productId] });
    }
  });

  const healthMutation = useMutation({
    mutationFn: () => runProductHealthCheck(productId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["products"] });
      await queryClient.invalidateQueries({ queryKey: ["products", productId] });
    }
  });

  const discoveriesQuery = useQuery({
    queryKey: ["product-discoveries", productId],
    queryFn: () => listDiscoveredOrganizations(productId),
    enabled: Boolean(productId)
  });
  const purgePreviewQuery = useQuery({
    queryKey: ["products", productId, "purge-preview"],
    queryFn: () => getProductPurgePreview(productId),
    enabled: Boolean(productId)
  });

  const discoverMutation = useMutation({
    mutationFn: () => discoverProductOrganizations(productId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["products", productId] });
      await queryClient.invalidateQueries({ queryKey: ["product-discoveries", productId] });
    }
  });

  const importMutation = useMutation({
    mutationFn: (productOrganizationId: string) => importProductOrganizations(productId, [productOrganizationId]),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["organizations"] });
      await queryClient.invalidateQueries({ queryKey: ["product-discoveries", productId] });
      await queryClient.invalidateQueries({ queryKey: ["products", productId, "purge-preview"] });
    }
  });

  const importAllMutation = useMutation({
    mutationFn: () => importAllProductOrganizations(productId, product?.product_name ?? ""),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["organizations"] });
      await queryClient.invalidateQueries({ queryKey: ["product-discoveries", productId] });
      await queryClient.invalidateQueries({ queryKey: ["products", productId, "purge-preview"] });
    }
  });

  const deleteMutation = useMutation({
    mutationFn: () => deleteProduct(productId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["products"] });
      router.push("/products");
    }
  });

  const purgeMutation = useMutation({
    mutationFn: () =>
      purgeTestProduct(
        productId,
        { reason: purgeReason, confirmation: purgeConfirmation },
        `product-purge-${productId}-${crypto.randomUUID()}`
      ),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["products"] });
      router.push("/products");
    }
  });

  return (
    <AppShell>
      <div className="space-y-6">
        <Link className="text-sm text-primary hover:underline" href="/products">
          Back to products
        </Link>

        {productQuery.isLoading ? <p className="text-sm text-muted-foreground">Loading product...</p> : null}
        {productQuery.isError ? <p className="text-sm text-red-700">{productQuery.error.message}</p> : null}

        {product ? (
          <>
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <h1 className="text-2xl font-semibold">{product.product_name}</h1>
                <p className="mt-1 text-sm text-muted-foreground">
                  {product.region} / {product.environment} / {product.currency}
                </p>
              </div>
              <Button type="button" onClick={() => healthMutation.mutate()} disabled={healthMutation.isPending}>
                {healthMutation.isPending ? "Checking..." : "Run Health Check"}
              </Button>
            </div>

            {product.environment === "production" ? (
              <div className="rounded-md border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
                Production deployment. Confirm URLs, maintenance state, and secret changes carefully.
              </div>
            ) : null}

            <section className="grid gap-4 md:grid-cols-3">
              <div className="rounded-md border border-border bg-white p-4">
                <p className="text-xs uppercase text-muted-foreground">Health</p>
                <div className="mt-2">
                  <StatusBadge tone={statusTone(product.health_status)}>{product.health_status}</StatusBadge>
                </div>
              </div>
              <div className="rounded-md border border-border bg-white p-4">
                <p className="text-xs uppercase text-muted-foreground">Sync</p>
                <div className="mt-2">
                  <StatusBadge tone={statusTone(product.sync_status)}>{product.sync_status}</StatusBadge>
                </div>
              </div>
              <div className="rounded-md border border-border bg-white p-4">
                <p className="text-xs uppercase text-muted-foreground">Secret</p>
                <p className="mt-2 text-sm">{product.secret_configured ? "configured" : "missing"}</p>
              </div>
            </section>

            <section className="rounded-md border border-border bg-white p-5">
              <h2 className="text-base font-semibold">Metadata</h2>
              <dl className="mt-4 grid gap-4 text-sm md:grid-cols-2">
                <div>
                  <dt className="text-muted-foreground">API base URL</dt>
                  <dd className="break-all">{product.api_base_url}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Health-check URL</dt>
                  <dd className="break-all">{product.health_check_url ?? "-"}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Admin API version</dt>
                  <dd>{product.admin_api_version}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Organization List API Path</dt>
                  <dd className="break-all">{product.organization_list_path ?? "not configured"}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Token Usage API Path</dt>
                  <dd className="break-all">{product.token_usage_list_path ?? "Not configured"}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">AI Usage Sync</dt>
                  <dd>{product.ai_usage_sync_configured ? "Configured" : "Not configured"}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Last usage sync attempt</dt>
                  <dd>{product.last_usage_sync_attempt_at ? new Date(product.last_usage_sync_attempt_at).toLocaleString() : "-"}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Last successful usage sync</dt>
                  <dd>{product.last_successful_usage_sync_at ? new Date(product.last_successful_usage_sync_at).toLocaleString() : "-"}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Last usage sync error</dt>
                  <dd>{product.last_usage_sync_error ?? "-"}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Last discovery</dt>
                  <dd>{product.last_successful_organization_discovery_at ? new Date(product.last_successful_organization_discovery_at).toLocaleString() : "-"}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Active</dt>
                  <dd>{product.is_active ? "active" : "inactive"}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Maintenance</dt>
                  <dd>{product.is_under_maintenance ? "under maintenance" : "normal"}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Last checked</dt>
                  <dd>{product.last_checked_at ? new Date(product.last_checked_at).toLocaleString() : "-"}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Response time</dt>
                  <dd>{product.last_health_response_time_ms === null ? "-" : `${product.last_health_response_time_ms} ms`}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Last safe error</dt>
                  <dd>{product.last_error_message ?? "-"}</dd>
                </div>
              </dl>
              {healthMutation.isSuccess ? (
                <p className="mt-4 text-sm text-muted-foreground">
                  Health check finished with status {healthMutation.data.data.health_status}.
                </p>
              ) : null}
              {healthMutation.isError ? <p className="mt-4 text-sm text-red-700">{healthMutation.error.message}</p> : null}
            </section>

            <section className="rounded-md border border-border bg-white p-5">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h2 className="text-base font-semibold">Product Organizations</h2>
                  <p className="mt-1 text-sm text-muted-foreground">Discovered organizations use Product Organization ID as the product-side identity.</p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button type="button" variant="secondary" disabled={discoverMutation.isPending || !product.organization_list_path} onClick={() => discoverMutation.mutate()}>
                    {discoverMutation.isPending ? "Discovering..." : "Discover Organizations"}
                  </Button>
                  <Button type="button" variant="secondary" disabled={importAllMutation.isPending || !discoveriesQuery.data?.data.items.length} onClick={() => importAllMutation.mutate()}>
                    Import All Eligible
                  </Button>
                </div>
              </div>
              {product.last_organization_discovery_error ? <p className="mt-3 text-sm text-red-700">{product.last_organization_discovery_error}</p> : null}
              {discoverMutation.data ? (
                <p className="mt-3 text-sm text-muted-foreground">
                  Discovered {discoverMutation.data.data.discovered_count}, new {discoverMutation.data.data.newly_discovered_count}, conflicts {discoverMutation.data.data.conflict_count}.
                </p>
              ) : null}
              {discoverMutation.isError ? <p className="mt-3 text-sm text-red-700">{discoverMutation.error.message}</p> : null}
              {importAllMutation.isError ? <p className="mt-3 text-sm text-red-700">{importAllMutation.error.message}</p> : null}
              <div className="mt-4 overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead className="bg-muted text-xs uppercase text-muted-foreground">
                    <tr>
                      <th className="px-3 py-2">Organization</th>
                      <th className="px-3 py-2">Product Organization ID</th>
                      <th className="px-3 py-2">Lifecycle</th>
                      <th className="px-3 py-2">Billing</th>
                      <th className="px-3 py-2">Status</th>
                      <th className="px-3 py-2">Last Seen</th>
                      <th className="px-3 py-2" />
                    </tr>
                  </thead>
                  <tbody>
                    {discoveriesQuery.data?.data.items.map((item) => (
                      <tr key={item.id} className="border-t border-border">
                        <td className="px-3 py-2">{item.organization_name}</td>
                        <td className="px-3 py-2">{item.product_organization_id}</td>
                        <td className="px-3 py-2">{item.lifecycle_status_snapshot ?? "-"}</td>
                        <td className="px-3 py-2">{item.billing_mode_snapshot ?? "-"}</td>
                        <td className="px-3 py-2"><StatusBadge tone={statusTone(item.discovery_status)}>{item.discovery_status}</StatusBadge></td>
                        <td className="px-3 py-2">{item.last_seen_at ? new Date(item.last_seen_at).toLocaleString() : "-"}</td>
                        <td className="px-3 py-2">
                          <Button type="button" variant="secondary" disabled={!["discovered", "no_longer_returned"].includes(item.discovery_status) || importMutation.isPending} onClick={() => importMutation.mutate(item.product_organization_id)}>
                            Import
                          </Button>
                        </td>
                      </tr>
                    ))}
                    {!discoveriesQuery.data?.data.items.length ? (
                      <tr><td className="px-3 py-4 text-muted-foreground" colSpan={7}>No discovered organizations yet.</td></tr>
                    ) : null}
                  </tbody>
                </table>
              </div>
            </section>

            <section className="rounded-md border border-border bg-white p-5">
              <h2 className="text-base font-semibold">Edit Product Deployment</h2>
              <form className="mt-4 grid gap-4 md:grid-cols-3" onSubmit={form.handleSubmit((values) => updateMutation.mutate(values))}>
                <Input placeholder="Product name" {...form.register("product_name", { required: true })} />
                <Input placeholder="Region" {...form.register("region", { required: true })} />
                <select className="h-10 rounded-md border border-border bg-white px-3 text-sm" {...form.register("environment")}>
                  <option value="production">production</option>
                  <option value="staging">staging</option>
                  <option value="testing">testing</option>
                  <option value="development">development</option>
                </select>
                <Input placeholder="Currency" maxLength={3} {...form.register("currency", { required: true })} />
                <Input placeholder="API base URL" {...form.register("api_base_url", { required: true })} />
                <Input placeholder="Health-check URL" {...form.register("health_check_url")} />
                <Input placeholder="Admin API version" {...form.register("admin_api_version", { required: true })} />
                <Input placeholder="Organization List API Path" {...form.register("organization_list_path")} />
                <Input placeholder="Organization Detail Path Template" {...form.register("organization_detail_path_template")} />
                <label className="md:col-span-3">
                  <span className="text-sm font-medium">Token Usage API Path</span>
                  <Input className="mt-1" placeholder="/api/v1/admin/ai-usage" {...form.register("token_usage_list_path")} />
                  <span className="mt-1 block text-xs text-muted-foreground">
                    Relative product API path used by the Admin Dashboard to import finalized AI token-usage records. Leave empty when the product does not support AI usage synchronization.
                  </span>
                </label>
                <Input type="password" placeholder="New product admin secret" {...form.register("admin_api_secret")} />
                <div className="flex items-center gap-4 text-sm">
                  <label className="flex items-center gap-2">
                    <input type="checkbox" {...form.register("is_active")} />
                    Active
                  </label>
                  <label className="flex items-center gap-2">
                    <input type="checkbox" {...form.register("is_under_maintenance")} />
                    Maintenance
                  </label>
                </div>
                <div className="md:col-span-3">
                  <Button type="submit" disabled={updateMutation.isPending}>
                    {updateMutation.isPending ? "Saving..." : "Save"}
                  </Button>
                  {updateMutation.isSuccess ? <p className="mt-2 text-sm text-emerald-700">Saved.</p> : null}
                  {updateMutation.isError ? <p className="mt-2 text-sm text-red-700">{updateMutation.error.message}</p> : null}
                </div>
              </form>
            </section>

            <section className="rounded-md border border-red-200 bg-white p-5">
              <h2 className="text-base font-semibold text-red-900">Product Operations</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Normal delete is blocked when Admin Dashboard records depend on this deployment. Test purge removes only local Admin Dashboard data and never deletes remote product data.
              </p>
              {purgePreviewQuery.data ? (
                <dl className="mt-4 grid gap-3 text-sm md:grid-cols-4">
                  {Object.entries(purgePreviewQuery.data.data.dependency_summary).map(([key, value]) => (
                    <div key={key}>
                      <dt className="text-muted-foreground">{key}</dt>
                      <dd>{value}</dd>
                    </div>
                  ))}
                  <div>
                    <dt className="text-muted-foreground">Purge enabled</dt>
                    <dd>{purgePreviewQuery.data.data.enabled ? "yes" : "no"}</dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground">Remote deletion</dt>
                    <dd>{purgePreviewQuery.data.data.remote_product_deleted ? "yes" : "no"}</dd>
                  </div>
                </dl>
              ) : null}
              <div className="mt-4 flex flex-wrap gap-2">
                <Button type="button" variant="secondary" disabled={deleteMutation.isPending} onClick={() => deleteMutation.mutate()}>
                  {deleteMutation.isPending ? "Deleting..." : "Delete if Unused"}
                </Button>
              </div>
              {deleteMutation.isError ? <p className="mt-3 text-sm text-red-700">{deleteMutation.error.message}</p> : null}

              <div className="mt-5 grid gap-3 md:grid-cols-3">
                <Input placeholder="Reason" value={purgeReason} onChange={(event) => setPurgeReason(event.target.value)} />
                <Input placeholder="Type product name or ID" value={purgeConfirmation} onChange={(event) => setPurgeConfirmation(event.target.value)} />
                <Button
                  type="button"
                  variant="secondary"
                  disabled={purgeMutation.isPending || !purgeReason.trim() || !purgeConfirmation.trim()}
                  onClick={() => purgeMutation.mutate()}
                >
                  {purgeMutation.isPending ? "Purging..." : "Purge Test Deployment"}
                </Button>
              </div>
              {purgeMutation.isError ? <p className="mt-3 text-sm text-red-700">{purgeMutation.error.message}</p> : null}
            </section>
          </>
        ) : null}
      </div>
    </AppShell>
  );
}
