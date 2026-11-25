"use client";

import Link from "next/link";
import { useEffect, useId, useRef, useState } from "react";

import { useAuth } from "./auth-provider";

const navLinkClass =
  "whitespace-nowrap text-landing-ink/65 transition hover:text-landing-ink";

export function SiteHeader() {
  const { user, isLoading, logout } = useAuth();

  return (
    <header className="border-b border-landing-ink/10 bg-white/70 backdrop-blur-md">
      <nav className="mx-auto flex max-w-3xl flex-wrap items-center gap-x-5 gap-y-2 px-4 py-3.5 text-sm font-medium sm:px-6">
        <span className="font-display text-base font-semibold tracking-tight text-landing-ink">
          DataChain
        </span>
        {isLoading ? null : user ? (
          <>
            <Link href="/cameras" className={navLinkClass}>
              Cameras
            </Link>
            <Link href="/cameras/archived" className={navLinkClass}>
              Archive
            </Link>
            <Link href="/cameras/new" className={navLinkClass}>
              Add camera
            </Link>
            <AccountMenu email={user.email} onLogout={logout} />
          </>
        ) : (
          <>
            <Link href="/login" className={navLinkClass}>
              Log in
            </Link>
            <Link
              href="/register"
              className="whitespace-nowrap rounded-md bg-landing-accent px-3 py-1.5 font-semibold text-white transition hover:bg-landing-accent-soft"
            >
              Sign up
            </Link>
          </>
        )}
      </nav>
    </header>
  );
}

function AccountMenu({
  email,
  onLogout,
}: {
  email: string;
  onLogout: () => void;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const logoutRef = useRef<HTMLButtonElement>(null);
  const focusLogoutOnOpen = useRef(false);
  const menuId = useId();

  useEffect(() => {
    if (!open) {
      return;
    }

    const frame = window.requestAnimationFrame(() => {
      if (focusLogoutOnOpen.current) {
        focusLogoutOnOpen.current = false;
        logoutRef.current?.focus();
      }
    });

    function onPointerDown(event: PointerEvent) {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    }

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        setOpen(false);
        buttonRef.current?.focus();
      }
    }

    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      window.cancelAnimationFrame(frame);
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  return (
    <div ref={rootRef} className="relative">
      <button
        ref={buttonRef}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={menuId}
        aria-label="Account menu"
        onClick={() => setOpen((current) => !current)}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown" && !open) {
            event.preventDefault();
            focusLogoutOnOpen.current = true;
            setOpen(true);
          }
        }}
        className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-landing-ink/20 text-landing-ink/70 transition hover:border-landing-ink/35 hover:text-landing-ink"
      >
        <UserIcon />
      </button>
      {open ? (
        <div
          id={menuId}
          role="menu"
          aria-label="Account"
          className="absolute left-0 z-30 mt-2 w-max max-w-[min(18rem,calc(100vw-2rem))] rounded-xl border border-landing-ink/10 bg-white p-2 shadow-sm"
        >
          <p className="break-all px-2 py-1.5 text-sm font-medium text-landing-ink">
            {email}
          </p>
          <button
            ref={logoutRef}
            type="button"
            role="menuitem"
            onClick={onLogout}
            className="block w-full rounded-md px-2 py-1.5 text-left text-landing-ink/65 transition hover:bg-landing-ink/5 hover:text-landing-ink"
          >
            Log out
          </button>
        </div>
      ) : null}
    </div>
  );
}

function UserIcon() {
  return (
    <svg
      viewBox="0 0 16 16"
      aria-hidden="true"
      className="h-4 w-4 stroke-current"
      fill="none"
    >
      <circle cx="8" cy="5.5" r="2.2" strokeWidth="1.4" />
      <path
        d="M3.4 13.1c.7-2.1 2.3-3.1 4.6-3.1s3.9 1 4.6 3.1"
        strokeWidth="1.4"
        strokeLinecap="round"
      />
    </svg>
  );
}
