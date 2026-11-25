"use client";

import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";

import { CameraForm } from "@/components/camera-form";
import { RequireAuth } from "@/components/require-auth";
import { useToast } from "@/components/toast-provider";
import { networkErrorMessage } from "@/lib/api";
import {
  CamerasApiError,
  getCamera,
  updateCamera,
  type CameraPublic,
} from "@/lib/cameras-api";
import { isArchivedCamera } from "@/lib/camera-archive";
import { cameraEditCancelHref, cameraEditSaveHref } from "@/lib/edit-return";
import { ui } from "@/lib/ui";

export default function EditCameraPage() {
  const params = useParams();
  const cameraId = typeof params.id === "string" ? params.id : "";

  return (
    <RequireAuth>
      <div className="space-y-6">
        <div>
          <Link href={`/cameras/${cameraId}`} className={ui.backLink}>
            ← Camera
          </Link>
          <h1 className={`mt-2 ${ui.pageTitle}`}>Edit camera</h1>
          <p className={`mt-1 ${ui.pageSubtitle}`}>
            Update name, stream URL, or location.
          </p>
        </div>
        <Suspense fallback={<p className={ui.muted}>Loading camera…</p>}>
          <EditCameraForm cameraId={cameraId} />
        </Suspense>
      </div>
    </RequireAuth>
  );
}

function EditCameraForm({ cameraId }: { cameraId: string }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { showToast } = useToast();

  const [camera, setCamera] = useState<CameraPublic | null>(null);
  const [loading, setLoading] = useState(true);

  const loadCamera = useCallback(async () => {
    if (!cameraId) {
      setLoading(false);
      return;
    }
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
      router.replace("/cameras");
    } finally {
      setLoading(false);
    }
  }, [cameraId, router, showToast]);

  useEffect(() => {
    void loadCamera();
  }, [loadCamera]);

  const cancelHref = cameraEditCancelHref(
    camera?.id ?? cameraId,
    searchParams.get("from")
  );

  if (loading) {
    return <p className={ui.muted}>Loading camera…</p>;
  }

  if (camera && isArchivedCamera(camera)) {
    return (
      <div className="space-y-3">
        <p className={ui.muted}>
          Archived cameras cannot be edited. Restore the camera before changing
          it.
        </p>
        <Link href={`/cameras/${camera.id}`} className={ui.link}>
          View recordings
        </Link>
      </div>
    );
  }

  return camera ? (
    <CameraForm
      key={camera.id}
      submitLabel="Save changes"
      initialValues={{
        name: camera.name,
        stream_url: camera.stream_url,
        location: camera.location,
      }}
      onCancel={() => router.push(cancelHref)}
      onSubmit={async (payload) => {
        try {
          await updateCamera(camera.id, payload);
          showToast("Camera updated.", "success");
          const href = cameraEditSaveHref(
            camera.id,
            searchParams.get("from"),
            true
          );
          if (href) {
            router.push(href);
          }
        } catch (error) {
          if (error instanceof CamerasApiError) {
            showToast(error.message, "error");
          } else {
            showToast(networkErrorMessage(), "error");
          }
          const href = cameraEditSaveHref(
            camera.id,
            searchParams.get("from"),
            false
          );
          if (href) {
            router.push(href);
          }
          throw error;
        }
      }}
    />
  ) : (
    <p className={ui.muted}>Camera not found.</p>
  );
}
