import { ui } from "@/lib/ui";

export default function ProjectStatusPage() {
  return (
    <div className="space-y-4">
      <h1 className={ui.pageTitle}>Project status</h1>
      <p className={ui.muted}>
        Internal status page for local development checks. This route is not
        linked from the public landing.
      </p>
      <ul className={`list-inside list-disc space-y-2 ${ui.muted}`}>
        <li>Frontend dev server: see README in this folder.</li>
        <li>Backend health: FastAPI GET /health (when API is running).</li>
        <li>Database: Docker Compose PostgreSQL at repo root.</li>
      </ul>
    </div>
  );
}
