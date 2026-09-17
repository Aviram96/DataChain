import { getApiBaseUrl, parseApiErrorMessage } from "./api";
import { authFetch } from "./auth-fetch";
import { CamerasApiError } from "./cameras-api";

export type VideoRecordPublic = {
  id: string;
  camera_id: string;
  started_at: string;
  ended_at: string;
  ipfs_cid: string;
  segment_hash: string;
  tx_hash: string | null;
};

export type VideoRecordListResponse = {
  items: VideoRecordPublic[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
};

export type ListRecordingsParams = {
  page?: number;
  pageSize?: number;
  startedAt?: string;
  endedAt?: string;
};

export async function listRecordings(
  cameraId: string,
  params: ListRecordingsParams = {}
): Promise<VideoRecordListResponse> {
  const search = new URLSearchParams({
    page: String(params.page ?? 1),
    page_size: String(params.pageSize ?? 10),
  });
  if (params.startedAt) {
    search.set("started_at", params.startedAt);
  }
  if (params.endedAt) {
    search.set("ended_at", params.endedAt);
  }

  const response = await authFetch(
    `${getApiBaseUrl()}/cameras/${cameraId}/recordings?${search.toString()}`
  );

  if (!response.ok) {
    const message = await parseApiErrorMessage(
      response,
      "Could not load recordings."
    );
    throw new CamerasApiError(message, response.status);
  }

  return (await response.json()) as VideoRecordListResponse;
}

const VERIFY_PAGE_SIZE = 50;

export async function listAllRecordings(
  cameraId: string,
  params: Pick<ListRecordingsParams, "startedAt" | "endedAt"> = {}
): Promise<VideoRecordPublic[]> {
  const items: VideoRecordPublic[] = [];
  let page = 1;
  let pages = 1;

  while (page <= pages) {
    const data = await listRecordings(cameraId, {
      page,
      pageSize: VERIFY_PAGE_SIZE,
      startedAt: params.startedAt,
      endedAt: params.endedAt,
    });
    items.push(...data.items);
    pages = data.pages;
    if (items.length >= data.total || data.items.length === 0) {
      break;
    }
    page += 1;
  }

  return items;
}
