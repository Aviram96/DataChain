/** Where Cancel returns. Only these two pages are allowed. */

export type EditSource = "list" | "details";

const FROM_LIST = "list";

export function cameraEditHref(cameraId: string, source: EditSource): string {
  const path = `/cameras/${cameraId}/edit`;
  if (source === "list") {
    return `${path}?from=${FROM_LIST}`;
  }
  return path;
}

export function cameraEditCancelHref(
  cameraId: string,
  from: string | null
): string {
  if (from === FROM_LIST) {
    return "/cameras";
  }
  return `/cameras/${cameraId}`;
}

/** Where Save Changes goes. Null keeps the user on the edit page. */
export function cameraEditSaveHref(
  cameraId: string,
  from: string | null,
  saved: boolean
): string | null {
  if (!saved) {
    return null;
  }
  return cameraEditCancelHref(cameraId, from);
}
