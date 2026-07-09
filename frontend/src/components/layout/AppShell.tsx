import type { ReactNode } from "react";

import { AuthGuard } from "@/components/layout/AuthGuard";
import { Sidebar } from "@/components/layout/Sidebar";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <AuthGuard>
      <div className="flex min-h-screen bg-slate-50">
        <Sidebar />
        <main className="min-w-0 flex-1 p-8">{children}</main>
      </div>
    </AuthGuard>
  );
}
