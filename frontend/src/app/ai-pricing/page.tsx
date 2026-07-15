"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { useForm } from "react-hook-form";

import { AppShell } from "@/components/layout/AppShell";
import { StatusBadge } from "@/components/status/StatusBadge";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { createAiPricingCatalog, listAiPricing, updateAiPricingCatalog } from "@/lib/aiPricing";
import type { AiPricingCatalogPayload } from "@/lib/types";

type FilterForm = {
  search: string;
  provider: string;
  pricing_scope_code: string;
  currency: string;
  is_active: string;
};

type CatalogForm = AiPricingCatalogPayload & { idempotency_key: string };

const defaultCatalog: CatalogForm = {
  provider: "",
  provider_model_id: "",
  display_name: "",
  pricing_scope_code: "standard",
  currency: "USD",
  description: "",
  is_active: true,
  reason: "",
  idempotency_key: ""
};

export default function AiPricingPage() {
  const queryClient = useQueryClient();
  const [filters, setFilters] = useState<FilterForm>({ search: "", provider: "", pricing_scope_code: "", currency: "", is_active: "" });
  const filterForm = useForm<FilterForm>({ defaultValues: filters });
  const catalogForm = useForm<CatalogForm>({ defaultValues: defaultCatalog });
  const pricingQuery = useQuery({ queryKey: ["ai-pricing", filters], queryFn: () => listAiPricing({ ...filters, limit: 25, offset: 0 }) });
  const createMutation = useMutation({
    mutationFn: (values: CatalogForm) => createAiPricingCatalog(values, values.idempotency_key),
    onSuccess: async () => {
      catalogForm.reset(defaultCatalog);
      await queryClient.invalidateQueries({ queryKey: ["ai-pricing"] });
    }
  });
  const toggleMutation = useMutation({
    mutationFn: (values: { id: string; display_name: string; description: string | null; is_active: boolean }) =>
      updateAiPricingCatalog(values.id, {
        display_name: values.display_name,
        description: values.description ?? "",
        is_active: !values.is_active,
        reason: values.is_active ? "Deactivate pricing catalog" : "Activate pricing catalog"
      }),
    onSuccess: async () => queryClient.invalidateQueries({ queryKey: ["ai-pricing"] })
  });

  return (
    <AppShell>
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-semibold">AI Model Pricing</h1>
          <p className="mt-1 text-sm text-muted-foreground">Historical pricing versions are immutable. Pricing corrections require a new version.</p>
        </div>

        <section className="rounded-md border border-border bg-white p-5">
          <h2 className="text-base font-semibold">Filters</h2>
          <form className="mt-4 grid gap-3 md:grid-cols-5" onSubmit={filterForm.handleSubmit((values) => setFilters(values))}>
            <Input placeholder="Search" {...filterForm.register("search")} />
            <Input placeholder="Provider" {...filterForm.register("provider")} />
            <Input placeholder="Pricing scope" {...filterForm.register("pricing_scope_code")} />
            <Input placeholder="Currency" maxLength={3} {...filterForm.register("currency")} />
            <select className="h-10 rounded-md border border-border bg-white px-3 text-sm" {...filterForm.register("is_active")}>
              <option value="">Any status</option>
              <option value="true">Active</option>
              <option value="false">Inactive</option>
            </select>
            <div className="md:col-span-5">
              <Button type="submit">Apply Filters</Button>
            </div>
          </form>
        </section>

        <section className="rounded-md border border-border bg-white p-5">
          <h2 className="text-base font-semibold">Create Pricing Catalog</h2>
          <form className="mt-4 grid gap-3 md:grid-cols-4" onSubmit={catalogForm.handleSubmit((values) => createMutation.mutate(values))}>
            <Input placeholder="Provider" {...catalogForm.register("provider", { required: true })} />
            <Input placeholder="Provider model ID" {...catalogForm.register("provider_model_id", { required: true })} />
            <Input placeholder="Display name" {...catalogForm.register("display_name", { required: true })} />
            <Input placeholder="Pricing scope" {...catalogForm.register("pricing_scope_code", { required: true })} />
            <Input placeholder="Currency" maxLength={3} {...catalogForm.register("currency", { required: true })} />
            <Input className="md:col-span-2" placeholder="Description" {...catalogForm.register("description")} />
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" {...catalogForm.register("is_active")} />
              Active
            </label>
            <Input className="md:col-span-2" placeholder="Reason / note" {...catalogForm.register("reason", { required: true })} />
            <Input className="md:col-span-2" placeholder="Idempotency key" {...catalogForm.register("idempotency_key", { required: true })} />
            <div className="md:col-span-4">
              <Button type="submit" disabled={createMutation.isPending}>{createMutation.isPending ? "Creating..." : "Create Catalog"}</Button>
              {createMutation.isError ? <p className="mt-2 text-sm text-red-700">{createMutation.error.message}</p> : null}
            </div>
          </form>
        </section>

        <section className="rounded-md border border-border bg-white">
          <div className="border-b border-border px-5 py-4">
            <h2 className="text-base font-semibold">Pricing Catalogs</h2>
          </div>
          {pricingQuery.isLoading ? <p className="p-5 text-sm text-muted-foreground">Loading pricing catalogs...</p> : null}
          {pricingQuery.isError ? <p className="p-5 text-sm text-red-700">{pricingQuery.error.message}</p> : null}
          {pricingQuery.data?.data.items.length === 0 ? <p className="p-5 text-sm text-muted-foreground">No pricing catalogs found.</p> : null}
          {pricingQuery.data?.data.items.length ? (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="bg-muted text-xs uppercase text-muted-foreground">
                  <tr>
                    <th className="px-4 py-3">Catalog</th>
                    <th className="px-4 py-3">Identity</th>
                    <th className="px-4 py-3">Current Price</th>
                    <th className="px-4 py-3">Versions</th>
                    <th className="px-4 py-3">Status</th>
                    <th className="px-4 py-3">Source</th>
                    <th className="px-4 py-3">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {pricingQuery.data.data.items.map((item) => (
                    <tr key={item.id} className="border-t border-border align-top">
                      <td className="px-4 py-3">
                        <Link className="font-medium text-primary hover:underline" href={`/ai-pricing/${item.id}`}>{item.display_name}</Link>
                        <div className="text-xs text-muted-foreground">{item.description ?? "-"}</div>
                      </td>
                      <td className="px-4 py-3">{item.provider} / {item.provider_model_id} / {item.pricing_scope_code} / {item.currency}</td>
                      <td className="px-4 py-3">
                        {item.current_effective_version
                          ? `${item.current_effective_version.input_token_price} in / ${item.current_effective_version.output_token_price} out per ${item.current_effective_version.pricing_unit_tokens}`
                          : "-"}
                      </td>
                      <td className="px-4 py-3">current v{item.current_effective_version?.version_number ?? "-"} / latest v{item.latest_version?.version_number ?? "-"} / {item.version_count}</td>
                      <td className="px-4 py-3"><StatusBadge tone={item.is_active ? "success" : "neutral"}>{item.is_active ? "active" : "inactive"}</StatusBadge></td>
                      <td className="px-4 py-3">
                        <div className="text-xs text-muted-foreground">{item.source_state}</div>
                        <div className="text-xs text-muted-foreground">{item.last_check_status ?? "not checked"} / reviews {item.unresolved_review_count}</div>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex gap-2">
                          <Link className="text-primary hover:underline" href={`/ai-pricing/${item.id}`}>History</Link>
                          <button className="text-primary hover:underline" type="button" onClick={() => toggleMutation.mutate(item)}>
                            {item.is_active ? "Deactivate" : "Activate"}
                          </button>
                        </div>
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
