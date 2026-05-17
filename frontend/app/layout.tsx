import type { Metadata } from "next";
import Link from "next/link";

import { Providers } from "@/components/providers";

import "./globals.css";

export const metadata: Metadata = {
  title: "Datachain",
  description: "Tamper-evident CCTV video management (Epic 1 scaffold).",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>
        <Providers>
          <header className="border-b border-slate-800 bg-slate-900/80 backdrop-blur">
            <nav className="mx-auto flex max-w-3xl items-center gap-6 px-4 py-3 text-sm font-medium">
              <Link href="/" className="text-slate-100 hover:text-white">
                Home
              </Link>
              <Link
                href="/login"
                className="text-slate-400 hover:text-white"
              >
                Sign in
              </Link>
              <Link
                href="/register"
                className="text-slate-400 hover:text-white"
              >
                Register
              </Link>
              <Link
                href="/project-status"
                className="text-slate-400 hover:text-white"
              >
                Project status
              </Link>
            </nav>
          </header>
          <main className="mx-auto max-w-3xl px-4 py-10">{children}</main>
        </Providers>
      </body>
    </html>
  );
}
