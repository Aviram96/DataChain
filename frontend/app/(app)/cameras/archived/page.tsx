import { ArchivedCameras } from "@/components/archived-cameras";
import { RequireAuth } from "@/components/require-auth";

export default function ArchivedCamerasPage() {
  return (
    <RequireAuth>
      <ArchivedCameras />
    </RequireAuth>
  );
}
