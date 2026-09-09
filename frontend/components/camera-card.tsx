"use client";

import Link from "next/link";
import { useState } from "react";

import {
  ingestFailedMessage,
  type CameraPublic,
  type CameraStatus,
} from "@/lib/cameras-api";
import { ui } from "@/lib/ui";

type CameraCardProps = {
  camera: CameraPublic;
  onDelete: () => Promise<void>;
};

export function CameraCard({ camera, onDelete }: CameraCardProps) {
  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);

  async function handleConfirmDelete() {
    setDeleting(true);
    try {
      await onDelete();
      setConfirming(false);
    } finally {
      setDeleting(false);
    }
  }

  const ingestFailed = ingestFailedMessage(camera);

  return (
    <article className={ui.panel}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 space-y-2">
          <h2 className="text-lg font-semibold text-landing-ink">
            <Link
              href={`/cameras/${camera.id}`}
              className="transition hover:text-landing-accent"
            >
              {camera.name}
            </Link>
          </h2>
          <StatusBadge status={camera.status} />
          {ingestFailed ? <p className={ui.hint}>{ingestFailed}</p> : null}
        </div>
        <div className="flex shrink-0 flex-wrap justify-end gap-3 text-sm">
          <Link href={`/cameras/${camera.id}`} className={ui.link}>
            Open
          </Link>
          <Link
            href={`/cameras/${camera.id}/edit`}
            className="text-landing-ink/70 transition hover:text-landing-ink"
          >
            Edit
          </Link>
          {!confirming ? (
            <button
              type="button"
              onClick={() => setConfirming(true)}
              className={ui.btnGhostDanger}
            >
              Delete
            </button>
          ) : null}
        </div>
      </div>

      {confirming ? (
        <div className={`mt-3 ${ui.dangerPanel}`}>
          <p>
            Remove{" "}
            <span className="font-semibold text-landing-ink">{camera.name}</span>{" "}
            from your dashboard? Historical recordings stay available for
            evidence.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              disabled={deleting}
              onClick={() => void handleConfirmDelete()}
              className={ui.btnDanger}
            >
              {deleting ? "Removing…" : "Remove"}
            </button>
            <button
              type="button"
              disabled={deleting}
              onClick={() => setConfirming(false)}
              className={ui.btnSecondary}
            >
              Cancel
            </button>
          </div>
        </div>
      ) : null}

      <dl className="mt-4 space-y-2 text-sm">
        <div>
          <dt className={ui.hint}>Stream URL</dt>
          <dd
            className="truncate text-landing-ink/80"
            title={camera.stream_url}
          >
            {camera.stream_url}
          </dd>
        </div>
        {camera.location ? (
          <div>
            <dt className={ui.hint}>Location</dt>
            <dd className="text-landing-ink/80">{camera.location}</dd>
          </div>
        ) : null}
      </dl>
    </article>
  );
}

function StatusBadge({ status }: { status: CameraStatus }) {
  const online = status === "online";
  return (
    <span className={online ? ui.badgeOnline : ui.badgeOffline}>
      <span
        className={`h-1.5 w-1.5 rounded-full ${
          online ? "bg-landing-accent" : "bg-landing-ink/35"
        }`}
        aria-hidden
      />
      {online ? "Online" : "Offline"}
    </span>
  );
}
