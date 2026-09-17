import { getApiBaseUrl, parseApiErrorMessage } from "./api";
import { authFetch } from "./auth-fetch";
import { CamerasApiError } from "./cameras-api";
import type { VerifyStatus } from "./verify-recordings";

export type VerificationScope = "full" | "partial" | "minute";

export type VerificationMinuteInput = {
  started_at: string;
  status: VerifyStatus;
  detail: string;
  video_record_id: string | null;
};

export type VerificationAttemptCreate = {
  started_at: string;
  ended_at: string;
  scope: VerificationScope;
  overall_status: VerifyStatus;
  minutes: VerificationMinuteInput[];
};

export type VerificationAttemptSummary = {
  id: string;
  user_id: string;
  camera_id: string;
  started_at: string;
  ended_at: string;
  scope: VerificationScope;
  overall_status: VerifyStatus;
  created_at: string;
};

export type VerificationAttemptListResponse = {
  items: VerificationAttemptSummary[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
};

export type ListVerificationAttemptsParams = {
  page?: number;
  pageSize?: number;
};

export async function createVerificationAttempt(
  cameraId: string,
  payload: VerificationAttemptCreate
): Promise<VerificationAttemptSummary> {
  const response = await authFetch(
    `${getApiBaseUrl()}/cameras/${cameraId}/verification-attempts`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );

  if (!response.ok) {
    const message = await parseApiErrorMessage(
      response,
      "Could not save this verification to the audit trail."
    );
    throw new CamerasApiError(message, response.status);
  }

  return (await response.json()) as VerificationAttemptSummary;
}

export async function listVerificationAttempts(
  cameraId: string,
  params: ListVerificationAttemptsParams = {}
): Promise<VerificationAttemptListResponse> {
  const search = new URLSearchParams({
    page: String(params.page ?? 1),
    page_size: String(params.pageSize ?? 10),
  });
  const response = await authFetch(
    `${getApiBaseUrl()}/cameras/${cameraId}/verification-attempts?${search.toString()}`
  );

  if (!response.ok) {
    const message = await parseApiErrorMessage(
      response,
      "Could not load verification history."
    );
    throw new CamerasApiError(message, response.status);
  }

  return (await response.json()) as VerificationAttemptListResponse;
}
