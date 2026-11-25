"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useAuth } from "./auth-provider";

const primaryCtaClass =
  "inline-flex min-h-11 items-center justify-center rounded-md bg-landing-accent px-6 py-3 text-sm font-semibold text-white transition hover:bg-landing-accent-soft focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-landing-accent";
const secondaryCtaClass =
  "inline-flex min-h-11 items-center justify-center rounded-md border border-landing-ink/20 bg-white/70 px-6 py-3 text-sm font-semibold text-landing-ink backdrop-blur transition hover:border-landing-ink/40 hover:bg-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-landing-ink";

export function LandingPage() {
  const router = useRouter();
  const { user, isLoading } = useAuth();

  useEffect(() => {
    if (!isLoading && user) {
      router.replace("/cameras");
    }
  }, [isLoading, user, router]);

  if (isLoading || user) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-landing-ink text-landing-mist">
        <p className="text-sm" aria-live="polite">
          {user ? "Opening your cameras…" : "Loading…"}
        </p>
      </div>
    );
  }

  return (
    <div className="bg-landing-fog text-landing-ink">
      <section className="relative isolate min-h-[100svh] overflow-hidden">
        <div
          aria-hidden
          className="landing-atmosphere pointer-events-none absolute inset-0 -z-10 bg-[radial-gradient(120%_80%_at_10%_0%,#d7e4d9_0%,transparent_55%),radial-gradient(90%_70%_at_90%_20%,#c5d4c8_0%,transparent_50%),linear-gradient(165deg,#eef3ef_0%,#d5e0d7_45%,#b9c8bc_100%)]"
        />
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 -z-10 opacity-[0.35] [background-image:linear-gradient(rgba(12,18,16,0.06)_1px,transparent_1px),linear-gradient(90deg,rgba(12,18,16,0.06)_1px,transparent_1px)] [background-size:48px_48px]"
        />

        <div className="mx-auto grid min-h-[100svh] max-w-6xl gap-10 px-4 py-12 sm:px-6 lg:grid-cols-[minmax(0,1.05fr)_minmax(0,0.95fr)] lg:items-center lg:gap-14 lg:px-8 lg:py-16">
          <div className="space-y-8">
            <p className="landing-rise font-display text-5xl font-semibold tracking-tight text-landing-ink sm:text-6xl md:text-7xl">
              Datachain
            </p>
            <div className="landing-rise landing-rise-delay-1 space-y-4">
              <h1 className="max-w-xl text-2xl font-semibold leading-snug tracking-tight text-landing-ink sm:text-3xl">
                CCTV you can trust when it matters.
              </h1>
              <p className="max-w-lg text-base leading-relaxed text-landing-ink/75 sm:text-lg">
                Decentralized, tamper-evident video management for cameras that
                must keep their integrity.
              </p>
            </div>
            <div className="landing-rise landing-rise-delay-2 flex flex-col gap-3 sm:flex-row sm:flex-wrap">
              <Link href="/register" className={primaryCtaClass}>
                Sign up
              </Link>
              <Link href="/login" className={secondaryCtaClass}>
                Log in
              </Link>
            </div>
          </div>

          <div
            aria-hidden
            className="landing-rise landing-rise-delay-3 relative mx-auto aspect-[4/5] w-full max-w-md lg:max-w-none"
          >
            <div className="absolute inset-0 rounded-[2rem] bg-landing-ink/90 shadow-[0_40px_80px_-40px_rgba(12,18,16,0.55)]" />
            <div className="absolute inset-3 overflow-hidden rounded-[1.6rem] border border-white/10 bg-[linear-gradient(160deg,#15201b_0%,#0c1210_55%,#1a2a22_100%)]">
              <div className="absolute inset-x-0 top-0 h-14 border-b border-white/10 bg-black/20 px-4 py-3">
                <div className="flex items-center justify-between text-[11px] uppercase tracking-[0.2em] text-landing-mist/80">
                  <span>Cam 01 · Lobby</span>
                  <span className="text-landing-accent-soft">Live</span>
                </div>
              </div>
              <div className="absolute inset-x-6 top-24 bottom-20 rounded-lg border border-dashed border-white/15 bg-[repeating-linear-gradient(90deg,transparent,transparent_18px,rgba(47,154,99,0.08)_18px,rgba(47,154,99,0.08)_19px),repeating-linear-gradient(0deg,transparent,transparent_18px,rgba(255,255,255,0.04)_18px,rgba(255,255,255,0.04)_19px)]" />
              <div className="absolute inset-x-6 bottom-6 space-y-2">
                <div className="h-2 w-[75%] rounded-full bg-landing-accent/70" />
                <div className="h-2 w-1/2 rounded-full bg-white/20" />
                <p className="pt-2 text-xs text-landing-mist/70">
                  CID anchored · chain-verified segment
                </p>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="border-t border-landing-ink/10 bg-white px-4 py-16 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-3xl space-y-4">
          <h2 className="font-display text-3xl font-semibold tracking-tight text-landing-ink sm:text-4xl">
            The problem
          </h2>
          <p className="text-base leading-relaxed text-landing-ink/75 sm:text-lg">
            Centralized CCTV storage can be quietly edited, deleted, or
            overwritten. When footage loses its integrity, it loses its value as
            evidence — and you may not notice until it is too late.
          </p>
        </div>
      </section>

      <section className="border-t border-landing-ink/10 bg-landing-fog px-4 py-16 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-3xl space-y-4">
          <h2 className="font-display text-3xl font-semibold tracking-tight text-landing-ink sm:text-4xl">
            The solution
          </h2>
          <p className="text-base leading-relaxed text-landing-ink/75 sm:text-lg">
            Datachain keeps video segments on decentralized storage (IPFS),
            anchors their cryptographic identifiers on the blockchain, and lets
            you manage cameras and verify recordings from one place. Any change
            to a segment changes its hash — and the mismatch becomes visible.
          </p>
          <div className="flex flex-col gap-3 pt-4 sm:flex-row">
            <Link href="/register" className={primaryCtaClass}>
              Sign up
            </Link>
            <Link href="/login" className={secondaryCtaClass}>
              Log in
            </Link>
          </div>
        </div>
      </section>
    </div>
  );
}
