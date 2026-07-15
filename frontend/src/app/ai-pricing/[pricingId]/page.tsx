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
import {
  approveAiPricingCheckRun,
  createAiPricingVersion,
  getAiPricingCatalog,
  listAiPricingCheckRuns,
  listAiPricingVersions,
  rejectAiPricingCheckRun,
  runAiPricingCheck,
  updateAiPricingCatalog
} from "@/lib/aiPricing";

type MetadataForm = {
  display_name: string;
  description: string;
  is_active: boolean;
  reason: string;
};

type VersionForm = {
  input_token_price: string;
  output_token_price: string;
  pricing_unit_tokens: number;
  effective_from: string;
  effective_to: string;
  source_reference: string;
  reason: string;
  idempotency_key: string;
};

type CheckForm = {
  reason: string;
  idempotency_key: string;
  mock_scenario: string;
};

type ReviewForm = {
  reason: string;
  idempotency_key: string;
};

const versionDefaults: VersionForm = {
  input_token_price: "0.00000000",
  output_token_price: "0.00000000",
  pricing_unit_tokens: 1000000,
  effective_from: "",
  effective_to: "",
  source_reference: "",
  reason: "",
  idempotency_key: ""
};

function toneForState(state: string) {
  if (state === "current") return "success";
  if (state === "future") return "warning";
  return "neutral";
}

export default function AiPricingDetailPage() {
  const params = useParams<{ pricingId: string }>();
  const pricingId = params.pricingId;
  const queryClient = useQueryClient();
  const metadataForm = useForm<MetadataForm>();
  const versionForm = useForm<VersionForm>({ defaultValues: versionDefaults });
  const checkForm = useForm<CheckForm>({ defaultValues: { reason: "", idempotency_key: "", mock_scenario: "unchanged" } });
  const reviewForm = useForm<ReviewForm>({ defaultValues: { reason: "", idempotency_key: "" } });
  const catalogQuery = useQuery({ queryKey: ["ai-pricing", pricingId], queryFn: () => getAiPricingCatalog(pricingId) });
  const versionsQuery = useQuery({ queryKey: ["ai-pricing", pricingId, "versions"], queryFn: () => listAiPricingVersions(pricingId) });
  const checksQuery = useQuery({ queryKey: ["ai-pricing", pricingId, "check-runs"], queryFn: () => listAiPricingCheckRuns({ pricing_catalog_id: pricingId, limit: 20 }) });
  const catalog = catalogQuery.data?.data;

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["ai-pricing"] });
    await queryClient.invalidateQueries({ queryKey: ["ai-pricing", pricingId] });
    await queryClient.invalidateQueries({ queryKey: ["ai-pricing", pricingId, "versions"] });
    await queryClient.invalidateQueries({ queryKey: ["ai-pricing", pricingId, "check-runs"] });
  };

  const updateMutation = useMutation({
    mutationFn: (values: MetadataForm) => updateAiPricingCatalog(pricingId, values),
    onSuccess: refresh
  });
  const versionMutation = useMutation({
    mutationFn: (values: VersionForm) => createAiPricingVersion(pricingId, values, values.idempotency_key),
    onSuccess: async () => {
      versionForm.reset(versionDefaults);
      await refresh();
    }
  });
  const checkMutation = useMutation({
    mutationFn: (values: CheckForm) =>
      runAiPricingCheck(
        {
          pricing_catalog_id: pricingId,
          reason: values.reason,
          adapter_code: "development_mock",
          mock_scenario: values.mock_scenario || undefined
        },
        values.idempotency_key
      ),
    onSuccess: async () => {
      checkForm.reset({ reason: "", idempotency_key: "", mock_scenario: "unchanged" });
      await refresh();
    }
  });
  const approveMutation = useMutation({
    mutationFn: (values: { checkRunId: string; reason: string; idempotencyKey: string }) =>
      approveAiPricingCheckRun(values.checkRunId, { reason: values.reason }, values.idempotencyKey),
    onSuccess: refresh
  });
  const rejectMutation = useMutation({
    mutationFn: (values: { checkRunId: string; reason: string; idempotencyKey: string }) =>
      rejectAiPricingCheckRun(values.checkRunId, { reason: values.reason }, values.idempotencyKey),
    onSuccess: refresh
  });

  useEffect(() => {
    if (!catalog) return;
    metadataForm.reset({
      display_name: catalog.display_name,
      description: catalog.description ?? "",
      is_active: catalog.is_active,
      reason: ""
    });
  }, [catalog, metadataForm]);

  return (
    <AppShell>
      <div className="space-y-6">
        <Link className="text-sm text-primary hover:underline" href="/ai-pricing">Back to AI pricing</Link>
        {catalogQuery.isLoading ? <p className="text-sm text-muted-foreground">Loading pricing catalog...</p> : null}
        {catalogQuery.isError ? <p className="text-sm text-red-700">{catalogQuery.error.message}</p> : null}
        {catalog ? (
          <>
            <div>
              <h1 className="text-2xl font-semibold">{catalog.display_name}</h1>
              <p className="mt-1 text-sm text-muted-foreground">
                {catalog.provider} / {catalog.provider_model_id} / {catalog.pricing_scope_code} / {catalog.currency}
              </p>
            </div>

            <section className="rounded-md border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
              Historical pricing versions are immutable. Pricing corrections require a new version. Current pricing changes do not modify old versions.
            </section>

            <section className="grid gap-4 md:grid-cols-4">
              <div className="rounded-md border border-border bg-white p-4">
                <p className="text-xs uppercase text-muted-foreground">Current Version</p>
                <p className="mt-1 text-lg font-semibold">v{catalog.current_effective_version?.version_number ?? "-"}</p>
              </div>
              <div className="rounded-md border border-border bg-white p-4">
                <p className="text-xs uppercase text-muted-foreground">Latest Version</p>
                <p className="mt-1 text-lg font-semibold">v{catalog.latest_version?.version_number ?? "-"}</p>
              </div>
              <div className="rounded-md border border-border bg-white p-4">
                <p className="text-xs uppercase text-muted-foreground">Current Input</p>
                <p className="mt-1 text-lg font-semibold">{catalog.current_effective_version?.input_token_price ?? "-"}</p>
              </div>
              <div className="rounded-md border border-border bg-white p-4">
                <p className="text-xs uppercase text-muted-foreground">Current Output</p>
                <p className="mt-1 text-lg font-semibold">{catalog.current_effective_version?.output_token_price ?? "-"}</p>
              </div>
            </section>

            <section className="rounded-md border border-border bg-white p-5">
              <h2 className="text-base font-semibold">Trusted Pricing Check</h2>
              <div className="mt-3 grid gap-4 md:grid-cols-4">
                <div>
                  <p className="text-xs uppercase text-muted-foreground">Last Check</p>
                  <p className="mt-1 text-sm">{catalog.last_check_status ?? "-"}</p>
                </div>
                <div>
                  <p className="text-xs uppercase text-muted-foreground">Source State</p>
                  <p className="mt-1 text-sm">{catalog.source_state}</p>
                </div>
                <div>
                  <p className="text-xs uppercase text-muted-foreground">Unresolved Reviews</p>
                  <p className="mt-1 text-sm">{catalog.unresolved_review_count}</p>
                </div>
                <div>
                  <p className="text-xs uppercase text-muted-foreground">Last Error</p>
                  <p className="mt-1 text-sm">{catalog.safe_last_error ?? "-"}</p>
                </div>
              </div>
              <form className="mt-4 grid gap-4 md:grid-cols-4" onSubmit={checkForm.handleSubmit((values) => checkMutation.mutate(values))}>
                <select className="h-10 rounded-md border border-border bg-white px-3 text-sm" {...checkForm.register("mock_scenario")}>
                  <option value="unchanged">unchanged</option>
                  <option value="input_price_changed">input_price_changed</option>
                  <option value="output_price_changed">output_price_changed</option>
                  <option value="both_changed">both_changed</option>
                  <option value="missing_currency">missing_currency</option>
                  <option value="missing_pricing_unit">missing_pricing_unit</option>
                  <option value="missing_output_price">missing_output_price</option>
                  <option value="unknown_model">unknown_model</option>
                  <option value="contradictory_duplicate_entries">contradictory_duplicate_entries</option>
                </select>
                <Input placeholder="Reason / note" {...checkForm.register("reason", { required: true })} />
                <Input placeholder="Idempotency key" {...checkForm.register("idempotency_key", { required: true })} />
                <div>
                  <Button type="submit" disabled={checkMutation.isPending}>{checkMutation.isPending ? "Checking..." : "Check Pricing Now"}</Button>
                </div>
                {checkMutation.isError ? <p className="text-sm text-red-700 md:col-span-4">{checkMutation.error.message}</p> : null}
              </form>
            </section>

            <section className="rounded-md border border-border bg-white p-5">
              <h2 className="text-base font-semibold">Stable Metadata</h2>
              <form className="mt-4 grid gap-4 md:grid-cols-3" onSubmit={metadataForm.handleSubmit((values) => updateMutation.mutate(values))}>
                <Input placeholder="Display name" {...metadataForm.register("display_name", { required: true })} />
                <Input className="md:col-span-2" placeholder="Description" {...metadataForm.register("description")} />
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" {...metadataForm.register("is_active")} />
                  Active
                </label>
                <Input className="md:col-span-2" placeholder="Reason / note" {...metadataForm.register("reason", { required: true })} />
                <div className="md:col-span-3">
                  <Button type="submit" disabled={updateMutation.isPending}>{updateMutation.isPending ? "Saving..." : "Save Metadata"}</Button>
                  {updateMutation.isError ? <p className="mt-2 text-sm text-red-700">{updateMutation.error.message}</p> : null}
                </div>
              </form>
            </section>

            <section className="rounded-md border border-border bg-white p-5">
              <h2 className="text-base font-semibold">Create Manual Version</h2>
              <form className="mt-4 grid gap-4 md:grid-cols-4" onSubmit={versionForm.handleSubmit((values) => versionMutation.mutate(values))}>
                <Input placeholder="Input token price" {...versionForm.register("input_token_price", { required: true })} />
                <Input placeholder="Output token price" {...versionForm.register("output_token_price", { required: true })} />
                <Input type="number" min={1} placeholder="Pricing unit tokens" {...versionForm.register("pricing_unit_tokens", { valueAsNumber: true, min: 1 })} />
                <Input placeholder="Source reference" {...versionForm.register("source_reference")} />
                <Input type="datetime-local" {...versionForm.register("effective_from", { required: true })} />
                <Input type="datetime-local" {...versionForm.register("effective_to")} />
                <Input placeholder="Reason / note" {...versionForm.register("reason", { required: true })} />
                <Input placeholder="Idempotency key" {...versionForm.register("idempotency_key", { required: true })} />
                <div className="md:col-span-4">
                  <Button type="submit" disabled={versionMutation.isPending}>{versionMutation.isPending ? "Creating..." : "Create Version"}</Button>
                  {versionMutation.isError ? <p className="mt-2 text-sm text-red-700">{versionMutation.error.message}</p> : null}
                </div>
              </form>
            </section>

            <section className="rounded-md border border-border bg-white">
              <div className="border-b border-border px-5 py-4">
                <h2 className="text-base font-semibold">Pricing History</h2>
              </div>
              {versionsQuery.isLoading ? <p className="p-5 text-sm text-muted-foreground">Loading pricing versions...</p> : null}
              {versionsQuery.data?.data.length === 0 ? <p className="p-5 text-sm text-muted-foreground">No pricing versions yet.</p> : null}
              {versionsQuery.data?.data.length ? (
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm">
                    <thead className="bg-muted text-xs uppercase text-muted-foreground">
                      <tr>
                        <th className="px-4 py-3">Version</th>
                        <th className="px-4 py-3">Prices</th>
                        <th className="px-4 py-3">Unit</th>
                        <th className="px-4 py-3">Effective</th>
                        <th className="px-4 py-3">Source</th>
                        <th className="px-4 py-3">State</th>
                      </tr>
                    </thead>
                    <tbody>
                      {versionsQuery.data.data.map((version) => (
                        <tr key={version.id} className="border-t border-border align-top">
                          <td className="px-4 py-3 font-medium">v{version.version_number}</td>
                          <td className="px-4 py-3">{version.input_token_price} in / {version.output_token_price} out {catalog.currency}</td>
                          <td className="px-4 py-3">per {version.pricing_unit_tokens} tokens</td>
                          <td className="px-4 py-3">{new Date(version.effective_from).toLocaleString()} to {version.effective_to ? new Date(version.effective_to).toLocaleString() : "open"}</td>
                          <td className="px-4 py-3">{version.source_type}{version.source_reference ? ` / ${version.source_reference}` : ""}</td>
                          <td className="px-4 py-3"><StatusBadge tone={toneForState(version.effective_state)}>{version.effective_state}</StatusBadge></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : null}
            </section>

            <section className="rounded-md border border-border bg-white">
              <div className="border-b border-border px-5 py-4">
                <h2 className="text-base font-semibold">Check History</h2>
              </div>
              {checksQuery.isLoading ? <p className="p-5 text-sm text-muted-foreground">Loading check runs...</p> : null}
              {checksQuery.data?.data.items.length === 0 ? <p className="p-5 text-sm text-muted-foreground">No check runs yet.</p> : null}
              {checksQuery.data?.data.items.length ? (
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm">
                    <thead className="bg-muted text-xs uppercase text-muted-foreground">
                      <tr>
                        <th className="px-4 py-3">Run</th>
                        <th className="px-4 py-3">Candidate</th>
                        <th className="px-4 py-3">Source</th>
                        <th className="px-4 py-3">Review</th>
                        <th className="px-4 py-3">Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {checksQuery.data.data.items.map((run) => (
                        <tr key={run.id} className="border-t border-border align-top">
                          <td className="px-4 py-3">
                            <StatusBadge tone={run.status === "version_created" || run.status === "approved" || run.status === "unchanged" ? "success" : run.status === "requires_manual_review" ? "warning" : "neutral"}>{run.status}</StatusBadge>
                            <div className="mt-1 text-xs text-muted-foreground">{new Date(run.started_at).toLocaleString()}</div>
                          </td>
                          <td className="px-4 py-3">
                            {run.candidate_input_price ?? "-"} in / {run.candidate_output_price ?? "-"} out
                            <div className="text-xs text-muted-foreground">{run.candidate_currency ?? "-"} per {run.candidate_pricing_unit_tokens ?? "-"}</div>
                          </td>
                          <td className="px-4 py-3">
                            {run.source_reference ?? "-"}
                            <div className="text-xs text-muted-foreground">{run.source_fingerprint ? `${run.source_fingerprint.slice(0, 12)}...` : "-"}</div>
                            {run.safe_error ? <div className="text-xs text-red-700">{run.safe_error}</div> : null}
                          </td>
                          <td className="px-4 py-3">{run.review_decision ?? (run.status === "requires_manual_review" ? "unreviewed" : "-")}</td>
                          <td className="px-4 py-3">
                            {run.status === "requires_manual_review" && !run.reviewed_at ? (
                              <form
                                className="grid gap-2"
                                onSubmit={reviewForm.handleSubmit((values) =>
                                  approveMutation.mutate({ checkRunId: run.id, reason: values.reason, idempotencyKey: values.idempotency_key })
                                )}
                              >
                                <Input placeholder="Reason" {...reviewForm.register("reason", { required: true })} />
                                <Input placeholder="Idempotency key" {...reviewForm.register("idempotency_key", { required: true })} />
                                <div className="flex gap-2">
                                  <Button type="submit" disabled={approveMutation.isPending}>Approve</Button>
                                  <Button
                                    type="button"
                                    variant="secondary"
                                    disabled={rejectMutation.isPending}
                                    onClick={reviewForm.handleSubmit((values) => rejectMutation.mutate({ checkRunId: run.id, reason: values.reason, idempotencyKey: values.idempotency_key }))}
                                  >
                                    Reject
                                  </Button>
                                </div>
                              </form>
                            ) : run.created_version_id ? (
                              <span className="text-xs text-muted-foreground">Created version {run.created_version_id.slice(0, 8)}</span>
                            ) : (
                              <span className="text-xs text-muted-foreground">-</span>
                            )}
                          </td>
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
