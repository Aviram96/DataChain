import { getApiBaseUrl, parseApiErrorMessage } from "./api";
import { authFetch } from "./auth-fetch";

export type CameraCreatePayload = {
  name: string;
  stream_url: string;
  location?: string | null;
};

export type CameraPublic = {
  id: string;
  name: string;
  stream_url: string;
  location: string | null;
  created_at: string;
};

export class CamerasApiError extends Error {
  constructor(
    message: string,
    readonly status: number
  ) {
    super(message);
    this.name = "CamerasApiError";
  }
}

export async function createCamera(
  payload: CameraCreatePayload
): Promise<CameraPublic> {
  const response = await authFetch(`${getApiBaseUrl()}/cameras`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const message = await parseApiErrorMessage(
      response,
      "Could not add camera."
    );
    throw new CamerasApiError(message, response.status);
  }

  return (await response.json()) as CameraPublic;
}
