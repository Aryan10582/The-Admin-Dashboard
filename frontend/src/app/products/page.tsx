"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useForm } from "react-hook-form";

import { AppShell } from "@/components/layout/AppShell";
import { StatusBadge } from "@/components/status/StatusBadge";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { createProduct, listProducts } from "@/lib/products";
import type { ProductPayload } from "@/lib/types";

const defaultValues: ProductPayload = {
  product_name: "",
  region: "",
  environment: "staging",
  currency: "USD",
  api_base_url: "",
  health_check_url: "",
  admin_api_version: "v1",
  is_active: true,
  is_under_maintenance: false,
  admin_api_secret: ""
};

function statusTone(status: string) {
  if (status === "healthy" || status === "synced") return "success";
  if (status === "slow" || status === "pending" || status === "retrying" || status === "under_maintenance") return "warning";
  if (status === "down" || status === "failed" || status === "not_responding") return "danger";
  return "neutral";
}

export default function ProductsPage() {
  const queryClient = useQueryClient();
  const productsQuery = useQuery({ queryKey: ["products"], queryFn: listProducts });
  const form = useForm<ProductPayload>({ defaultValues });

  const createMutation = useMutation({
    mutationFn: createProduct,
    onSuccess: async () => {
      form.reset(defaultValues);
      await queryClient.invalidateQueries({ queryKey: ["products"] });
    }
  });

  return (
    <AppShell>
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-semibold">Products</h1>
          <p className="mt-1 text-sm text-muted-foreground">Manage product deployments through the Admin Backend.</p>
        </div>

        <section className="rounded-md border border-border bg-white p-5">
          <h2 className="text-base font-semibold">Create Product Deployment</h2>
          <form className="mt-4 grid gap-4 md:grid-cols-3" onSubmit={form.handleSubmit((values) => createMutation.mutate(values))}>
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
            <Input type="password" placeholder="Product admin secret" {...form.register("admin_api_secret")} />
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
              <Button type="submit" disabled={createMutation.isPending}>
                {createMutation.isPending ? "Creating..." : "Create"}
              </Button>
              {createMutation.isError ? <p className="mt-2 text-sm text-red-700">{createMutation.error.message}</p> : null}
            </div>
          </form>
        </section>

        <section className="rounded-md border border-border bg-white">
          <div className="border-b border-border px-5 py-4">
            <h2 className="text-base font-semibold">Product Deployments</h2>
          </div>
          {productsQuery.isLoading ? <p className="p-5 text-sm text-muted-foreground">Loading products...</p> : null}
          {productsQuery.isError ? <p className="p-5 text-sm text-red-700">{productsQuery.error.message}</p> : null}
          {productsQuery.data?.data.length === 0 ? <p className="p-5 text-sm text-muted-foreground">No product deployments yet.</p> : null}
          {productsQuery.data?.data.length ? (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="bg-muted text-xs uppercase text-muted-foreground">
                  <tr>
                    <th className="px-4 py-3">Product</th>
                    <th className="px-4 py-3">Region</th>
                    <th className="px-4 py-3">Environment</th>
                    <th className="px-4 py-3">Currency</th>
                    <th className="px-4 py-3">Health</th>
                    <th className="px-4 py-3">Sync</th>
                    <th className="px-4 py-3">API</th>
                    <th className="px-4 py-3">Last Checked</th>
                    <th className="px-4 py-3">Active</th>
                    <th className="px-4 py-3">Secret</th>
                    <th className="px-4 py-3" />
                  </tr>
                </thead>
                <tbody>
                  {productsQuery.data.data.map((product) => (
                    <tr key={product.id} className="border-t border-border">
                      <td className="px-4 py-3 font-medium">{product.product_name}</td>
                      <td className="px-4 py-3">{product.region}</td>
                      <td className="px-4 py-3">{product.environment}</td>
                      <td className="px-4 py-3">{product.currency}</td>
                      <td className="px-4 py-3">
                        <StatusBadge tone={statusTone(product.health_status)}>{product.health_status}</StatusBadge>
                      </td>
                      <td className="px-4 py-3">
                        <StatusBadge tone={statusTone(product.sync_status)}>{product.sync_status}</StatusBadge>
                      </td>
                      <td className="px-4 py-3">{product.admin_api_version}</td>
                      <td className="px-4 py-3">{product.last_checked_at ? new Date(product.last_checked_at).toLocaleString() : "-"}</td>
                      <td className="px-4 py-3">{product.is_active ? "active" : "inactive"}</td>
                      <td className="px-4 py-3">{product.secret_configured ? "configured" : "missing"}</td>
                      <td className="px-4 py-3">
                        <Link className="text-primary hover:underline" href={`/products/${product.id}`}>
                          Details
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </section>
      </div>
    </AppShell>
  );
}
