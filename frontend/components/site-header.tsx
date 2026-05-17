"use client";

import Link from "next/link";

import { useAuth } from "./auth-provider";

const navLinkClass = "text-slate-400 hover:text-white";

export function SiteHeader() {
  const { user, isLoading, logout } = useAuth();

  return (
    <header className="border-b border-slate-800 bg-slate-900/80 backdrop-blur">
      <nav className="mx-auto flex max-w-3xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3 text-sm font-medium">
        <Link href="/" className="text-slate-100 hover:text-white">
          Home
        </Link>
        {isLoading ? null : user ? (
          <>
            <span className="text-slate-400" title={user.email}>
              Signed in as <span className="text-slate-200">{user.email}</span>
            </span>
            <button
              type="button"
              onClick={logout}
              className="text-slate-400 hover:text-white"
            >
              Log out
            </button>
          </>
        ) : (
          <>
            <Link href="/login" className={navLinkClass}>
              Sign in
            </Link>
            <Link href="/register" className={navLinkClass}>
              Register
            </Link>
          </>
        )}
        <Link href="/project-status" className={navLinkClass}>
          Project status
        </Link>
      </nav>
    </header>
  );
}
