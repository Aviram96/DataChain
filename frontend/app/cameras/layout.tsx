import type { ReactNode } from "react";

export default function CamerasLayout({ children }: { children: ReactNode }) {
  return <div className="-mx-4 max-w-5xl px-4 sm:mx-auto">{children}</div>;
}
