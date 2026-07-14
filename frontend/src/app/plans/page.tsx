"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";

import { AppShell } from "@/components/layout/AppShell";
import { StatusBadge } from "@/components/status/StatusBadge";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { createPlan, listPlans, type PlanFilters } from "@/lib/plans";
import { listProducts } from "@/lib/products";
import type { BillingPlanPayload } from "@/lib/types";

const limit = 25;

const defaultValues: BillingPlanPayload = {
  plan_code: "",
  name: "",
  description: "",
  product_deployment_id: "",
  currency: "USD",
  is_active: true
};

export default function PlansPage() {
  const queryClient = useQueryClient();
  const [page, setPage] = useState(0);
  const [filters, setFilters] = useState<PlanFilters>({});
  const queryFilters = useMemo(() => ({ ...filters, limit, offset: page * limit }), [filters, page]);
  const plansQuery = useQuery({ queryKey: ["plans", queryFilters], queryFn: () => listPlans(queryFilters) });
  const productsQuery = useQuery({ queryKey: ["products"], queryFn: listProducts });
  const form = useForm<BillingPlanPayload>({ defaultValues });
  const total = plansQuery.data?.data.total ?? 0;

  const createMutation = useMutation({
    mutationFn: createPlan,
    onSuccess: async () => {
      form.reset(defaultValues);
      await queryClient.invalidateQueries({ queryKey: ["plans"] });
    }
  });

  return (
    <AppShell>
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-semibold">Billing Plans</h1>
          <p className="mt-1 text-sm text-muted-foreground">Stable commercial plan identities and immutable plan versions.</p>
        </div>

        <section className="rounded-md border border-border bg-white p-5">
          <h2 className="text-base font-semibold">Create Plan</h2>
          <form className="mt-4 grid gap-4 md:grid-cols-3" onSubmit={form.handleSubmit((values) => createMutation.mutate(values))}>
            <Input placeholder="Plan code" {...form.register("plan_code", { required: true })} />
            <Input placeholder="Plan name" {...form.register("name", { required: true })} />
            <select className="h-10 rounded-md border border-border bg-white px-3 text-sm" {...form.register("product_deployment_id", { required: true })}>
              <option value="">Product deployment</option>
              {productsQuery.data?.data.map((product) => (
                <option key={product.id} value={product.id}>
                  {product.product_name} / {product.region} / {product.environment}
                </option>
              ))}
            </select>
            <Input placeholder="Currency" maxLength={3} {...form.register("currency", { required: true })} />
            <Input className="md:col-span-2" placeholder="Description" {...form.register("description")} />
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" {...form.register("is_active")} />
              Active
            </label>
            <div className="md:col-span-3">
              <Button type="submit" disabled={createMutation.isPending || productsQuery.isLoading}>
                {createMutation.isPending ? "Creating..." : "Create Plan"}
              </Button>
              {createMutation.isError ? <p className="mt-2 text-sm text-red-700">{createMutation.error.message}</p> : null}
            </div>
          </form>
        </section>

        <section className="rounded-md border border-border bg-white p-5">
          <h2 className="text-base font-semibold">Filters</h2>
          <div className="mt-4 grid gap-3 md:grid-cols-4">
            <Input placeholder="Search name or code" onChange={(event) => setFilters((value) => ({ ...value, search: event.target.value }))} />
            <select className="h-10 rounded-md border border-border bg-white px-3 text-sm" onChange={(event) => setFilters((value) => ({ ...value, product_deployment_id: event.target.value }))}>
              <option value="">All deployments</option>
              {productsQuery.data?.data.map((product) => (
                <option key={product.id} value={product.id}>
                  {product.product_name} / {product.region}
                </option>
              ))}
            </select>
            <Input placeholder="Currency" maxLength={3} onChange={(event) => setFilters((value) => ({ ...value, currency: event.target.value }))} />
            <select className="h-10 rounded-md border border-border bg-white px-3 text-sm" onChange={(event) => setFilters((value) => ({ ...value, is_active: event.target.value }))}>
              <option value="">Any status</option>
              <option value="true">active</option>
              <option value="false">inactive</option>
            </select>
          </div>
        </section>

        <section className="rounded-md border border-border bg-white">
          <div className="flex items-center justify-between border-b border-border px-5 py-4">
            <h2 className="text-base font-semibold">Plans</h2>
            <p className="text-sm text-muted-foreground">{total} total</p>
          </div>
          {plansQuery.isLoading ? <p className="p-5 text-sm text-muted-foreground">Loading plans...</p> : null}
          {plansQuery.isError ? <p className="p-5 text-sm text-red-700">{plansQuery.error.message}</p> : null}
          {plansQuery.data?.data.items.length === 0 ? <p className="p-5 text-sm text-muted-foreground">No plans found.</p> : null}
          {plansQuery.data?.data.items.length ? (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="bg-muted text-xs uppercase text-muted-foreground">
                  <tr>
                    <th className="px-4 py-3">Plan</th>
                    <th className="px-4 py-3">Code</th>
                    <th className="px-4 py-3">Product</th>
                    <th className="px-4 py-3">Current Version</th>
                    <th className="px-4 py-3">Latest</th>
                    <th className="px-4 py-3">Price</th>
                    <th className="px-4 py-3">Mode</th>
                    <th className="px-4 py-3">Status</th>
                    <th className="px-4 py-3" />
                  </tr>
                </thead>
                <tbody>
                  {plansQuery.data.data.items.map((plan) => (
                    <tr key={plan.id} className="border-t border-border">
                      <td className="px-4 py-3 font-medium">{plan.name}</td>
                      <td className="px-4 py-3">{plan.plan_code}</td>
                      <td className="px-4 py-3">{plan.product_name ?? "-"} / {plan.region ?? "-"}</td>
                      <td className="px-4 py-3">{plan.current_effective_version ? `v${plan.current_effective_version.version_number}` : "-"}</td>
                      <td className="px-4 py-3">{plan.latest_version ? `v${plan.latest_version.version_number}` : "-"}</td>
                      <td className="px-4 py-3">{plan.current_effective_version ? `${plan.current_effective_version.price} ${plan.current_effective_version.currency}` : "-"}</td>
                      <td className="px-4 py-3">{plan.current_effective_version?.billing_mode_compatibility ?? "-"}</td>
                      <td className="px-4 py-3"><StatusBadge tone={plan.is_active ? "success" : "neutral"}>{plan.is_active ? "active" : "inactive"}</StatusBadge></td>
                      <td className="px-4 py-3">
                        <Link className="text-primary hover:underline" href={`/plans/${plan.id}`}>
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
            <Button type="button" variant="secondary" disabled={page === 0} onClick={() => setPage((value) => Math.max(0, value - 1))}>
              Previous
            </Button>
            <span className="text-sm text-muted-foreground">Page {page + 1}</span>
            <Button type="button" variant="secondary" disabled={(page + 1) * limit >= total} onClick={() => setPage((value) => value + 1)}>
              Next
            </Button>
          </div>
        </section>
      </div>
    </AppShell>
  );
}
