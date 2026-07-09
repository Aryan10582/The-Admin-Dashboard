"use client";

import { useQuery } from "@tanstack/react-query";

import { getCurrentAdmin } from "@/lib/auth";

export function useCurrentAdmin() {
  return useQuery({
    queryKey: ["current-admin"],
    queryFn: getCurrentAdmin
  });
}
