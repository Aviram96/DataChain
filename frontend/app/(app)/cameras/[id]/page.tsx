"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { RequireAuth } from "@/components/require-auth";
import { useToast } from "@/components/toast-provider";
import { networkErrorMessage } from "@/lib/api";
import {
  CamerasApiError,
  deleteCamera,
  getCamera,
  ingestFailedMessage,
  type CameraPublic,
} from "@/lib/cameras-api";
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
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);

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

  async function handleDelete() {
    setDeleting(true);
    try {
      await deleteCamera(cameraId);
      showToast("Camera removed from your dashboard.", "success");
      router.push("/cameras");
    } catch (error) {
      if (error instanceof CamerasApiError) {
        showToast(error.message, "error");
      } else {
        showToast(networkErrorMessage(), "error");
      }
    } finally {
      setDeleting(false);
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

  const online = camera.status === "online";
  const ingestFailed = ingestFailedMessage(camera);

  return (
    <div className="space-y-6">
      <div>
        <Link href="/cameras" className={ui.backLink}>
          ← Cameras
        </Link>
        <div className="mt-2 flex flex-wrap items-start justify-between gap-4">
          <div className="space-y-2">
            <h1 className={ui.pageTitle}>{camera.name}</h1>
            <span className={online ? ui.badgeOnline : ui.badgeOffline}>
              {online ? "Online" : "Offline"}
            </span>
            {ingestFailed ? <p className={ui.muted}>{ingestFailed}</p> : null}
          </div>
          <div className="flex flex-wrap gap-3">
            <Link href={`/cameras/${camera.id}/edit`} className={ui.btnSecondary}>
              Edit
            </Link>
            {!confirmingDelete ? (
              <button
                type="button"
                onClick={() => setConfirmingDelete(true)}
                className={ui.btnGhostDanger}
              >
                Delete
              </button>
            ) : null}
          </div>
        </div>
      </div>

      {confirmingDelete ? (
        <div className={ui.dangerPanel}>
          <p>
            Remove this camera from your dashboard? Historical recordings stay
            available for evidence.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              disabled={deleting}
              onClick={() => void handleDelete()}
              className={ui.btnDanger}
            >
              {deleting ? "Removing…" : "Remove"}
            </button>
            <button
              type="button"
              disabled={deleting}
              onClick={() => setConfirmingDelete(false)}
              className={ui.btnSecondary}
            >
              Cancel
            </button>
          </div>
        </div>
      ) : null}

      <dl className={`space-y-3 text-sm ${ui.panel}`}>
        <div>
          <dt className={ui.hint}>Stream URL</dt>
          <dd className="break-all text-landing-ink/85">{camera.stream_url}</dd>
        </div>
        <div>
          <dt className={ui.hint}>Location</dt>
          <dd className="text-landing-ink/85">{camera.location || "—"}</dd>
        </div>
        <div>
          <dt className={ui.hint}>Added</dt>
          <dd className="text-landing-ink/85">
            {new Date(camera.created_at).toLocaleString()}
          </dd>
        </div>
      </dl>

      <section className={ui.panelMuted}>
        <h2 className={`${ui.sectionTitle} text-left`}>Recordings</h2>
        <p className={`mt-2 text-left ${ui.muted}`}>
          Search, watch, download, and verify videos for this camera will appear
          here (Slice E — Video management).
        </p>
      </section>
    </div>
  );
}
