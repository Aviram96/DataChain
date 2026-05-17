import { parseApiErrorMessage } from "./api";
import { clearSessionAndRedirect } from "./auth-session";
import { getAccessToken } from "./auth-token";

const DEFAULT_SESSION_MESSAGE =
  "Your session has expired. Please sign in again.";

export async function authFetch(
  input: RequestInfo | URL,
  init?: RequestInit
): Promise<Response> {
  const token = getAccessToken();
  const headers = new Headers(init?.headers);
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(input, { ...init, headers });

  if (response.status === 401 && token) {
    const message = await parseApiErrorMessage(
      response,
      DEFAULT_SESSION_MESSAGE
    );
    clearSessionAndRedirect({ message });
  }

  return response;
}
