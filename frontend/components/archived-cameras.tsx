"use client";

import Link from "next/link";
import { useCallback, useEffect, useId, useRef, useState } from "react";

import { networkErrorMessage } from "@/lib/api";
import {
  CamerasApiError,
  listArchivedCameras,
  permanentlyDeleteCamera,
  restoreCamera,
  type CameraPublic,
} from "@/lib/cameras-api";
import { restoreFailureMessage } from "@/lib/camera-archive";
import { submitPermanentDelete } from "@/lib/permanent-delete";
import { ui } from "@/lib/ui";

import { useToast } from "./toast-provider";

const PAGE_SIZE = 10;

export function ArchivedCameras() {
  const { showToast } = useToast();
  const [cameras, setCameras] = useState<CameraPublic[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pages, setPages] = useState(1);
  const [loading, setLoading] = useState(true);

  const loadCameras = useCallback(
    async (pageToLoad: number) => {
      setLoading(true);
      try {
        const data = await listArchivedCameras({
          page: pageToLoad,
          pageSize: PAGE_SIZE,
        });
        setCameras(data.items);
        setTotal(data.total);
        setPage(data.page);
        setPages(data.pages);
      } catch (error) {
        if (error instanceof CamerasApiError) {
          showToast(error.message, "error");
        } else {
          showToast(networkErrorMessage(), "error");
        }
      } finally {
        setLoading(false);
      }
    },
    [showToast]
  );

  useEffect(() => {
    void loadCameras(page);
  }, [loadCameras, page]);

  const handleDeleted = useCallback(
    (id: string) => {
      setCameras((current) => {
        const next = current.filter((camera) => camera.id !== id);
        if (next.length === 0 && page > 1) {
          setPage((currentPage) => currentPage - 1);
        }
        return next;
      });
      setTotal((current) => {
        const next = Math.max(0, current - 1);
        setPages(Math.max(1, Math.ceil(next / PAGE_SIZE)));
        return next;
      });
    },
    [page]
  );

  const handleRestore = useCallback(
    async (id: string) => {
      try {
        await restoreCamera(id);
        showToast(
          "Camera restored successfully. Recording will start automatically when the stream is available.",
          "success"
        );
        if (cameras.length === 1 && page > 1) {
          setPage((current) => current - 1);
        } else {
          await loadCameras(page);
        }
      } catch (error) {
        if (error instanceof CamerasApiError) {
          showToast(restoreFailureMessage(error), "error");
        } else {
          showToast(networkErrorMessage(), "error");
        }
        throw error;
      }
    },
    [cameras.length, loadCameras, page, showToast]
  );

  return (
    <div className="space-y-6">
      <div>
        <Link href="/cameras" className={ui.backLink}>
          ← Cameras
        </Link>
        <h1 className={`mt-2 ${ui.pageTitle}`}>Archived cameras</h1>
        <p className={`mt-1 ${ui.pageSubtitle}`}>
          {loading
            ? "Loading…"
            : total === 0
              ? "No archived cameras."
              : `${total} archived camera${total === 1 ? "" : "s"}`}
        </p>
        <p className={`mt-2 ${ui.muted}`}>
          Restoring a camera puts it back on your active list. Recording will
          start automatically when the stream is available.
        </p>
      </div>

      {loading ? (
        <p className={ui.muted}>Loading archived cameras…</p>
      ) : cameras.length === 0 ? (
        <p className={ui.panelMuted}>No archived cameras.</p>
      ) : (
        <div className="grid items-stretch gap-4 sm:grid-cols-2">
          {cameras.map((camera) => (
            <ArchivedCameraCard
              key={camera.id}
              camera={camera}
              onRestore={() => handleRestore(camera.id)}
              onDeleted={handleDeleted}
            />
          ))}
        </div>
      )}

      {pages > 1 && total > 0 ? (
        <div className="flex flex-wrap items-center justify-between gap-4 border-t border-landing-ink/10 pt-4">
          <p className={ui.hint}>
            Showing {(page - 1) * PAGE_SIZE + 1}–
            {Math.min(page * PAGE_SIZE, total)} of {total} cameras
          </p>
          <div className="flex items-center gap-3">
            <button
              type="button"
              disabled={page <= 1 || loading}
              onClick={() => setPage((current) => current - 1)}
              className={ui.btnSecondary}
            >
              Previous
            </button>
            <span className={ui.muted}>
              Page {page} of {pages}
            </span>
            <button
              type="button"
              disabled={page >= pages || loading}
              onClick={() => setPage((current) => current + 1)}
              className={ui.btnSecondary}
            >
              Next
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function ArchivedCameraCard({
  camera,
  onRestore,
  onDeleted,
}: {
  camera: CameraPublic;
  onRestore: () => Promise<void>;
  onDeleted: (id: string) => void;
}) {
  const { showToast } = useToast();
  const [confirming, setConfirming] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const deleteLock = useRef(false);
  const archivedAt = camera.archived_at
    ? new Date(camera.archived_at).toLocaleString()
    : "Unknown date";

  async function handleConfirmRestore() {
    setRestoring(true);
    try {
      await onRestore();
      setConfirming(false);
    } finally {
      setRestoring(false);
    }
  }

  function openDelete() {
    setConfirming(false);
    setDeleteOpen(true);
  }

  function closeDelete() {
    if (deleting || deleteLock.current) {
      return;
    }
    setDeleteOpen(false);
  }

  async function handleConfirmDelete() {
    setDeleting(true);
    try {
      const outcome = await submitPermanentDelete({
        cameraName: camera.name,
        lock: deleteLock,
        send: (confirmName) => permanentlyDeleteCamera(camera.id, confirmName),
      });
      if (outcome.status === "deleted") {
        showToast(outcome.message, "success");
        setDeleteOpen(false);
        onDeleted(camera.id);
      } else if (outcome.status === "failed") {
        showToast(outcome.message, "error");
      }
    } finally {
      setDeleting(false);
    }
  }

  return (
    <article className={`${ui.panel} flex h-full flex-col`}>
      <h2 className="break-words text-lg font-semibold text-landing-ink">
        {camera.name}
      </h2>
      <span className={`mt-2 w-fit ${ui.badgeOffline}`}>Archived</span>

      <dl className="mt-4 space-y-2 text-sm">
        <div>
          <dt className={ui.hint}>Location</dt>
          <dd className="break-words text-landing-ink/80">
            {camera.location?.trim() || "No location"}
          </dd>
        </div>
        <div>
          <dt className={ui.hint}>Archived</dt>
          <dd className="text-landing-ink/80">{archivedAt}</dd>
        </div>
      </dl>

      <div className="mt-4 flex flex-1 flex-col justify-end gap-3">
        {confirming ? (
          <div className={ui.panel}>
            <p className="text-sm text-landing-ink">
              Restore <span className="font-semibold">{camera.name}</span>? It
              returns to your active cameras with the same recordings. Recording
              will start automatically when the stream is available.
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              <button
                type="button"
                disabled={restoring}
                onClick={() => void handleConfirmRestore()}
                className={ui.btnPrimary}
              >
                {restoring ? "Restoring…" : "Restore"}
              </button>
              <button
                type="button"
                disabled={restoring}
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
            View recordings
          </Link>
          {!confirming ? (
            <button
              type="button"
              onClick={() => setConfirming(true)}
              className="text-sm font-medium text-landing-ink/80 transition hover:text-landing-ink"
            >
              Restore
            </button>
          ) : null}
          <button
            type="button"
            onClick={openDelete}
            className={`${ui.btnGhostDanger} inline-flex items-center gap-1`}
          >
            <TrashIcon />
            Delete
          </button>
        </div>
      </div>
      {deleteOpen ? (
        <PermanentDeleteDialog
          cameraName={camera.name}
          deleting={deleting || deleteLock.current}
          onCancel={closeDelete}
          onConfirm={() => void handleConfirmDelete()}
        />
      ) : null}
    </article>
  );
}

function PermanentDeleteDialog({
  cameraName,
  deleting,
  onCancel,
  onConfirm,
}: {
  cameraName: string;
  deleting: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const titleId = useId();

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onCancel();
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onCancel]);

  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center overflow-y-auto bg-landing-ink/40 p-4"
      onClick={onCancel}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onClick={(event) => event.stopPropagation()}
        className={`${ui.panel} relative z-10 max-h-[calc(100dvh-2rem)] w-full max-w-md overflow-y-auto`}
      >
        <h2 id={titleId} className="text-lg font-semibold text-landing-ink">
          Delete permanently
        </h2>
        <p className={`mt-3 ${ui.dangerPanel}`}>
          Delete <span className="font-semibold">{cameraName}</span>{" "}
          permanently? This cannot be undone.
        </p>
        <div className="mt-4 flex flex-wrap justify-end gap-2">
          <button
            type="button"
            disabled={deleting}
            onClick={onCancel}
            className={ui.btnSecondary}
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={deleting}
            onClick={onConfirm}
            className={ui.btnDanger}
          >
            {deleting ? "Deleting…" : "Delete"}
          </button>
        </div>
      </div>
    </div>
  );
}

function TrashIcon() {
  return (
    <svg
      viewBox="0 0 16 16"
      aria-hidden="true"
      className="h-3.5 w-3.5 shrink-0 stroke-current"
      fill="none"
    >
      <path d="M3.2 4.2h9.6" strokeWidth="1.4" strokeLinecap="round" />
      <path
        d="M6.2 4.1V3.1h3.6v1"
        strokeWidth="1.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M4.4 4.4l.6 8.1h5.9l.6-8.1"
        strokeWidth="1.4"
        strokeLinejoin="round"
      />
      <path
        d="M6.6 6.4v4.2M9.4 6.4v4.2"
        strokeWidth="1.4"
        strokeLinecap="round"
      />
    </svg>
  );
}
