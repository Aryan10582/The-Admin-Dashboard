"use client";

import { useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { useCurrentAdmin } from "@/hooks/useCurrentAdmin";

export function AuthGuard({ children }: { children: ReactNode }) {
  const router = useRouter();
  const { isError, isLoading } = useCurrentAdmin();

  useEffect(() => {
    if (isError) {
      router.replace("/login");
    }
  }, [isError, router]);

  if (isLoading) {
    return <div className="flex min-h-screen items-center justify-center text-sm text-muted-foreground">Loading...</div>;
  }

  if (isError) {
    return null;
  }

  return <>{children}</>;
}
