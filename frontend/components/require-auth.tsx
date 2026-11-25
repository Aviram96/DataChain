"use client";

import { useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { ui } from "@/lib/ui";

import { useAuth } from "./auth-provider";

export function RequireAuth({ children }: { children: ReactNode }) {
  const router = useRouter();
  const { user, isLoading } = useAuth();

  useEffect(() => {
    if (!isLoading && !user) {
      router.replace("/login");
    }
  }, [isLoading, user, router]);

  if (isLoading) {
    return <p className={ui.muted}>Loading…</p>;
  }

  if (!user) {
    return null;
  }

  return <>{children}</>;
}
