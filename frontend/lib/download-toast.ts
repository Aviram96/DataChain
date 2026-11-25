import type { ToastVariant } from "./toast-variants";

export type DownloadToastReport = {
  overall: string;
  detail: string;
  discontinuous: boolean;
};

export type DownloadToast = {
  message: string;
  variant: ToastVariant;
};

/** Toast for a download that saved a file. */
export function toastForSuccessfulDownload(
  report: DownloadToastReport
): DownloadToast {
  if (report.discontinuous) {
    return { variant: "warning", message: report.detail };
  }
  if (report.overall !== "verified") {
    return { variant: "error", message: report.detail };
  }
  return { variant: "success", message: report.detail };
}

/**
 * Show the toast before saving the file.
 * The save clicks a download link, and that click can discard a toast that
 * has only been scheduled and not painted yet.
 */
export function deliverSuccessfulDownload(
  report: DownloadToastReport,
  actions: {
    showToast: (message: string, variant: ToastVariant) => void;
    save: () => void;
  }
): DownloadToast {
  const notice = toastForSuccessfulDownload(report);
  actions.showToast(notice.message, notice.variant);
  actions.save();
  return notice;
}

/** Toast for a download that did not save a file. */
export function toastForFailedDownload(message: string): DownloadToast {
  return { variant: "error", message };
}
