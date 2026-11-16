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

export type PlaybackStatus =
  | "verified"
  | "tampered"
  | "missing"
  | "unavailable"
  | "failed";

export type PlaybackSegmentResult = {
  video_record_id: string;
  started_at: string;
  ended_at: string;
  status: PlaybackStatus;
  detail: string;
};

export type PlaybackInterval = {
  started_at: string;
  ended_at: string;
  detail: string;
};

export type PlaybackDenial = {
  overall: PlaybackStatus;
  detail: string;
  segments: PlaybackSegmentResult[];
  missing_intervals: PlaybackInterval[];
  excluded_intervals: Array<
    PlaybackInterval & { status: PlaybackStatus; video_record_id: string }
  >;
};

export class PlaybackVerificationError extends Error {
  readonly denial: PlaybackDenial;

  constructor(denial: PlaybackDenial) {
    super(denial.detail);
    this.name = "PlaybackVerificationError";
    this.denial = denial;
  }
}

export async function fetchRecordingPlayback(
  cameraId: string,
  recordId: string,
  signal?: AbortSignal
): Promise<Blob> {
  const response = await authFetch(
    `${getApiBaseUrl()}/cameras/${cameraId}/recordings/${recordId}/playback`,
    { signal }
  );

  if (!response.ok) {
    const body = await readJson(response);
    const denial = playbackDenialFrom(body);
    if (denial) {
      throw new PlaybackVerificationError(denial);
    }
    throw new CamerasApiError(
      messageFromBody(body, "Could not play this recording."),
      response.status
    );
  }

  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("video/")) {
    throw new CamerasApiError("Could not play this recording.", response.status);
  }
  return response.blob();
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

function playbackDenialFrom(body: unknown): PlaybackDenial | null {
  if (typeof body !== "object" || body === null) {
    return null;
  }
  const record = body as Partial<PlaybackDenial>;
  if (
    typeof record.overall !== "string" ||
    typeof record.detail !== "string" ||
    !Array.isArray(record.segments)
  ) {
    return null;
  }
  return record as PlaybackDenial;
}

function messageFromBody(body: unknown, fallback: string): string {
  if (typeof body !== "object" || body === null || !("detail" in body)) {
    return fallback;
  }
  const detail = (body as { detail?: unknown }).detail;
  return typeof detail === "string" && detail.length > 0 ? detail : fallback;
}

export type DownloadSegmentResult = PlaybackSegmentResult & {
  tx_hash?: string | null;
};

export type DownloadVerification = {
  overall: PlaybackStatus;
  detail: string;
  discontinuous: boolean;
  segments: DownloadSegmentResult[];
  missing_intervals: PlaybackInterval[];
  excluded_intervals: PlaybackDenial["excluded_intervals"];
};

export class DownloadVerificationError extends Error {
  readonly report: DownloadVerification;

  constructor(report: DownloadVerification) {
    super(report.detail);
    this.name = "DownloadVerificationError";
    this.report = report;
  }
}

export type DownloadResult = {
  report: DownloadVerification;
  video: Blob;
  filename: string;
};

export async function downloadRecordings(
  cameraId: string,
  params: { startedAt: string; endedAt: string },
  signal?: AbortSignal
): Promise<DownloadResult> {
  const search = new URLSearchParams({
    started_at: params.startedAt,
    ended_at: params.endedAt,
  });
  const response = await authFetch(
    `${getApiBaseUrl()}/cameras/${cameraId}/recordings/download?${search.toString()}`,
    { signal }
  );

  if (!response.ok) {
    const body = await readJson(response);
    const report = downloadReportFrom(body);
    if (report) {
      throw new DownloadVerificationError(report);
    }
    throw new CamerasApiError(
      messageFromBody(body, "Could not download recordings."),
      response.status
    );
  }

  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("multipart/form-data")) {
    throw new CamerasApiError("Could not download recordings.", response.status);
  }
  const form = await response.formData();
  const report = downloadReportFrom(await readFormJson(form.get("report")));
  const video = form.get("video");
  if (!report || !(video instanceof Blob) || video.size <= 0) {
    throw new CamerasApiError("Could not download recordings.", response.status);
  }
  const filename =
    video instanceof File && video.name ? video.name : "recording.mp4";
  return { report, video, filename };
}

export function saveRecordingDownload(video: Blob, filename: string): void {
  const url = URL.createObjectURL(video);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

async function readFormJson(part: FormDataEntryValue | null): Promise<unknown> {
  if (typeof part === "string") {
    try {
      return JSON.parse(part) as unknown;
    } catch {
      return null;
    }
  }
  if (part instanceof Blob) {
    try {
      return JSON.parse(await part.text()) as unknown;
    } catch {
      return null;
    }
  }
  return null;
}

function downloadReportFrom(body: unknown): DownloadVerification | null {
  if (typeof body !== "object" || body === null) {
    return null;
  }
  const record = body as Partial<DownloadVerification>;
  if (
    typeof record.overall !== "string" ||
    typeof record.detail !== "string" ||
    typeof record.discontinuous !== "boolean" ||
    !Array.isArray(record.segments) ||
    !Array.isArray(record.missing_intervals) ||
    !Array.isArray(record.excluded_intervals)
  ) {
    return null;
  }
  return record as DownloadVerification;
}

