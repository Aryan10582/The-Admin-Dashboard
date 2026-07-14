"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect } from "react";
import { useForm } from "react-hook-form";

import { AppShell } from "@/components/layout/AppShell";
import { StatusBadge } from "@/components/status/StatusBadge";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { getProduct, runProductHealthCheck, updateProduct } from "@/lib/products";
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
  const productQuery = useQuery({ queryKey: ["products", productId], queryFn: () => getProduct(productId) });
  const form = useForm<ProductPayload>();

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

  const product = productQuery.data?.data;

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
          </>
        ) : null}
      </div>
    </AppShell>
  );
}
