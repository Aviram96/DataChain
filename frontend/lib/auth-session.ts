import { clearAccessToken } from "./auth-token";

const PUBLIC_AUTH_PATHS = ["/login", "/register"];

let sessionExpiredHandler: ((message: string) => void) | null = null;

export function registerSessionExpiredHandler(
  handler: ((message: string) => void) | null,
): void {
  sessionExpiredHandler = handler;
}

function isPublicAuthPath(pathname: string): boolean {
  return PUBLIC_AUTH_PATHS.some(
    (path) => pathname === path || pathname.startsWith(`${path}/`),
  );
}

export function clearSessionAndRedirect(options?: {
  message?: string;
}): void {
  clearAccessToken();

  if (typeof window === "undefined") {
    return;
  }

  const onPublicAuthPage = isPublicAuthPath(window.location.pathname);

  if (options?.message && !onPublicAuthPage && sessionExpiredHandler) {
    sessionExpiredHandler(options.message);
  }

  if (!onPublicAuthPage) {
    window.location.assign("/login");
  }
}
