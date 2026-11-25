"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { CameraRecordings } from "@/components/camera-recordings";
import { RequireAuth } from "@/components/require-auth";
import { useToast } from "@/components/toast-provider";
import { networkErrorMessage } from "@/lib/api";
import { cameraEditHref } from "@/lib/edit-return";
import {
  CamerasApiError,
  archiveCamera,
  getCamera,
  ingestFailedMessage,
  restoreCamera,
  type CameraPublic,
} from "@/lib/cameras-api";
import { isArchivedCamera, restoreFailureMessage } from "@/lib/camera-archive";
import { ui } from "@/lib/ui";

export default function CameraDetailPage() {
  return (
    <RequireAuth>
      <CameraDetailContent />
    </RequireAuth>
  );
}

function CameraDetailContent() {
  const params = useParams();
  const router = useRouter();
  const { showToast } = useToast();
  const cameraId = String(params.id ?? "");

  const [camera, setCamera] = useState<CameraPublic | null>(null);
  const [loading, setLoading] = useState(true);
  const [confirmingArchive, setConfirmingArchive] = useState(false);
  const [archiving, setArchiving] = useState(false);
  const [confirmingRestore, setConfirmingRestore] = useState(false);
  const [restoring, setRestoring] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getCamera(cameraId);
      setCamera(data);
    } catch (error) {
      if (error instanceof CamerasApiError) {
        showToast(error.message, "error");
      } else {
        showToast(networkErrorMessage(), "error");
      }
      setCamera(null);
    } finally {
      setLoading(false);
    }
  }, [cameraId, showToast]);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleArchive() {
    setArchiving(true);
    try {
      await archiveCamera(cameraId);
      showToast("Camera archived. New recording has stopped.", "success");
      router.push("/cameras");
    } catch (error) {
      if (error instanceof CamerasApiError) {
        showToast(error.message, "error");
      } else {
        showToast(networkErrorMessage(), "error");
      }
    } finally {
      setArchiving(false);
    }
  }

  async function handleRestore() {
    setRestoring(true);
    try {
      const restored = await restoreCamera(cameraId);
      setCamera(restored);
      setConfirmingRestore(false);
      showToast(
        "Camera restored successfully. Recording will start automatically when the stream is available.",
        "success"
      );
    } catch (error) {
      if (error instanceof CamerasApiError) {
        showToast(restoreFailureMessage(error), "error");
      } else {
        showToast(networkErrorMessage(), "error");
      }
    } finally {
      setRestoring(false);
    }
  }

  if (loading) {
    return <p className={ui.muted}>Loading camera…</p>;
  }

  if (!camera) {
    return (
      <div className="space-y-4">
        <Link href="/cameras" className={ui.backLink}>
          ← Cameras
        </Link>
        <p className={ui.muted}>Camera not found.</p>
      </div>
    );
  }

  const archived = isArchivedCamera(camera);
  const online = camera.status === "online";
  const ingestFailed = ingestFailedMessage(camera);

  const details = [
    camera.location?.trim(),
    archived && camera.archived_at
      ? `Archived ${new Date(camera.archived_at).toLocaleString()}`
      : null,
    `Added ${new Date(camera.created_at).toLocaleString()}`,
  ].filter((part): part is string => Boolean(part));

  return (
    <div className="space-y-8">
      <div>
        <Link
          href={archived ? "/cameras/archived" : "/cameras"}
          className={ui.backLink}
        >
          {archived ? "← Archived cameras" : "← Cameras"}
        </Link>
        <div className="mt-2 flex flex-wrap items-start justify-between gap-4">
          <div className="space-y-2">
            <h1 className={ui.pageTitle}>{camera.name}</h1>
            <p className={ui.pageSubtitle}>{details.join(" · ")}</p>
            {archived ? (
              <span className={ui.badgeOffline}>Archived</span>
            ) : (
              <span className={online ? ui.badgeOnline : ui.badgeOffline}>
                {online ? "Online" : "Offline"}
              </span>
            )}
            {ingestFailed ? <p className={ui.muted}>{ingestFailed}</p> : null}
          </div>
          {archived ? (
            <div className="flex flex-wrap gap-3">
              {!confirmingRestore ? (
                <button
                  type="button"
                  onClick={() => setConfirmingRestore(true)}
                  className={ui.btnSecondary}
                >
                  Restore
                </button>
              ) : null}
            </div>
          ) : (
            <div className="flex flex-wrap gap-3">
              <Link
                href={cameraEditHref(camera.id, "details")}
                className="inline-flex items-center gap-1.5 rounded-sm bg-transparent text-sm font-medium text-landing-ink/80 transition hover:text-landing-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-landing-ink/40"
              >
                <PencilIcon />
                Edit
              </Link>
              {!confirmingArchive ? (
                <button
                  type="button"
                  onClick={() => setConfirmingArchive(true)}
                  className={`inline-flex items-center gap-1.5 ${ui.btnGhostDanger}`}
                >
                  <ArchiveIcon />
                  Archive
                </button>
              ) : null}
            </div>
          )}
        </div>
      </div>

      {confirmingArchive ? (
        <div className={ui.dangerPanel}>
          <p>
            Archive this camera? New recording stops. Existing recordings stay
            available, and you can restore the camera later.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              disabled={archiving}
              onClick={() => void handleArchive()}
              className={ui.btnDanger}
            >
              {archiving ? "Archiving…" : "Archive"}
            </button>
            <button
              type="button"
              disabled={archiving}
              onClick={() => setConfirmingArchive(false)}
              className={ui.btnSecondary}
            >
              Cancel
            </button>
          </div>
        </div>
      ) : null}

      {confirmingRestore ? (
        <div className={ui.panel}>
          <p className="text-sm text-landing-ink">
            Restore this camera to your active list? It keeps the same
            recordings. Recording will start automatically when the stream is
            available.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              disabled={restoring}
              onClick={() => void handleRestore()}
              className={ui.btnPrimary}
            >
              {restoring ? "Restoring…" : "Restore"}
            </button>
            <button
              type="button"
              disabled={restoring}
              onClick={() => setConfirmingRestore(false)}
              className={ui.btnSecondary}
            >
              Cancel
            </button>
          </div>
        </div>
      ) : null}

      <CameraRecordings cameraId={camera.id} />
    </div>
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

function PencilIcon() {
  return (
    <svg
      viewBox="0 0 16 16"
      aria-hidden="true"
      className="h-3.5 w-3.5 shrink-0 stroke-current"
      fill="none"
    >
      <path
        d="M9.2 3.1 12.9 6.8 5.6 14.1H2v-3.6L9.2 3.1z"
        strokeWidth="1.4"
        strokeLinejoin="round"
      />
      <path d="M8 4.3 11.7 8" strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  );
}
