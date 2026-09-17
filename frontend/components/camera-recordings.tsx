"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

import { networkErrorMessage } from "@/lib/api";
import { CamerasApiError } from "@/lib/cameras-api";
import {
  listRecordings,
  type VideoRecordPublic,
} from "@/lib/recordings-api";
import { ui } from "@/lib/ui";

import { useToast } from "./toast-provider";

const PAGE_SIZE = 10;

const COMING_SOON =
  "Watch, download, and verify will be available in a later step.";

type CameraRecordingsProps = {
  cameraId: string;
};

export function CameraRecordings({ cameraId }: CameraRecordingsProps) {
  const { showToast } = useToast();
  const [dateInput, setDateInput] = useState("");
  const [startInput, setStartInput] = useState("");
  const [endInput, setEndInput] = useState("");
  const [applied, setApplied] = useState<{
    startedAt?: string;
    endedAt?: string;
  }>({});
  const [items, setItems] = useState<VideoRecordPublic[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pages, setPages] = useState(1);
  const [loading, setLoading] = useState(true);

  const load = useCallback(
    async (pageToLoad: number) => {
      setLoading(true);
      try {
        const data = await listRecordings(cameraId, {
          page: pageToLoad,
          pageSize: PAGE_SIZE,
          startedAt: applied.startedAt,
          endedAt: applied.endedAt,
        });
        setItems(data.items);
        setTotal(data.total);
        setPage(data.page);
        setPages(data.pages);
      } catch (error) {
        if (error instanceof CamerasApiError) {
          showToast(error.message, "error");
        } else {
          showToast(networkErrorMessage(), "error");
        }
        setItems([]);
        setTotal(0);
      } finally {
        setLoading(false);
      }
    },
    [applied, cameraId, showToast]
  );

  useEffect(() => {
    void load(page);
  }, [load, page]);

  function applySearch(event: FormEvent) {
    event.preventDefault();
    const window = rangeFromForm(dateInput, startInput, endInput);
    if (window === "invalid") {
      showToast("Choose a date, then an end time after the start time.", "error");
      return;
    }
    setPage(1);
    setApplied(window);
  }

  function clearSearch() {
    setDateInput("");
    setStartInput("");
    setEndInput("");
    setPage(1);
    setApplied({});
  }

  const hasRange = Boolean(applied.startedAt || applied.endedAt);
  const emptyMessage = hasRange
    ? "No recordings match that date and time range."
    : "No recordings for this camera yet.";

  return (
    <section className="space-y-4">
      <div>
        <h2 className={`${ui.sectionTitle} text-left`}>Recordings</h2>
        <p className={`mt-1 ${ui.pageSubtitle}`}>
          Search by date and time, then choose watch, download, or verify.
        </p>
      </div>

      <form
        onSubmit={applySearch}
        className={`grid gap-3 sm:grid-cols-2 lg:grid-cols-4 lg:items-end ${ui.panel}`}
      >
        <div className="flex flex-col gap-1.5">
          <label htmlFor="recording-date" className={ui.hint}>
            Date
          </label>
          <input
            id="recording-date"
            type="date"
            value={dateInput}
            onChange={(event) => setDateInput(event.target.value)}
            className={ui.input}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <label htmlFor="recording-start" className={ui.hint}>
            Start time
          </label>
          <input
            id="recording-start"
            type="time"
            value={startInput}
            onChange={(event) => setStartInput(event.target.value)}
            className={ui.input}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <label htmlFor="recording-end" className={ui.hint}>
            End time
          </label>
          <input
            id="recording-end"
            type="time"
            value={endInput}
            onChange={(event) => setEndInput(event.target.value)}
            className={ui.input}
          />
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="submit" className={ui.btnPrimary}>
            Search
          </button>
          <button type="button" onClick={clearSearch} className={ui.btnSecondary}>
            Clear
          </button>
        </div>
      </form>

      {loading ? (
        <p className={ui.muted}>Loading recordings…</p>
      ) : items.length === 0 ? (
        <p className={`${ui.panelMuted} text-left`}>{emptyMessage}</p>
      ) : (
        <ul className="space-y-3">
          {items.map((record) => (
            <li key={record.id} className={ui.panel}>
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0 space-y-1">
                  <p className="font-medium text-landing-ink">
                    {formatWindow(record.started_at, record.ended_at)}
                  </p>
                  <p className={`break-all ${ui.hint}`}>CID {record.ipfs_cid}</p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    disabled
                    title={COMING_SOON}
                    className={ui.btnCompact}
                  >
                    Watch
                  </button>
                  <button
                    type="button"
                    disabled
                    title={COMING_SOON}
                    className={ui.btnCompact}
                  >
                    Download
                  </button>
                  <button
                    type="button"
                    disabled
                    title={COMING_SOON}
                    className={ui.btnCompact}
                  >
                    Verify
                  </button>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}

      {pages > 1 && total > 0 ? (
        <div className="flex flex-wrap items-center justify-between gap-4 border-t border-landing-ink/10 pt-4">
          <p className={ui.hint}>
            Showing {(page - 1) * PAGE_SIZE + 1}–
            {Math.min(page * PAGE_SIZE, total)} of {total} recordings
          </p>
          <div className="flex items-center gap-3">
            <button
              type="button"
              disabled={page <= 1 || loading}
              onClick={() => setPage(page - 1)}
              className={ui.btnSecondary}
            >
              Previous
            </button>
            <span className={ui.muted}>
              Page {page} of {pages}
            </span>
            <button
              type="button"
              disabled={page >= pages || loading}
              onClick={() => setPage(page + 1)}
              className={ui.btnSecondary}
            >
              Next
            </button>
          </div>
        </div>
      ) : null}
    </section>
  );
}

function rangeFromForm(
  date: string,
  start: string,
  end: string
): { startedAt?: string; endedAt?: string } | "invalid" {
  const trimmedDate = date.trim();
  if (!trimmedDate) {
    return {};
  }
  const startTime = start.trim() || "00:00";
  const startedAt = localDateTimeToIso(trimmedDate, startTime);
  let endedAt: string | null;
  if (end.trim()) {
    endedAt = localDateTimeToIso(trimmedDate, end.trim());
  } else {
    const nextDay = new Date(`${trimmedDate}T00:00:00`);
    if (Number.isNaN(nextDay.getTime())) {
      return "invalid";
    }
    nextDay.setDate(nextDay.getDate() + 1);
    endedAt = nextDay.toISOString();
  }
  if (!startedAt || !endedAt || Date.parse(endedAt) <= Date.parse(startedAt)) {
    return "invalid";
  }
  return { startedAt, endedAt };
}

function localDateTimeToIso(date: string, time: string): string | null {
  const withSeconds = time.length === 5 ? `${time}:00` : time;
  const parsed = new Date(`${date}T${withSeconds}`);
  if (Number.isNaN(parsed.getTime())) {
    return null;
  }
  return parsed.toISOString();
}

function formatWindow(startedAt: string, endedAt: string): string {
  const start = new Date(startedAt);
  const end = new Date(endedAt);
  return `${start.toLocaleString()} – ${end.toLocaleTimeString()}`;
}
