export type ToastVariant = "error" | "success" | "warning";

const LABEL_CLASS = "mb-1 block text-xs font-semibold uppercase tracking-wide";

export function toastLabel(variant: ToastVariant): string {
  if (variant === "error") {
    return "Error";
  }
  if (variant === "warning") {
    return "Warning";
  }
  return "Success";
}

export function toastClassName(variant: ToastVariant): string {
  if (variant === "error") {
    return "border-landing-warn/40 bg-white text-landing-ink shadow-md";
  }
  if (variant === "warning") {
    return "border-landing-caution/45 bg-white text-landing-ink shadow-md";
  }
  return "border-landing-accent/35 bg-white text-landing-ink shadow-md";
}

export function toastLabelClassName(variant: ToastVariant): string {
  if (variant === "error") {
    return `${LABEL_CLASS} text-landing-warn`;
  }
  if (variant === "warning") {
    return `${LABEL_CLASS} text-landing-caution`;
  }
  return `${LABEL_CLASS} text-landing-accent`;
}
