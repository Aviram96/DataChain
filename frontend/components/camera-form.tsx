"use client";

import { FormEvent, useState } from "react";

import type { CameraCreatePayload } from "@/lib/cameras-api";
import { ui } from "@/lib/ui";

export type CameraFormInitialValues = {
  name: string;
  stream_url: string;
  location: string | null;
};

type CameraFormProps = {
  submitLabel: string;
  onSubmit: (payload: CameraCreatePayload) => Promise<void>;
  onCancel?: () => void;
  initialValues?: CameraFormInitialValues;
};

export function CameraForm({
  submitLabel,
  onSubmit,
  onCancel,
  initialValues,
}: CameraFormProps) {
  const [name, setName] = useState(initialValues?.name ?? "");
  const [streamUrl, setStreamUrl] = useState(initialValues?.stream_url ?? "");
  const [location, setLocation] = useState(initialValues?.location ?? "");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    try {
      await onSubmit({
        name: name.trim(),
        stream_url: streamUrl.trim(),
        location: location.trim() ? location.trim() : null,
      });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className={`space-y-4 ${ui.panel}`}>
      <div className="space-y-1.5">
        <label htmlFor="camera-name" className={ui.label}>
          Name
        </label>
        <input
          id="camera-name"
          name="camera-name"
          type="text"
          required
          value={name}
          onChange={(e) => setName(e.target.value)}
          className={ui.input}
        />
      </div>
      <div className="space-y-1.5">
        <label htmlFor="camera-stream-url" className={ui.label}>
          Stream URL
        </label>
        <input
          id="camera-stream-url"
          name="camera-stream-url"
          type="text"
          required
          value={streamUrl}
          onChange={(e) => setStreamUrl(e.target.value)}
          className={ui.input}
        />
        <p className={ui.hint}>http://, https://, or rtsp://</p>
      </div>
      <div className="space-y-1.5">
        <label htmlFor="camera-location" className={ui.label}>
          Location (optional)
        </label>
        <input
          id="camera-location"
          name="camera-location"
          type="text"
          value={location}
          onChange={(e) => setLocation(e.target.value)}
          className={ui.input}
        />
      </div>
      <div className="flex flex-wrap gap-3 pt-1">
        <button type="submit" disabled={submitting} className={ui.btnPrimary}>
          {submitting ? "Saving…" : submitLabel}
        </button>
        {onCancel ? (
          <button type="button" onClick={onCancel} className={ui.btnSecondary}>
            Cancel
          </button>
        ) : null}
      </div>
    </form>
  );
}
