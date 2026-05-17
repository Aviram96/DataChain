const DEFAULT_API_URL = "http://127.0.0.1:8000";
/** Same-origin path proxied to the API in dev (see `next.config.ts` rewrites). */
export const API_PROXY_PREFIX = "/api";

export function getApiBaseUrl(): string {
  const configured = process.env.NEXT_PUBLIC_API_URL?.trim();
  if (configured) {
    return configured.replace(/\/$/, "");
  }
  // Browser: use Next.js rewrite so register/login avoid CORS in local dev.
  if (typeof window !== "undefined") {
    return API_PROXY_PREFIX;
  }
  return DEFAULT_API_URL;
}

export function networkErrorMessage(): string {
  const target =
    process.env.NEXT_PUBLIC_API_URL?.trim() ||
    "http://127.0.0.1:8000 (via /api proxy)";
  return `Cannot reach the API (${target}). Start Postgres, set backend/.env (JWT_SECRET_KEY, DATABASE_URL), then run: cd backend && uvicorn app.main:app --reload --port 8000`;
}

type FastApiDetail = string | { msg?: string }[];

export async function parseApiErrorMessage(
  response: Response,
  fallback: string
): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: FastApiDetail };
    const { detail } = body;
    if (typeof detail === "string" && detail.length > 0) {
      return detail;
    }
    if (Array.isArray(detail) && detail.length > 0) {
      const first = detail[0];
      if (typeof first === "object" && first?.msg) {
        return first.msg;
      }
    }
  } catch {
    // ignore JSON parse errors
  }
  return fallback;
}
