"use client";

import type { ReactNode } from "react";

import { AuthProvider } from "./auth-provider";
import { SiteHeader } from "./site-header";
import { ToastProvider } from "./toast-provider";

export function Providers({ children }: { children: ReactNode }) {
  return (
    <ToastProvider>
      <AuthProvider>
        <SiteHeader />
        {children}
      </AuthProvider>
    </ToastProvider>
  );
}
