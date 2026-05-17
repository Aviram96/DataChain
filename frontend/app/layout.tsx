import type { Metadata } from "next";

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
          <main className="mx-auto max-w-3xl px-4 py-10">{children}</main>
        </Providers>
      </body>
    </html>
  );
}
