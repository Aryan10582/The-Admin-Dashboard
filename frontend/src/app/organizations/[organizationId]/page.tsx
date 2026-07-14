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
import { addCredits, deductCredits, getOrganizationBilling, getOrganizationLedger, recordManualPayment, type FinancialActionPayload } from "@/lib/billing";
import {
  getOrganization,
  updateOrganization,
  updateOrganizationMapping,
  verifyOrganizationMapping
} from "@/lib/organizations";
import type { OrganizationMappingPayload, OrganizationPayload } from "@/lib/types";

const placeholders = ["Service Enforcement", "AI Usage", "Revenue", "Pending Changes", "Audit History", "Impersonation"];
type FinancialFormValues = FinancialActionPayload & { idempotency_key: string };

function statusTone(status: string) {
  if (["active", "healthy_balance", "running", "synced"].includes(status)) return "success";
  if (["trial", "pending", "pending_sync", "requires_manual_review", "missing_product_id"].includes(status)) return "warning";
  if (["suspended", "churned", "failed", "product_mismatch", "verification_failed", "balance_exhausted"].includes(status)) {
    return "danger";
  }
  return "neutral";
}

function mappingWarning(status: string | undefined, productOrgId: string | null | undefined) {
  if (!productOrgId) return "Missing product-side organization ID.";
  if (status === "active") return null;
  if (status === "product_mismatch") return "Product mismatch detected. Review the mapping before using it.";
  if (status === "verification_failed") return "Verification failed. The mapping is not verified.";
  if (status === "requires_manual_review") return "Mapping requires manual review.";
  return "Mapping is not verified.";
}

export default function OrganizationDetailPage() {
  const params = useParams<{ organizationId: string }>();
  const organizationId = params.organizationId;
  const queryClient = useQueryClient();
  const organizationQuery = useQuery({ queryKey: ["organizations", organizationId], queryFn: () => getOrganization(organizationId) });
  const billingQuery = useQuery({ queryKey: ["organizations", organizationId, "billing"], queryFn: () => getOrganizationBilling(organizationId) });
  const ledgerQuery = useQuery({ queryKey: ["organizations", organizationId, "ledger"], queryFn: () => getOrganizationLedger(organizationId, { limit: 10 }) });
  const organizationForm = useForm<OrganizationPayload>();
  const mappingForm = useForm<OrganizationMappingPayload>();
  const addCreditsForm = useForm<FinancialFormValues>({ defaultValues: { amount: "", reason: "", idempotency_key: "" } });
  const deductCreditsForm = useForm<FinancialFormValues>({ defaultValues: { amount: "", reason: "", idempotency_key: "" } });
  const manualPaymentForm = useForm<FinancialFormValues>({ defaultValues: { amount: "", reason: "", idempotency_key: "", payment_method: "", payment_reference: "" } });

  const organization = organizationQuery.data?.data;
  const billingCurrency = billingQuery.data?.data.currency ?? organization?.currency ?? "";

  useEffect(() => {
    if (!organization) return;
    organizationForm.reset({
      name: organization.name,
      product_deployment_id: organization.product_deployment_id,
      currency: organization.currency,
      lifecycle_status: organization.lifecycle_status,
      billing_mode: organization.billing_mode,
      billing_calculation_status: organization.billing_calculation_status,
      credit_status: organization.credit_status,
      service_status: organization.service_status,
      sync_status: organization.sync_status,
      last_active_at: organization.last_active_at
    });
    mappingForm.reset({
      product_deployment_id: organization.product_deployment_id,
      product_organization_id: organization.mapping?.product_organization_id ?? "",
      mapping_status: organization.mapping?.mapping_status ?? "requires_manual_review",
      external_billing_id: organization.mapping?.external_billing_id ?? "",
      external_customer_id: organization.mapping?.external_customer_id ?? "",
      external_plan_id: organization.mapping?.external_plan_id ?? "",
      external_subscription_id: organization.mapping?.external_subscription_id ?? ""
    });
  }, [mappingForm, organization, organizationForm]);

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["organizations"] });
    await queryClient.invalidateQueries({ queryKey: ["organizations", organizationId] });
    await queryClient.invalidateQueries({ queryKey: ["organizations", organizationId, "billing"] });
    await queryClient.invalidateQueries({ queryKey: ["organizations", organizationId, "ledger"] });
  };

  const updateMutation = useMutation({ mutationFn: (values: OrganizationPayload) => updateOrganization(organizationId, values), onSuccess: refresh });
  const mappingMutation = useMutation({ mutationFn: (values: OrganizationMappingPayload) => updateOrganizationMapping(organizationId, values), onSuccess: refresh });
  const verifyMutation = useMutation({ mutationFn: () => verifyOrganizationMapping(organizationId), onSuccess: refresh });
  const addCreditsMutation = useMutation({
    mutationFn: (values: FinancialFormValues) =>
      addCredits(organizationId, { amount: values.amount, currency: billingCurrency, reason: values.reason }, values.idempotency_key),
    onSuccess: async () => {
      addCreditsForm.reset({ amount: "", reason: "", idempotency_key: "" });
      await refresh();
    }
  });
  const deductCreditsMutation = useMutation({
    mutationFn: (values: FinancialFormValues) =>
      deductCredits(
        organizationId,
        { amount: values.amount, currency: billingCurrency, reason: values.reason },
        values.idempotency_key
      ),
    onSuccess: async () => {
      deductCreditsForm.reset({ amount: "", reason: "", idempotency_key: "" });
      await refresh();
    }
  });
  const manualPaymentMutation = useMutation({
    mutationFn: (values: FinancialFormValues) =>
      recordManualPayment(
        organizationId,
        {
          amount: values.amount,
          currency: billingCurrency,
          reason: values.reason,
          payment_method: values.payment_method || null,
          payment_reference: values.payment_reference || null
        },
        values.idempotency_key
      ),
    onSuccess: async () => {
      manualPaymentForm.reset({ amount: "", reason: "", idempotency_key: "", payment_method: "", payment_reference: "" });
      await refresh();
    }
  });

  const warning = mappingWarning(organization?.mapping?.mapping_status, organization?.mapping?.product_organization_id);

  return (
    <AppShell>
      <div className="space-y-6">
        <Link className="text-sm text-primary hover:underline" href="/organizations">
          Back to organizations
        </Link>

        {organizationQuery.isLoading ? <p className="text-sm text-muted-foreground">Loading organization...</p> : null}
        {organizationQuery.isError ? <p className="text-sm text-red-700">{organizationQuery.error.message}</p> : null}

        {organization ? (
          <>
            <div>
              <h1 className="text-2xl font-semibold">{organization.name}</h1>
              <p className="mt-1 text-sm text-muted-foreground">
                {organization.product_deployment.product_name} / {organization.product_deployment.region} / {organization.product_deployment.environment}
              </p>
            </div>

            {organization.product_deployment.environment === "production" ? (
              <div className="rounded-md border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
                Production environment. Verify product-side organization IDs carefully before future operational actions.
              </div>
            ) : null}
            {warning ? <div className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-800">{warning}</div> : null}

            <section className="grid gap-4 md:grid-cols-4">
              <div className="rounded-md border border-border bg-white p-4">
                <p className="text-xs uppercase text-muted-foreground">Lifecycle</p>
                <div className="mt-2"><StatusBadge tone={statusTone(organization.lifecycle_status)}>{organization.lifecycle_status}</StatusBadge></div>
              </div>
              <div className="rounded-md border border-border bg-white p-4">
                <p className="text-xs uppercase text-muted-foreground">Service</p>
                <div className="mt-2"><StatusBadge tone={statusTone(organization.service_status)}>{organization.service_status}</StatusBadge></div>
              </div>
              <div className="rounded-md border border-border bg-white p-4">
                <p className="text-xs uppercase text-muted-foreground">Sync</p>
                <div className="mt-2"><StatusBadge tone={statusTone(organization.sync_status)}>{organization.sync_status}</StatusBadge></div>
              </div>
              <div className="rounded-md border border-border bg-white p-4">
                <p className="text-xs uppercase text-muted-foreground">Mapping</p>
                <div className="mt-2"><StatusBadge tone={statusTone(organization.mapping?.mapping_status ?? "missing_product_id")}>{organization.mapping?.mapping_status ?? "missing_product_id"}</StatusBadge></div>
              </div>
            </section>

            <section className="rounded-md border border-border bg-white p-5">
              <h2 className="text-base font-semibold">Organization Information</h2>
              <dl className="mt-4 grid gap-4 text-sm md:grid-cols-2">
                <div><dt className="text-muted-foreground">Central organization ID</dt><dd>{organization.central_organization_id}</dd></div>
                <div><dt className="text-muted-foreground">Currency</dt><dd>{organization.currency}</dd></div>
                <div><dt className="text-muted-foreground">Billing mode</dt><dd>{organization.billing_mode}</dd></div>
                <div><dt className="text-muted-foreground">Billing calculation</dt><dd>{organization.billing_calculation_status}</dd></div>
                <div><dt className="text-muted-foreground">Credit status</dt><dd>{organization.credit_status}</dd></div>
                <div><dt className="text-muted-foreground">Last active</dt><dd>{organization.last_active_at ? new Date(organization.last_active_at).toLocaleString() : "-"}</dd></div>
              </dl>
            </section>

            <section className="rounded-md border border-border bg-white p-5">
              <h2 className="text-base font-semibold">Edit Organization</h2>
              <form className="mt-4 grid gap-4 md:grid-cols-3" onSubmit={organizationForm.handleSubmit((values) => updateMutation.mutate(values))}>
                <Input placeholder="Organization name" {...organizationForm.register("name", { required: true })} />
                <Input placeholder="Currency" maxLength={3} {...organizationForm.register("currency", { required: true })} />
                <select className="h-10 rounded-md border border-border bg-white px-3 text-sm" {...organizationForm.register("lifecycle_status")}>
                  <option value="trial">trial</option><option value="active">active</option><option value="suspended">suspended</option><option value="churned">churned</option><option value="internal_testing">internal_testing</option><option value="demo">demo</option>
                </select>
                <select className="h-10 rounded-md border border-border bg-white px-3 text-sm" {...organizationForm.register("billing_mode")}>
                  <option value="prepaid_credits">prepaid_credits</option><option value="postpaid_manual_settlement">postpaid_manual_settlement</option><option value="free_internal_testing">free_internal_testing</option>
                </select>
                <select className="h-10 rounded-md border border-border bg-white px-3 text-sm" {...organizationForm.register("credit_status")}>
                  <option value="not_applicable">not_applicable</option><option value="healthy_balance">healthy_balance</option><option value="low_balance">low_balance</option><option value="zero_balance">zero_balance</option><option value="balance_exhausted">balance_exhausted</option><option value="outstanding_dues">outstanding_dues</option>
                </select>
                <select className="h-10 rounded-md border border-border bg-white px-3 text-sm" {...organizationForm.register("service_status")}>
                  <option value="pending_sync">pending_sync</option><option value="running">running</option><option value="paused">paused</option><option value="disabled">disabled</option>
                </select>
                <div className="md:col-span-3">
                  <Button type="submit" disabled={updateMutation.isPending}>{updateMutation.isPending ? "Saving..." : "Save Organization"}</Button>
                  {updateMutation.isError ? <p className="mt-2 text-sm text-red-700">{updateMutation.error.message}</p> : null}
                </div>
              </form>
            </section>

            <section className="rounded-md border border-border bg-white p-5">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <h2 className="text-base font-semibold">External Mapping</h2>
                <Button type="button" onClick={() => verifyMutation.mutate()} disabled={verifyMutation.isPending}>
                  {verifyMutation.isPending ? "Verifying..." : "Verify Mapping"}
                </Button>
              </div>
              <dl className="mt-4 grid gap-4 text-sm md:grid-cols-2">
                <div><dt className="text-muted-foreground">Product-side organization ID</dt><dd>{organization.mapping?.product_organization_id ?? "-"}</dd></div>
                <div><dt className="text-muted-foreground">Last verified</dt><dd>{organization.mapping?.last_verified_at ? new Date(organization.mapping.last_verified_at).toLocaleString() : "-"}</dd></div>
                <div><dt className="text-muted-foreground">Product API version</dt><dd>{organization.mapping?.product_api_version ?? organization.product_deployment.admin_api_version}</dd></div>
                <div><dt className="text-muted-foreground">Safe verification result</dt><dd>{verifyMutation.data?.data.message ?? "-"}</dd></div>
              </dl>
              <form className="mt-4 grid gap-4 md:grid-cols-3" onSubmit={mappingForm.handleSubmit((values) => mappingMutation.mutate(values))}>
                <Input placeholder="Product-side organization ID" {...mappingForm.register("product_organization_id")} />
                <select className="h-10 rounded-md border border-border bg-white px-3 text-sm" {...mappingForm.register("mapping_status")}>
                  <option value="requires_manual_review">requires_manual_review</option>
                  <option value="inactive">inactive</option>
                  <option value="missing_product_id">missing_product_id</option>
                  <option value="verification_failed">verification_failed</option>
                </select>
                <Input placeholder="External customer ID" {...mappingForm.register("external_customer_id")} />
                <Input placeholder="External billing ID" {...mappingForm.register("external_billing_id")} />
                <Input placeholder="External plan ID" {...mappingForm.register("external_plan_id")} />
                <Input placeholder="External subscription ID" {...mappingForm.register("external_subscription_id")} />
                <div className="md:col-span-3">
                  <Button type="submit" disabled={mappingMutation.isPending}>{mappingMutation.isPending ? "Saving..." : "Save Mapping"}</Button>
                  {mappingMutation.isError ? <p className="mt-2 text-sm text-red-700">{mappingMutation.error.message}</p> : null}
                  {verifyMutation.isError ? <p className="mt-2 text-sm text-red-700">{verifyMutation.error.message}</p> : null}
                  {verifyMutation.isSuccess ? <p className="mt-2 text-sm text-muted-foreground">Verification finished: {verifyMutation.data.data.mapping.mapping_status}</p> : null}
                </div>
              </form>
            </section>

            <section className="rounded-md border border-border bg-white p-5">
              <h2 className="text-base font-semibold">Billing</h2>
              {billingQuery.isLoading ? <p className="mt-3 text-sm text-muted-foreground">Loading billing...</p> : null}
              {billingQuery.isError ? <p className="mt-3 text-sm text-red-700">{billingQuery.error.message}</p> : null}
              {billingQuery.data ? (
                <div className="mt-4 grid gap-4 md:grid-cols-4">
                  <div><p className="text-xs uppercase text-muted-foreground">Credit Balance</p><p className="mt-1 text-sm font-medium">{billingQuery.data.data.credit_balance} {billingQuery.data.data.currency}</p></div>
                  <div><p className="text-xs uppercase text-muted-foreground">Outstanding Dues</p><p className="mt-1 text-sm font-medium">{billingQuery.data.data.outstanding_dues} {billingQuery.data.data.currency}</p></div>
                  <div><p className="text-xs uppercase text-muted-foreground">Billing Mode</p><p className="mt-1 text-sm">{billingQuery.data.data.billing_mode}</p></div>
                  <div><p className="text-xs uppercase text-muted-foreground">Credit Status</p><p className="mt-1 text-sm">{billingQuery.data.data.credit_status}</p></div>
                </div>
              ) : null}

              <div className="mt-6 grid gap-5 lg:grid-cols-3">
                <form className="rounded-md border border-border p-4" onSubmit={addCreditsForm.handleSubmit((values) => addCreditsMutation.mutate(values))}>
                  <h3 className="text-sm font-semibold">Add Credits</h3>
                  <div className="mt-3 space-y-3">
                    <Input placeholder="Amount" {...addCreditsForm.register("amount", { required: true })} />
                    <Input placeholder="Reason / note" {...addCreditsForm.register("reason", { required: true })} />
                    <Input placeholder="Idempotency key" {...addCreditsForm.register("idempotency_key", { required: true })} />
                    <Button type="submit" disabled={addCreditsMutation.isPending}>{addCreditsMutation.isPending ? "Adding..." : "Add Credits"}</Button>
                    {addCreditsMutation.data ? <p className="text-sm text-muted-foreground">Saved with sync status {addCreditsMutation.data.data.ledger_entry.product_sync_status}.</p> : null}
                    {addCreditsMutation.isError ? <p className="text-sm text-red-700">{addCreditsMutation.error.message}</p> : null}
                  </div>
                </form>

                <form className="rounded-md border border-border p-4" onSubmit={deductCreditsForm.handleSubmit((values) => deductCreditsMutation.mutate(values))}>
                  <h3 className="text-sm font-semibold">Deduct Credits</h3>
                  <div className="mt-3 space-y-3">
                    <Input placeholder="Amount" {...deductCreditsForm.register("amount", { required: true })} />
                    <Input placeholder="Reason / note" {...deductCreditsForm.register("reason", { required: true })} />
                    <Input placeholder="Idempotency key" {...deductCreditsForm.register("idempotency_key", { required: true })} />
                    <Button type="submit" disabled={deductCreditsMutation.isPending}>{deductCreditsMutation.isPending ? "Deducting..." : "Deduct Credits"}</Button>
                    {deductCreditsMutation.data ? <p className="text-sm text-muted-foreground">Saved with sync status {deductCreditsMutation.data.data.ledger_entry.product_sync_status}.</p> : null}
                    {deductCreditsMutation.isError ? <p className="text-sm text-red-700">{deductCreditsMutation.error.message}</p> : null}
                  </div>
                </form>

                <form className="rounded-md border border-border p-4" onSubmit={manualPaymentForm.handleSubmit((values) => manualPaymentMutation.mutate(values))}>
                  <h3 className="text-sm font-semibold">Manual Payment</h3>
                  <div className="mt-3 space-y-3">
                    <Input placeholder="Amount" {...manualPaymentForm.register("amount", { required: true })} />
                    <Input placeholder="Reason / note" {...manualPaymentForm.register("reason", { required: true })} />
                    <Input placeholder="Idempotency key" {...manualPaymentForm.register("idempotency_key", { required: true })} />
                    <Input placeholder="Payment method" {...manualPaymentForm.register("payment_method")} />
                    <Input placeholder="Payment reference" {...manualPaymentForm.register("payment_reference")} />
                    <Button type="submit" disabled={manualPaymentMutation.isPending}>{manualPaymentMutation.isPending ? "Recording..." : "Record Payment"}</Button>
                    {manualPaymentMutation.data ? <p className="text-sm text-muted-foreground">Saved with sync status {manualPaymentMutation.data.data.ledger_entry.product_sync_status}.</p> : null}
                    {manualPaymentMutation.isError ? <p className="text-sm text-red-700">{manualPaymentMutation.error.message}</p> : null}
                  </div>
                </form>
              </div>

              <div className="mt-6">
                <h3 className="text-sm font-semibold">Recent Ledger Entries</h3>
                {ledgerQuery.data?.data.items.length ? (
                  <div className="mt-3 overflow-x-auto">
                    <table className="w-full text-left text-sm">
                      <thead className="bg-muted text-xs uppercase text-muted-foreground">
                        <tr><th className="px-3 py-2">Date</th><th className="px-3 py-2">Type</th><th className="px-3 py-2">Amount</th><th className="px-3 py-2">Balance</th><th className="px-3 py-2">Sync</th><th className="px-3 py-2">Note</th></tr>
                      </thead>
                      <tbody>
                        {ledgerQuery.data.data.items.map((entry) => (
                          <tr key={entry.id} className="border-t border-border">
                            <td className="px-3 py-2">{new Date(entry.created_at).toLocaleString()}</td>
                            <td className="px-3 py-2">{entry.transaction_type}</td>
                            <td className="px-3 py-2">{entry.amount} {entry.currency}</td>
                            <td className="px-3 py-2">{entry.balance_before} to {entry.balance_after}</td>
                            <td className="px-3 py-2">{entry.product_sync_status}</td>
                            <td className="px-3 py-2">{entry.note}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : <p className="mt-3 text-sm text-muted-foreground">No ledger entries yet.</p>}
              </div>
            </section>

            <section className="grid gap-4 md:grid-cols-2">
              {placeholders.map((label) => (
                <div key={label} className="rounded-md border border-border bg-white p-4">
                  <h3 className="text-sm font-semibold">{label}</h3>
                  <p className="mt-2 text-sm text-muted-foreground">This feature is not implemented yet.</p>
                </div>
              ))}
            </section>
          </>
        ) : null}
      </div>
    </AppShell>
  );
}
