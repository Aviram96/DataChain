import { CamerasDashboard } from "@/components/cameras-dashboard";
import { RequireAuth } from "@/components/require-auth";

export default function CamerasPage() {
  return (
    <RequireAuth>
      <CamerasDashboard />
    </RequireAuth>
  );
}
