"use client";

import { FormEvent, useState } from "react";

import type { CameraCreatePayload } from "@/lib/cameras-api";

type CameraFormProps = {
  submitLabel: string;
  onSubmit: (payload: CameraCreatePayload) => Promise<void>;
  onCancel?: () => void;
};

export function CameraForm({
  submitLabel,
  onSubmit,
  onCancel,
}: CameraFormProps) {
  const [name, setName] = useState("");
  const [streamUrl, setStreamUrl] = useState("");
  const [location, setLocation] = useState("");
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

  const inputClass =
    "w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100 outline-none ring-emerald-500/50 focus:ring-2";

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="space-y-1">
        <label htmlFor="camera-name" className="block text-sm text-slate-300">
          Name
        </label>
        <input
          id="camera-name"
          name="camera-name"
          type="text"
          required
          value={name}
          onChange={(e) => setName(e.target.value)}
          className={inputClass}
        />
      </div>
      <div className="space-y-1">
        <label
          htmlFor="camera-stream-url"
          className="block text-sm text-slate-300"
        >
          IP / stream URL
        </label>
        <input
          id="camera-stream-url"
          name="camera-stream-url"
          type="text"
          required
          value={streamUrl}
          onChange={(e) => setStreamUrl(e.target.value)}
          className={inputClass}
        />
        <p className="text-xs text-slate-500">http://, https://, or rtsp://</p>
      </div>
      <div className="space-y-1">
        <label
          htmlFor="camera-location"
          className="block text-sm text-slate-300"
        >
          Location (optional)
        </label>
        <input
          id="camera-location"
          name="camera-location"
          type="text"
          value={location}
          onChange={(e) => setLocation(e.target.value)}
          className={inputClass}
        />
      </div>
      <FormActions
        submitLabel={submitLabel}
        submitting={submitting}
        onCancel={onCancel}
      />
    </form>
  );
}

function FormActions({
  submitLabel,
  submitting,
  onCancel,
}: {
  submitLabel: string;
  submitting: boolean;
  onCancel?: () => void;
}) {
  return (
    <div className="flex flex-wrap gap-3">
      <button
        type="submit"
        disabled={submitting}
        className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500 disabled:opacity-60"
      >
        {submitting ? "Saving…" : submitLabel}
      </button>
      {onCancel ? (
        <button
          type="button"
          onClick={onCancel}
          className="rounded-md border border-slate-600 px-4 py-2 text-sm text-slate-300 hover:border-slate-500"
        >
          Cancel
        </button>
      ) : null}
    </div>
  );
}
