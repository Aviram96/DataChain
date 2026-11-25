export type PermanentDeleteResult = {
  camera_id: string;
  deleted: boolean;
  message: string;
};

export type ExclusiveLock = { current: boolean };

export type PermanentDeleteSubmission =
  | { status: "duplicate" }
  | {
      status: "deleted";
      message: string;
      result: PermanentDeleteResult;
    }
  | { status: "failed"; message: string };

type StatusError = { status: number; message: string };

export function permanentDeletePath(id: string): string {
  return `/cameras/${id}/permanent-delete`;
}

export function permanentDeleteSuccessMessage(): string {
  return "Camera deleted.";
}

export function permanentDeleteFailureMessage(error: StatusError): string {
  if (error.status === 404) {
    return "This archived camera could not be found. Nothing was deleted.";
  }
  if (error.status === 400) {
    return error.message
      ? `${error.message} Nothing was deleted.`
      : "Could not delete this camera. Nothing was deleted.";
  }
  if (error.status === 409) {
    const detail = error.message || "This camera cannot be deleted right now.";
    return detail.includes("Nothing was deleted")
      ? detail
      : `${detail} Nothing was deleted.`;
  }
  return error.message
    ? `${error.message} Nothing was deleted.`
    : "Could not delete this camera. Nothing was deleted.";
}

export function permanentDeleteErrorText(error: unknown): string {
  if (isStatusError(error)) {
    return permanentDeleteFailureMessage(error);
  }
  return "Cannot reach the API. Nothing was deleted.";
}

/**
 * Send one permanent delete. A second call with the same lock while the first
 * request is still running does not call `send` again.
 */
export async function submitPermanentDelete(args: {
  cameraName: string;
  lock: ExclusiveLock;
  send: (confirmName: string) => Promise<PermanentDeleteResult>;
}): Promise<PermanentDeleteSubmission> {
  if (args.lock.current) {
    return { status: "duplicate" };
  }
  args.lock.current = true;
  try {
    const result = await args.send(args.cameraName);
    return {
      status: "deleted",
      message: permanentDeleteSuccessMessage(),
      result,
    };
  } catch (error) {
    return { status: "failed", message: permanentDeleteErrorText(error) };
  } finally {
    args.lock.current = false;
  }
}

export async function performPermanentDelete(args: {
  confirmName: string;
  url: string;
  fetchImpl: (url: string, init: RequestInit) => Promise<Response>;
}): Promise<PermanentDeleteResult> {
  let response: Response;
  try {
    response = await args.fetchImpl(args.url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirm_name: args.confirmName }),
    });
  } catch {
    throw new Error("Cannot reach the API.");
  }
  if (!response.ok) {
    const fallback =
      response.status === 409
        ? "This camera cannot be deleted right now."
        : response.status === 404
          ? "Camera not found."
          : "Could not delete camera.";
    throw {
      status: response.status,
      message: await readDetail(response, fallback),
    } satisfies StatusError;
  }
  return (await response.json()) as PermanentDeleteResult;
}

async function readDetail(
  response: Response,
  fallback: string
): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string" && body.detail.length > 0) {
      return body.detail;
    }
  } catch {
    // Ignore a body that is not JSON.
  }
  return fallback;
}

function isStatusError(error: unknown): error is StatusError {
  if (typeof error !== "object" || error === null) {
    return false;
  }
  const value = error as { status?: unknown; message?: unknown };
  return typeof value.status === "number" && typeof value.message === "string";
}
