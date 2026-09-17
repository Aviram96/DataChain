/** Shared class names aligned with the marketing landing palette. */

export const ui = {
  pageTitle: "font-display text-3xl font-semibold tracking-tight text-landing-ink",
  pageSubtitle: "text-sm text-landing-ink/65",
  sectionTitle: "font-display text-xl font-semibold tracking-tight text-landing-ink",
  label: "block text-sm font-medium text-landing-ink/80",
  hint: "text-xs text-landing-ink/55",
  muted: "text-sm text-landing-ink/65",
  link: "text-landing-accent hover:text-landing-accent-soft",
  backLink: "text-sm text-landing-ink/60 transition hover:text-landing-ink",
  input:
    "w-full rounded-md border border-landing-ink/15 bg-white px-3 py-2.5 text-landing-ink outline-none transition placeholder:text-landing-ink/35 focus:border-landing-accent focus:ring-2 focus:ring-landing-accent/20",
  select:
    "rounded-md border border-landing-ink/15 bg-white px-3 py-2.5 text-sm text-landing-ink outline-none transition focus:border-landing-accent focus:ring-2 focus:ring-landing-accent/20",
  panel:
    "rounded-2xl border border-landing-ink/10 bg-white/80 p-4 shadow-sm backdrop-blur sm:p-5",
  panelMuted:
    "rounded-2xl border border-dashed border-landing-ink/15 bg-white/50 p-6 text-center text-landing-ink/65",
  dangerPanel:
    "rounded-xl border border-landing-warn/30 bg-landing-warn/10 p-3 text-sm text-landing-ink",
  btnPrimary:
    "inline-flex min-h-10 items-center justify-center rounded-md bg-landing-accent px-4 py-2 text-sm font-semibold text-white transition hover:bg-landing-accent-soft disabled:cursor-not-allowed disabled:opacity-60",
  btnSecondary:
    "inline-flex min-h-10 items-center justify-center rounded-md border border-landing-ink/20 bg-white/80 px-4 py-2 text-sm font-semibold text-landing-ink transition hover:border-landing-ink/35 hover:bg-white disabled:cursor-not-allowed disabled:opacity-60",
  btnCompact:
    "inline-flex min-h-9 items-center justify-center rounded-md border border-landing-ink/20 bg-white/80 px-3 py-1.5 text-xs font-semibold text-landing-ink transition hover:border-landing-ink/35 hover:bg-white disabled:cursor-not-allowed disabled:opacity-60",
  btnDanger:
    "inline-flex min-h-10 items-center justify-center rounded-md bg-landing-warn px-4 py-2 text-sm font-semibold text-white transition hover:bg-[#a84c1f] disabled:cursor-not-allowed disabled:opacity-60",
  btnGhostDanger:
    "text-sm font-medium text-landing-warn transition hover:text-[#a84c1f]",
  badgeOnline:
    "inline-flex items-center gap-1.5 rounded-md bg-landing-accent/10 px-2 py-0.5 text-xs font-medium text-landing-accent ring-1 ring-landing-accent/25",
  badgeOffline:
    "inline-flex items-center gap-1.5 rounded-md bg-landing-ink/5 px-2 py-0.5 text-xs font-medium text-landing-ink/55 ring-1 ring-landing-ink/10",
  badgeVerified:
    "inline-flex items-center gap-1.5 rounded-md bg-landing-accent/10 px-2 py-0.5 text-xs font-medium text-landing-accent ring-1 ring-landing-accent/25",
  badgeTampered:
    "inline-flex items-center gap-1.5 rounded-md bg-landing-warn/10 px-2 py-0.5 text-xs font-medium text-landing-warn ring-1 ring-landing-warn/30",
  badgeMissing:
    "inline-flex items-center gap-1.5 rounded-md bg-landing-ink/5 px-2 py-0.5 text-xs font-medium text-landing-ink/60 ring-1 ring-landing-ink/15",
  badgeFailedVerify:
    "inline-flex items-center gap-1.5 rounded-md bg-landing-ink/10 px-2 py-0.5 text-xs font-medium text-landing-ink/70 ring-1 ring-landing-ink/20",
} as const;
