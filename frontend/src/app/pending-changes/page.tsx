import { AppShell } from "@/components/layout/AppShell";

export default function PendingChangesPage() {
  return (
    <AppShell>
      <h1 className="text-2xl font-semibold">Pending Changes</h1>
      <p className="mt-2 text-sm text-muted-foreground">Pending product changes are intentionally deferred.</p>
    </AppShell>
  );
}
