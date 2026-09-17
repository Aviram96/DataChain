import { ui } from "@/lib/ui";
import { polygonscanTxUrl } from "@/lib/verify-config";
import {
  countByStatus,
  verifyStatusLabel,
  type VerifyReport,
  type VerifyStatus,
} from "@/lib/verify-recordings";

type RecordingVerifyPanelProps = {
  report: VerifyReport;
};

export function RecordingVerifyPanel({ report }: RecordingVerifyPanelProps) {
  const counts = countByStatus(report.results);

  return (
    <div className={ui.panel}>
      <div className="flex flex-wrap items-center gap-2">
        <h3 className={ui.sectionTitle}>Verification result</h3>
        <VerifyBadge status={report.overall} />
      </div>
      <p className={`mt-2 ${ui.muted}`}>{overallCopy(report.overall)}</p>
      {report.scope === "partial" ? (
        <p className={`mt-1 ${ui.hint}`}>
          Only the chosen part of the selected range was checked.
        </p>
      ) : null}
      <p className={`mt-1 ${ui.hint}`}>
        {report.results.length} minute
        {report.results.length === 1 ? "" : "s"} checked
        {summaryCounts(counts)}
      </p>
      <ul className="mt-4 space-y-2">
        {report.results.map((result) => {
          const txUrl = result.record?.tx_hash
            ? polygonscanTxUrl(result.record.tx_hash)
            : null;
          return (
            <li
              key={`${result.slotIso}-${result.record?.id ?? "gap"}`}
              className="rounded-xl border border-landing-ink/10 bg-white/70 p-3"
            >
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0 space-y-1">
                  <p className="text-sm font-medium text-landing-ink">
                    {formatSlot(result.slotIso, result.record?.ended_at)}
                  </p>
                  <p className={ui.hint}>{result.detail}</p>
                </div>
                <VerifyBadge status={result.status} />
              </div>
              {txUrl ? (
                <a
                  href={txUrl}
                  target="_blank"
                  rel="noreferrer"
                  className={`mt-2 inline-block ${ui.link} text-xs`}
                >
                  View on Polygonscan
                </a>
              ) : null}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export function VerifyBadge({ status }: { status: VerifyStatus }) {
  return <span className={badgeClass(status)}>{verifyStatusLabel(status)}</span>;
}

function badgeClass(status: VerifyStatus): string {
  switch (status) {
    case "verified":
      return ui.badgeVerified;
    case "tampered":
      return ui.badgeTampered;
    case "missing":
      return ui.badgeMissing;
    case "failed_to_verify":
      return ui.badgeFailedVerify;
  }
}

function overallCopy(status: VerifyStatus): string {
  switch (status) {
    case "verified":
      return "This range is authentic: every expected minute matches the blockchain proof.";
    case "tampered":
      return "At least one minute does not match the blockchain proof.";
    case "missing":
      return "Some expected minutes have no recording in the app.";
    case "failed_to_verify":
      return "Some minutes could not be checked (RPC). That is not a tamper result.";
  }
}

function summaryCounts(counts: Record<VerifyStatus, number>): string {
  const parts = (
    [
      ["verified", "Verified"],
      ["tampered", "Tampered"],
      ["missing", "Missing"],
      ["failed_to_verify", "Failed to verify"],
    ] as const
  )
    .filter(([key]) => counts[key] > 0)
    .map(([key, label]) => `${counts[key]} ${label}`);
  return parts.length ? ` — ${parts.join(", ")}` : "";
}

function formatSlot(startedAt: string, endedAt?: string): string {
  const start = new Date(startedAt);
  if (!endedAt) {
    return start.toLocaleString();
  }
  const end = new Date(endedAt);
  return `${start.toLocaleString()} – ${end.toLocaleTimeString()}`;
}
