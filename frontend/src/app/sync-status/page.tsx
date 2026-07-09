import { AppShell } from "@/components/layout/AppShell";

export default function SyncStatusPage() {
  return (
    <AppShell>
      <h1 className="text-2xl font-semibold">Sync Status</h1>
      <p className="mt-2 text-sm text-muted-foreground">Product sync workflows are intentionally deferred.</p>
    </AppShell>
  );
}
