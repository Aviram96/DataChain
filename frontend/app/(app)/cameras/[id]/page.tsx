"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { CameraRecordings } from "@/components/camera-recordings";
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
  const [liveFailed, setLiveFailed] = useState(false);

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

  useEffect(() => {
    setLiveFailed(false);
  }, [camera?.stream_url]);

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

  const feedKind = liveFeedKind(camera.stream_url);
  const details = [
    camera.location?.trim(),
    `Added ${new Date(camera.created_at).toLocaleString()}`,
  ].filter((part): part is string => Boolean(part));

  return (
    <div className="space-y-8">
      <div>
        <Link href="/cameras" className={ui.backLink}>
          ← Cameras
        </Link>
        <div className="mt-2 flex flex-wrap items-start justify-between gap-4">
          <div className="space-y-2">
            <h1 className={ui.pageTitle}>{camera.name}</h1>
            <p className={ui.pageSubtitle}>{details.join(" · ")}</p>
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

      <section className={ui.panel} aria-labelledby="live-picture-heading">
        <h2 id="live-picture-heading" className={ui.sectionTitle}>
          Live
        </h2>
        <p className={`mt-1 ${ui.muted}`}>What this camera sees right now.</p>
        {feedKind === "mjpeg" && !liveFailed ? (
          <img
            key={camera.stream_url}
            src={camera.stream_url}
            alt="Live camera"
            onError={() => setLiveFailed(true)}
            className="mt-3 h-72 w-full rounded-md bg-landing-ink object-contain"
          />
        ) : null}
        {feedKind === "video" && !liveFailed ? (
          <video
            key={camera.stream_url}
            src={camera.stream_url}
            controls
            autoPlay
            muted
            loop
            playsInline
            onError={() => setLiveFailed(true)}
            className="mt-3 h-72 w-full rounded-md bg-landing-ink object-contain"
          />
        ) : null}
        {feedKind && liveFailed ? (
          <p className={`mt-3 ${ui.muted}`}>
            The live picture did not load. Saved clips are still listed below.
          </p>
        ) : null}
        {!feedKind ? (
          <p className={`mt-3 ${ui.muted}`}>
            This stream cannot be shown in the browser. Saved clips are below.
          </p>
        ) : null}
        <p className={`mt-3 break-all ${ui.hint}`}>{camera.stream_url}</p>
      </section>

      <CameraRecordings cameraId={camera.id} />
    </div>
  );
}

function liveFeedKind(url: string): "mjpeg" | "video" | null {
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
      return null;
    }
    if (/\.(mjpg|mjpeg)$/i.test(parsed.pathname)) {
      return "mjpeg";
    }
    if (/\.(mp4|webm|ogg)$/i.test(parsed.pathname)) {
      return "video";
    }
    return null;
  } catch {
    return null;
  }
}
