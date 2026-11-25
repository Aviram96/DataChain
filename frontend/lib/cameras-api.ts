import { getApiBaseUrl, parseApiErrorMessage } from "./api";
import { authFetch } from "./auth-fetch";
import {
  performPermanentDelete,
  permanentDeletePath,
  type PermanentDeleteResult,
} from "./permanent-delete";

export type { PermanentDeleteResult };

export type CameraCreatePayload = {
  name: string;
  stream_url: string;
  location?: string | null;
};

export type CameraStatus = "online" | "offline";

/** Present when status is offline: ingest restart-cap vs stream probe. */
export type CameraOfflineReason = "ingest_failed" | "unreachable";

/** Archived is separate from online/offline. The API sends this on every camera. */
export type CameraLifecycle = "active" | "archived";

/** Default list sort: newest cameras first (Slice B / CP-B.C10). */
export type CameraSort =
  | "created_at_desc"
  | "created_at_asc"
  | "name_asc"
  | "name_desc";

export const DEFAULT_CAMERA_SORT: CameraSort = "created_at_desc";

export type CameraPublic = {
  id: string;
  name: string;
  stream_url: string;
  location: string | null;
  created_at: string;
  status: CameraStatus;
  offline_reason: CameraOfflineReason | null;
  ingest_offline_at: string | null;
  lifecycle: CameraLifecycle;
  archived_at: string | null;
};

/** Copy for ingest restart-cap (CP-C.C1); includes when capture stopped. */
export function ingestFailedMessage(
  camera: Pick<
    CameraPublic,
    "offline_reason" | "ingest_offline_at" | "lifecycle"
  >
): string | null {
  if (camera.lifecycle === "archived") {
    return null;
  }
  if (camera.offline_reason !== "ingest_failed") {
    return null;
  }
  const since = camera.ingest_offline_at
    ? ` since ${new Date(camera.ingest_offline_at).toLocaleString()}`
    : "";
  return `Capture stopped after repeated failures${since}. Footage for this period may be missing.`;
}

export type CameraListResponse = {
  items: CameraPublic[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
};

export type ListCamerasParams = {
  page?: number;
  pageSize?: number;
  q?: string;
  status?: CameraStatus | "";
  sort?: CameraSort;
};

export class CamerasApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "CamerasApiError";
    this.status = status;
  }
}

export async function listCameras(
  params: ListCamerasParams | number = 1,
  pageSize = 10
): Promise<CameraListResponse> {
  const normalized: ListCamerasParams =
    typeof params === "number"
      ? { page: params, pageSize }
      : { pageSize: 10, ...params };

  const search = new URLSearchParams({
    page: String(normalized.page ?? 1),
    page_size: String(normalized.pageSize ?? 10),
    sort: normalized.sort ?? DEFAULT_CAMERA_SORT,
  });
  if (normalized.q?.trim()) {
    search.set("q", normalized.q.trim());
  }
  if (normalized.status === "online" || normalized.status === "offline") {
    search.set("status", normalized.status);
  }

  const response = await authFetch(
    `${getApiBaseUrl()}/cameras?${search.toString()}`
  );

  if (!response.ok) {
    const message = await parseApiErrorMessage(
      response,
      "Could not load cameras."
    );
    throw new CamerasApiError(message, response.status);
  }

  return (await response.json()) as CameraListResponse;
}

export async function listArchivedCameras(
  params: Omit<ListCamerasParams, "status"> | number = 1,
  pageSize = 10
): Promise<CameraListResponse> {
  const normalized: Omit<ListCamerasParams, "status"> =
    typeof params === "number"
      ? { page: params, pageSize }
      : { pageSize: 10, ...params };

  const search = new URLSearchParams({
    page: String(normalized.page ?? 1),
    page_size: String(normalized.pageSize ?? 10),
    sort: normalized.sort ?? DEFAULT_CAMERA_SORT,
  });
  if (normalized.q?.trim()) {
    search.set("q", normalized.q.trim());
  }

  const response = await authFetch(
    `${getApiBaseUrl()}/cameras/archived?${search.toString()}`
  );

  if (!response.ok) {
    const message = await parseApiErrorMessage(
      response,
      "Could not load archived cameras."
    );
    throw new CamerasApiError(message, response.status);
  }

  return (await response.json()) as CameraListResponse;
}

export async function getCamera(id: string): Promise<CameraPublic> {
  const response = await authFetch(`${getApiBaseUrl()}/cameras/${id}`);

  if (!response.ok) {
    const message = await parseApiErrorMessage(
      response,
      "Could not load camera."
    );
    throw new CamerasApiError(message, response.status);
  }

  return (await response.json()) as CameraPublic;
}

export async function updateCamera(
  id: string,
  payload: CameraCreatePayload
): Promise<CameraPublic> {
  const response = await authFetch(`${getApiBaseUrl()}/cameras/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const fallback =
      response.status === 409
        ? "You already have a camera with this name."
        : "Could not update camera.";
    const message = await parseApiErrorMessage(response, fallback);
    throw new CamerasApiError(message, response.status);
  }

  return (await response.json()) as CameraPublic;
}

export async function archiveCamera(id: string): Promise<CameraPublic> {
  const response = await authFetch(`${getApiBaseUrl()}/cameras/${id}/archive`, {
    method: "POST",
  });

  if (!response.ok) {
    const message = await parseApiErrorMessage(
      response,
      "Could not archive camera."
    );
    throw new CamerasApiError(message, response.status);
  }

  return (await response.json()) as CameraPublic;
}

export async function permanentlyDeleteCamera(
  id: string,
  confirmName: string
): Promise<PermanentDeleteResult> {
  try {
    return await performPermanentDelete({
      confirmName,
      url: `${getApiBaseUrl()}${permanentDeletePath(id)}`,
      fetchImpl: (url, init) => authFetch(url, init),
    });
  } catch (error) {
    if (isDeleteStatusError(error)) {
      throw new CamerasApiError(error.message, error.status);
    }
    throw error;
  }
}

function isDeleteStatusError(
  error: unknown
): error is { status: number; message: string } {
  if (typeof error !== "object" || error === null) {
    return false;
  }
  const value = error as { status?: unknown; message?: unknown };
  return typeof value.status === "number" && typeof value.message === "string";
}

export async function restoreCamera(id: string): Promise<CameraPublic> {
  const response = await authFetch(`${getApiBaseUrl()}/cameras/${id}/restore`, {
    method: "POST",
  });

  if (!response.ok) {
    const fallback =
      response.status === 409
        ? "You already have a camera with this name."
        : "Could not restore camera.";
    const message = await parseApiErrorMessage(response, fallback);
    throw new CamerasApiError(message, response.status);
  }

  return (await response.json()) as CameraPublic;
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
    const fallback =
      response.status === 409
        ? "You already have a camera with this name."
        : "Could not add camera.";
    const message = await parseApiErrorMessage(response, fallback);
    throw new CamerasApiError(message, response.status);
  }

  return (await response.json()) as CameraPublic;
}
