"use client";

import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { AppShell } from "@/components/layout/AppShell";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { listBillingLedger, type LedgerFilters } from "@/lib/billing";

const limit = 25;

export default function BillingPage() {
  const [page, setPage] = useState(0);
  const [filters, setFilters] = useState<LedgerFilters>({});
  const queryFilters = useMemo(() => ({ ...filters, limit, offset: page * limit }), [filters, page]);
  const ledgerQuery = useQuery({ queryKey: ["billing-ledger", queryFilters], queryFn: () => listBillingLedger(queryFilters) });
  const total = ledgerQuery.data?.data.total ?? 0;

  return (
    <AppShell>
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-semibold">Billing Ledger</h1>
          <p className="mt-1 text-sm text-muted-foreground">Append-only financial entries across organizations.</p>
        </div>

        <section className="rounded-md border border-border bg-white p-5">
          <h2 className="text-base font-semibold">Filters</h2>
          <div className="mt-4 grid gap-3 md:grid-cols-4">
            <Input placeholder="Organization ID" onChange={(event) => setFilters((value) => ({ ...value, organization_id: event.target.value }))} />
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
            <select className="h-10 rounded-md border border-border bg-white px-3 text-sm" onChange={(event) => setFilters((value) => ({ ...value, transaction_type: event.target.value }))}>
              <option value="">Transaction type</option>
              <option value="credit_grant">credit_grant</option>
              <option value="credit_deduction">credit_deduction</option>
              <option value="manual_payment">manual_payment</option>
              <option value="usage_charge">usage_charge</option>
              <option value="adjustment">adjustment</option>
              <option value="correction">correction</option>
              <option value="reversal">reversal</option>
            </select>
            <Input type="date" onChange={(event) => setFilters((value) => ({ ...value, date_from: event.target.value }))} />
            <Input type="date" onChange={(event) => setFilters((value) => ({ ...value, date_to: event.target.value }))} />
            <Button type="button" variant="secondary" onClick={() => { setFilters({}); setPage(0); }}>
              Clear
            </Button>
          </div>
        </section>

        <section className="rounded-md border border-border bg-white">
          <div className="flex items-center justify-between border-b border-border px-5 py-4">
            <h2 className="text-base font-semibold">Ledger Entries</h2>
            <p className="text-sm text-muted-foreground">{total} total</p>
          </div>
          {ledgerQuery.isLoading ? <p className="p-5 text-sm text-muted-foreground">Loading ledger...</p> : null}
          {ledgerQuery.isError ? <p className="p-5 text-sm text-red-700">{ledgerQuery.error.message}</p> : null}
          {ledgerQuery.data?.data.items.length === 0 ? <p className="p-5 text-sm text-muted-foreground">No ledger entries found.</p> : null}
          {ledgerQuery.data?.data.items.length ? (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="bg-muted text-xs uppercase text-muted-foreground">
                  <tr>
                    <th className="px-4 py-3">Date</th>
                    <th className="px-4 py-3">Organization</th>
                    <th className="px-4 py-3">Deployment</th>
                    <th className="px-4 py-3">Type</th>
                    <th className="px-4 py-3">Amount</th>
                    <th className="px-4 py-3">Balance</th>
                    <th className="px-4 py-3">Outstanding</th>
                    <th className="px-4 py-3">Sync</th>
                    <th className="px-4 py-3">Note</th>
                  </tr>
                </thead>
                <tbody>
                  {ledgerQuery.data.data.items.map((entry) => (
                    <tr key={entry.id} className="border-t border-border">
                      <td className="px-4 py-3">{new Date(entry.created_at).toLocaleString()}</td>
                      <td className="px-4 py-3">{entry.organization_id}</td>
                      <td className="px-4 py-3">{entry.product_deployment_id}</td>
                      <td className="px-4 py-3">{entry.transaction_type}</td>
                      <td className="px-4 py-3">{entry.amount} {entry.currency}</td>
                      <td className="px-4 py-3">{entry.balance_before} to {entry.balance_after}</td>
                      <td className="px-4 py-3">{entry.outstanding_dues_before} to {entry.outstanding_dues_after}</td>
                      <td className="px-4 py-3">{entry.product_sync_status}</td>
                      <td className="px-4 py-3">{entry.note}</td>
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
