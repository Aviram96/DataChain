"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";

import { CameraForm } from "@/components/camera-form";
import { RequireAuth } from "@/components/require-auth";
import { useToast } from "@/components/toast-provider";
import { networkErrorMessage } from "@/lib/api";
import { CamerasApiError, createCamera } from "@/lib/cameras-api";
import { ui } from "@/lib/ui";

export default function NewCameraPage() {
  const router = useRouter();
  const { showToast } = useToast();

  return (
    <RequireAuth>
      <div className="space-y-6">
        <div>
          <Link href="/cameras" className={ui.backLink}>
            ← Cameras
          </Link>
          <h1 className={`mt-2 ${ui.pageTitle}`}>Add camera</h1>
          <p className={`mt-1 ${ui.pageSubtitle}`}>
            Name, stream URL, and optional location are saved to your account.
          </p>
        </div>
        <CameraForm
          submitLabel="Add camera"
          onCancel={() => router.push("/cameras")}
          onSubmit={async (payload) => {
            try {
              await createCamera(payload);
              showToast("Camera added.", "success");
              router.push("/cameras");
            } catch (error) {
              if (error instanceof CamerasApiError) {
                showToast(error.message, "error");
              } else {
                showToast(networkErrorMessage(), "error");
              }
              throw error;
            }
          }}
        />
      </div>
    </RequireAuth>
  );
}
