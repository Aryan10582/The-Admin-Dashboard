"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";

import { AppShell } from "@/components/layout/AppShell";
import { StatusBadge } from "@/components/status/StatusBadge";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { createPlanVersion, getPlan, listPlanVersions, updatePlan } from "@/lib/plans";
import type { BillingMode } from "@/lib/types";

type VersionForm = {
  currency: string;
  billing_mode_compatibility: BillingMode;
  base_price: string;
  pricing_structure: string;
  limits: string;
  included_tokens: number;
  included_leads: number;
  overage_pricing: string;
  effective_from: string;
  effective_to: string;
  external_product_plan_id: string;
  reason: string;
};

type MetadataForm = {
  name: string;
  description: string;
  is_active: boolean;
};

const versionDefaults: VersionForm = {
  currency: "USD",
  billing_mode_compatibility: "prepaid_credits",
  base_price: "0.00",
  pricing_structure: "{}",
  limits: "{}",
  included_tokens: 0,
  included_leads: 0,
  overage_pricing: "{}",
  effective_from: "",
  effective_to: "",
  external_product_plan_id: "",
  reason: ""
};

function jsonPreview(value: Record<string, unknown> | null) {
  return value ? JSON.stringify(value) : "{}";
}

export default function PlanDetailPage() {
  const params = useParams<{ planId: string }>();
  const planId = params.planId;
  const queryClient = useQueryClient();
  const planQuery = useQuery({ queryKey: ["plans", planId], queryFn: () => getPlan(planId) });
  const versionsQuery = useQuery({ queryKey: ["plans", planId, "versions"], queryFn: () => listPlanVersions(planId) });
  const metadataForm = useForm<MetadataForm>();
  const versionForm = useForm<VersionForm>({ defaultValues: versionDefaults });
  const [versionSubmitError, setVersionSubmitError] = useState<string | null>(null);
  const plan = planQuery.data?.data;

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["plans"] });
    await queryClient.invalidateQueries({ queryKey: ["plans", planId] });
    await queryClient.invalidateQueries({ queryKey: ["plans", planId, "versions"] });
  };

  const updateMutation = useMutation({
    mutationFn: (values: MetadataForm) => updatePlan(planId, values),
    onSuccess: refresh
  });
  const versionMutation = useMutation({
    mutationFn: createPlanVersion.bind(null, planId),
    onSuccess: async () => {
      setVersionSubmitError(null);
      versionForm.reset({ ...versionDefaults, currency: plan?.currency ?? "USD" });
      await refresh();
    },
    onError: (error) => {
      setVersionSubmitError(error.message);
    }
  });

  useEffect(() => {
    if (!plan) return;
    metadataForm.reset({ name: plan.name, description: plan.description ?? "", is_active: plan.is_active });
    versionForm.reset({ ...versionDefaults, currency: plan.currency });
  }, [metadataForm, plan, versionForm]);

  return (
    <AppShell>
      <div className="space-y-6">
        <Link className="text-sm text-primary hover:underline" href="/plans">
          Back to plans
        </Link>
        {planQuery.isLoading ? <p className="text-sm text-muted-foreground">Loading plan...</p> : null}
        {planQuery.isError ? <p className="text-sm text-red-700">{planQuery.error.message}</p> : null}
        {plan ? (
          <>
            <div>
              <h1 className="text-2xl font-semibold">{plan.name}</h1>
              <p className="mt-1 text-sm text-muted-foreground">
                {plan.plan_code} / {plan.product_name ?? "deployment"} / {plan.currency}
              </p>
            </div>

            <section className="rounded-md border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
              Existing plan versions are immutable. Pricing or limit changes require creating a new version.
            </section>

            <section className="rounded-md border border-border bg-white p-5">
              <h2 className="text-base font-semibold">Stable Metadata</h2>
              <form className="mt-4 grid gap-4 md:grid-cols-3" onSubmit={metadataForm.handleSubmit((values) => updateMutation.mutate(values))}>
                <Input placeholder="Plan name" {...metadataForm.register("name", { required: true })} />
                <Input className="md:col-span-2" placeholder="Description" {...metadataForm.register("description")} />
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" {...metadataForm.register("is_active")} />
                  Active
                </label>
                <div className="md:col-span-3">
                  <Button type="submit" disabled={updateMutation.isPending}>
                    {updateMutation.isPending ? "Saving..." : "Save Metadata"}
                  </Button>
                  {updateMutation.isError ? <p className="mt-2 text-sm text-red-700">{updateMutation.error.message}</p> : null}
                </div>
              </form>
            </section>

            <section className="rounded-md border border-border bg-white p-5">
              <h2 className="text-base font-semibold">Create New Version</h2>
              <form
                className="mt-4 grid gap-4 md:grid-cols-3"
                data-testid="plan-version-form"
                onSubmit={(event) => {
                  event.preventDefault();
                  const formData = new FormData(event.currentTarget);
                  const values: VersionForm = {
                    currency: String(formData.get("currency") ?? ""),
                    billing_mode_compatibility: String(formData.get("billing_mode_compatibility") ?? "prepaid_credits") as BillingMode,
                    base_price: String(formData.get("base_price") ?? ""),
                    pricing_structure: String(formData.get("pricing_structure") ?? "{}"),
                    limits: String(formData.get("limits") ?? "{}"),
                    included_tokens: Number(formData.get("included_tokens") ?? 0),
                    included_leads: Number(formData.get("included_leads") ?? 0),
                    overage_pricing: String(formData.get("overage_pricing") ?? "{}"),
                    effective_from: String(formData.get("effective_from") ?? ""),
                    effective_to: String(formData.get("effective_to") ?? ""),
                    external_product_plan_id: String(formData.get("external_product_plan_id") ?? ""),
                    reason: String(formData.get("reason") ?? "")
                  };
                  if (!values.currency.trim() || !values.base_price.trim() || !values.effective_from.trim() || !values.reason.trim()) {
                    setVersionSubmitError("Complete the required version fields before creating a version.");
                    return;
                  }
                  setVersionSubmitError(null);
                  versionMutation.mutate(values);
                }}
              >
                <Input placeholder="Currency" maxLength={3} aria-invalid={!!versionForm.formState.errors.currency} {...versionForm.register("currency")} />
                <select className="h-10 rounded-md border border-border bg-white px-3 text-sm" {...versionForm.register("billing_mode_compatibility")}>
                  <option value="prepaid_credits">prepaid_credits</option>
                  <option value="postpaid_manual_settlement">postpaid_manual_settlement</option>
                  <option value="free_internal_testing">free_internal_testing</option>
                </select>
                <Input placeholder="Base price" aria-invalid={!!versionForm.formState.errors.base_price} {...versionForm.register("base_price")} />
                <Input type="datetime-local" aria-invalid={!!versionForm.formState.errors.effective_from} {...versionForm.register("effective_from")} />
                <Input type="datetime-local" {...versionForm.register("effective_to")} />
                <Input placeholder="External product plan ID" {...versionForm.register("external_product_plan_id")} />
                <Input type="number" min={0} placeholder="Included tokens" {...versionForm.register("included_tokens", { valueAsNumber: true, min: 0 })} />
                <Input type="number" min={0} placeholder="Included leads" {...versionForm.register("included_leads", { valueAsNumber: true, min: 0 })} />
                <Input placeholder="Reason" aria-invalid={!!versionForm.formState.errors.reason} {...versionForm.register("reason")} />
                <textarea className="min-h-24 rounded-md border border-border px-3 py-2 text-sm md:col-span-1" placeholder="Pricing structure JSON" {...versionForm.register("pricing_structure")} />
                <textarea className="min-h-24 rounded-md border border-border px-3 py-2 text-sm md:col-span-1" placeholder="Limits JSON" {...versionForm.register("limits")} />
                <textarea className="min-h-24 rounded-md border border-border px-3 py-2 text-sm md:col-span-1" placeholder="Overage pricing JSON" {...versionForm.register("overage_pricing")} />
                <div className="md:col-span-3">
                  <Button type="submit" disabled={versionMutation.isPending}>
                    {versionMutation.isPending ? "Creating..." : "Create Version"}
                  </Button>
                  {versionSubmitError ? <p className="mt-2 text-sm text-red-700">{versionSubmitError}</p> : null}
                </div>
              </form>
            </section>

            <section className="rounded-md border border-border bg-white">
              <div className="border-b border-border px-5 py-4">
                <h2 className="text-base font-semibold">Version Timeline</h2>
              </div>
              {versionsQuery.isLoading ? <p className="p-5 text-sm text-muted-foreground">Loading versions...</p> : null}
              {versionsQuery.data?.data.length === 0 ? <p className="p-5 text-sm text-muted-foreground">No versions yet.</p> : null}
              {versionsQuery.data?.data.length ? (
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm">
                    <thead className="bg-muted text-xs uppercase text-muted-foreground">
                      <tr>
                        <th className="px-4 py-3">Version</th>
                        <th className="px-4 py-3">Price</th>
                        <th className="px-4 py-3">Mode</th>
                        <th className="px-4 py-3">Included</th>
                        <th className="px-4 py-3">Effective</th>
                        <th className="px-4 py-3">Limits</th>
                        <th className="px-4 py-3">Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {versionsQuery.data.data.map((version) => (
                        <tr key={version.id} className="border-t border-border align-top">
                          <td className="px-4 py-3 font-medium">v{version.version_number}</td>
                          <td className="px-4 py-3">{version.price} {version.currency}</td>
                          <td className="px-4 py-3">{version.billing_mode_compatibility}</td>
                          <td className="px-4 py-3">{version.included_tokens} tokens / {version.included_leads} leads</td>
                          <td className="px-4 py-3">{new Date(version.effective_from).toLocaleString()} to {version.effective_to ? new Date(version.effective_to).toLocaleString() : "open"}</td>
                          <td className="px-4 py-3"><code className="text-xs">{jsonPreview(version.limits)}</code></td>
                          <td className="px-4 py-3"><StatusBadge tone={version.is_active ? "success" : "neutral"}>{version.is_active ? "active" : "inactive"}</StatusBadge></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : null}
            </section>
          </>
        ) : null}
      </div>
    </AppShell>
  );
}
