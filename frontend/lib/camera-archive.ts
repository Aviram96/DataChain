export function isArchivedCamera(camera: { lifecycle: string }): boolean {
  return camera.lifecycle === "archived";
}

/** Shown when restore is refused because an active camera already has the name. */
export function restoreNameConflictMessage(): string {
  return "An active camera already uses this name. Rename that camera, then restore this one. Nothing was changed.";
}

export function restoreFailureMessage(error: {
  status: number;
  message: string;
}): string {
  if (
    error.status === 409 &&
    error.message.toLowerCase().includes("already have a camera")
  ) {
    return restoreNameConflictMessage();
  }
  return error.message;
}
