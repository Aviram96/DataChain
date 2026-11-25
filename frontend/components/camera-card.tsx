"use client";

import Link from "next/link";
import { useState } from "react";

import {
  ingestFailedMessage,
  type CameraPublic,
  type CameraStatus,
} from "@/lib/cameras-api";
import { cameraEditHref } from "@/lib/edit-return";
import { ui } from "@/lib/ui";

type CameraCardProps = {
  camera: CameraPublic;
  onArchive: () => Promise<void>;
};

export function CameraCard({ camera, onArchive }: CameraCardProps) {
  const [confirming, setConfirming] = useState(false);
  const [archiving, setArchiving] = useState(false);

  async function handleConfirmArchive() {
    setArchiving(true);
    try {
      await onArchive();
      setConfirming(false);
    } finally {
      setArchiving(false);
    }
  }

  const ingestFailed = ingestFailedMessage(camera);

  return (
    <article className={`${ui.panel} flex h-full flex-col`}>
      <h2 className="break-words text-lg font-semibold text-landing-ink">
        <Link
          href={`/cameras/${camera.id}`}
          className="transition hover:text-landing-accent"
        >
          {camera.name}
        </Link>
      </h2>
      <StatusBadge status={camera.status} />
      {ingestFailed ? (
        <p className={`mt-2 ${ui.hint}`}>{ingestFailed}</p>
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
            <dd className="break-words text-landing-ink/80">
              {camera.location}
            </dd>
          </div>
        ) : null}
      </dl>

      <div className="mt-4 flex flex-1 flex-col justify-end gap-3">
        {confirming ? (
          <div className={ui.dangerPanel}>
            <p>
              Archive{" "}
              <span className="font-semibold text-landing-ink">
                {camera.name}
              </span>
              ? New recording stops. Existing recordings stay on this camera,
              and you can restore it later.
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              <button
                type="button"
                disabled={archiving}
                onClick={() => void handleConfirmArchive()}
                className={ui.btnDanger}
              >
                {archiving ? "Archiving…" : "Archive"}
              </button>
              <button
                type="button"
                disabled={archiving}
                onClick={() => setConfirming(false)}
                className={ui.btnSecondary}
              >
                Cancel
              </button>
            </div>
          </div>
        ) : null}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
          <Link href={`/cameras/${camera.id}`} className={ui.link}>
            Open
          </Link>
          <Link
            href={cameraEditHref(camera.id, "list")}
            className="text-landing-ink/70 transition hover:text-landing-ink"
          >
            Edit
          </Link>
          {!confirming ? (
            <button
              type="button"
              onClick={() => setConfirming(true)}
              className={`inline-flex items-center gap-1.5 ${ui.btnGhostDanger}`}
            >
              <ArchiveIcon />
              Archive
            </button>
          ) : null}
        </div>
      </div>
    </article>
  );
}

function ArchiveIcon() {
  return (
    <svg
      viewBox="0 0 16 16"
      aria-hidden="true"
      className="h-3.5 w-3.5 shrink-0 stroke-current"
      fill="none"
    >
      <path d="M2.5 3.2h11v2.2h-11z" strokeWidth="1.4" strokeLinejoin="round" />
      <path d="M3.4 5.4h9.2V13H3.4z" strokeWidth="1.4" strokeLinejoin="round" />
      <path d="M6.4 8.2h3.2" strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  );
}

function StatusBadge({ status }: { status: CameraStatus }) {
  const online = status === "online";
  return (
    <span className={`mt-2 w-fit ${online ? ui.badgeOnline : ui.badgeOffline}`}>
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
