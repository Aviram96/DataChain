"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";

import { networkErrorMessage } from "@/lib/api";
import { CamerasApiError } from "@/lib/cameras-api";
import {
  downloadRecordings,
  DownloadVerificationError,
  fetchRecordingPlayback,
  listAllRecordings,
  listRecordings,
  PlaybackVerificationError,
  saveRecordingDownload,
  type DownloadVerification,
  type PlaybackDenial,
  type VideoRecordPublic,
} from "@/lib/recordings-api";
import { ui } from "@/lib/ui";
import { createVerificationAttempt } from "@/lib/verification-api";
import { createDatachainContract, mapPool, readChainSegment } from "@/lib/verify-chain";
import {
  aggregateStatus,
  classifySegment,
  clipSubRange,
  expectedMinuteStarts,
  findRecordForSlot,
  formatLocalWindow,
  MAX_EXPECTED_MINUTES,
  type VerifyMinuteResult,
  type VerifyReport,
} from "@/lib/verify-recordings";

import { RecordingVerifyPanel, VerifyBadge } from "./recording-verify-panel";
import { useToast } from "./toast-provider";
import { VerificationHistory } from "./verification-history";

const PAGE_SIZE = 10;

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
  const [watching, setWatching] = useState<VideoRecordPublic | null>(null);
  const [watchSrc, setWatchSrc] = useState<string | null>(null);
  const [watchPendingId, setWatchPendingId] = useState<string | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [verifyReport, setVerifyReport] = useState<VerifyReport | null>(null);
  const [historyTick, setHistoryTick] = useState(0);
  const [partialStart, setPartialStart] = useState("");
  const [partialEnd, setPartialEnd] = useState("");
  const playbackErrorFor = useRef<string | null>(null);
  const watchSeq = useRef(0);
  const activitySeq = useRef(0);
  const watchAbort = useRef<AbortController | null>(null);
  const downloadAbort = useRef<AbortController | null>(null);
  const watchBlob = useRef<string | null>(null);

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

  useEffect(() => {
    setVerifyReport(null);
    if (applied.startedAt && applied.endedAt) {
      setPartialStart(isoToLocalTime(applied.startedAt));
      setPartialEnd(
        isoToLocalDate(applied.endedAt) === isoToLocalDate(applied.startedAt)
          ? isoToLocalTime(applied.endedAt)
          : "23:59"
      );
    } else {
      setPartialStart("");
      setPartialEnd("");
    }
  }, [applied, cameraId]);

  useEffect(() => {
    return () => {
      watchAbort.current?.abort();
      downloadAbort.current?.abort();
      if (watchBlob.current) {
        URL.revokeObjectURL(watchBlob.current);
      }
    };
  }, []);

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

  function revokeWatchBlob() {
    if (watchBlob.current) {
      URL.revokeObjectURL(watchBlob.current);
      watchBlob.current = null;
    }
  }

  function closeWatch() {
    watchSeq.current += 1;
    watchAbort.current?.abort();
    watchAbort.current = null;
    revokeWatchBlob();
    setWatchSrc(null);
    setWatching(null);
    setWatchPendingId(null);
  }

  function openWatch(record: VideoRecordPublic) {
    watchAbort.current?.abort();
    downloadAbort.current?.abort();
    const controller = new AbortController();
    watchAbort.current = controller;
    const seq = watchSeq.current + 1;
    watchSeq.current = seq;
    const activity = ++activitySeq.current;
    revokeWatchBlob();
    playbackErrorFor.current = null;
    setWatchSrc(null);
    setWatching(null);
    setVerifyReport(null);
    setWatchPendingId(record.id);

    void (async () => {
      try {
        const blob = await fetchRecordingPlayback(
          cameraId,
          record.id,
          controller.signal
        );
        if (seq !== watchSeq.current || activity !== activitySeq.current) {
          return;
        }
        const url = URL.createObjectURL(blob);
        watchBlob.current = url;
        setWatchSrc(url);
        setWatching(record);
        setVerifyReport(verifiedWatchReport(record));
      } catch (error) {
        if (
          seq !== watchSeq.current ||
          activity !== activitySeq.current ||
          controller.signal.aborted
        ) {
          return;
        }
        if (error instanceof PlaybackVerificationError) {
          setVerifyReport(deniedWatchReport(record, error.denial));
          showToast(error.denial.detail, "error");
          return;
        }
        if (error instanceof CamerasApiError) {
          showToast(error.message, "error");
          return;
        }
        showToast(networkErrorMessage(), "error");
      } finally {
        if (seq === watchSeq.current) {
          setWatchPendingId(null);
        }
      }
    })();
  }

  function handlePlaybackError() {
    if (!watching || playbackErrorFor.current === watching.id) {
      return;
    }
    playbackErrorFor.current = watching.id;
    showToast("Could not play this recording. Try again.", "error");
  }

  async function runVerify(
    range: { startedAt: string; endedAt: string },
    recordsOverride?: VideoRecordPublic[],
    scope: "full" | "partial" | "minute" = "full"
  ) {
    const slots = expectedMinuteStarts(range.startedAt, range.endedAt);
    if (slots.length === 0) {
      showToast("Choose a date, then an end time after the start time.", "error");
      return;
    }
    if (slots.length > MAX_EXPECTED_MINUTES) {
      showToast("Choose a range of 24 hours or less to verify.", "error");
      return;
    }

    const activity = ++activitySeq.current;
    setVerifying(true);
    try {
      const records =
        recordsOverride ??
        (await listAllRecordings(cameraId, {
          startedAt: range.startedAt,
          endedAt: range.endedAt,
        }));
      const contract = createDatachainContract();
      const used = new Set<string>();
      const slotWork = slots.map((slot) => {
        const record = findRecordForSlot(records, slot) ?? null;
        if (record) {
          used.add(record.id);
        }
        return { slot, record };
      });
      const extras = records
        .filter((record) => !used.has(record.id))
        .map((record) => ({
          slot: new Date(record.started_at),
          record,
        }));
      const work = [...slotWork, ...extras];
      const results = await mapPool(work, 4, async ({ slot, record }) => {
        const startedAtIso = record?.started_at ?? slot.toISOString();
        const chain = await readChainSegment(contract, cameraId, startedAtIso);
        const classified = classifySegment({ cameraId, record, chain });
        const minute: VerifyMinuteResult = {
          slotIso: startedAtIso,
          status: classified.status,
          detail: classified.detail,
          record,
        };
        return minute;
      });
      const report: VerifyReport = {
        overall: aggregateStatus(results.map((result) => result.status)),
        results,
        scope,
        source: "verify",
      };
      if (activity !== activitySeq.current) {
        return;
      }
      setVerifyReport(report);
      try {
        await createVerificationAttempt(cameraId, {
          started_at: range.startedAt,
          ended_at: range.endedAt,
          scope,
          overall_status: report.overall,
          minutes: results.map((result) => ({
            started_at: result.slotIso,
            status: result.status,
            detail: result.detail,
            video_record_id: result.record?.id ?? null,
          })),
        });
        if (activity !== activitySeq.current) {
          return;
        }
        setHistoryTick((tick) => tick + 1);
      } catch (persistError) {
        if (activity !== activitySeq.current) {
          return;
        }
        if (persistError instanceof CamerasApiError) {
          showToast(persistError.message, "error");
        } else {
          showToast(
            "Could not save this verification to the audit trail.",
            "error"
          );
        }
      }
    } catch (error) {
      if (activity !== activitySeq.current) {
        return;
      }
      if (error instanceof CamerasApiError) {
        showToast(error.message, "error");
      } else {
        showToast(networkErrorMessage(), "error");
      }
    } finally {
      setVerifying(false);
    }
  }

  function verifyAppliedRange() {
    if (!applied.startedAt || !applied.endedAt) {
      showToast(
        "Choose a date and time range, then verify that recording.",
        "error"
      );
      return;
    }
    void runVerify({
      startedAt: applied.startedAt,
      endedAt: applied.endedAt,
    }, undefined, "full");
  }

  function resolvePartialWindow(): { startedAt: string; endedAt: string } | null {
    if (!applied.startedAt || !applied.endedAt) {
      showToast(
        "Choose a date and time range, then pick a part of that recording.",
        "error"
      );
      return null;
    }
    if (!partialStart.trim() || !partialEnd.trim()) {
      showToast(
        "Choose a start and end time inside the searched range.",
        "error"
      );
      return null;
    }
    const date = isoToLocalDate(applied.startedAt);
    const startedAt = localDateTimeToIso(date, partialStart);
    const endedAt = localDateTimeToIso(date, partialEnd);
    if (!startedAt || !endedAt || Date.parse(endedAt) <= Date.parse(startedAt)) {
      showToast("Choose an end time after the start time.", "error");
      return null;
    }
    const clipped = clipSubRange(
      { startedAt: applied.startedAt, endedAt: applied.endedAt },
      { startedAt, endedAt }
    );
    if (clipped === "invalid") {
      showToast("Choose an end time after the start time.", "error");
      return null;
    }
    if (clipped === "outside") {
      showToast(
        "Choose a start and end inside the searched date and time range.",
        "error"
      );
      return null;
    }
    return clipped;
  }

  function verifyPartialRange() {
    const window = resolvePartialWindow();
    if (!window) {
      return;
    }
    void runVerify(window, undefined, "partial");
  }

  function verifyOne(record: VideoRecordPublic) {
    void runVerify(
      { startedAt: record.started_at, endedAt: record.ended_at },
      [record],
      "minute"
    );
  }

  async function runDownload(
    range: { startedAt: string; endedAt: string },
    scope: "full" | "partial" | "minute",
    records: VideoRecordPublic[]
  ) {
    watchAbort.current?.abort();
    downloadAbort.current?.abort();
    const controller = new AbortController();
    downloadAbort.current = controller;
    const activity = ++activitySeq.current;
    setDownloading(true);
    setVerifyReport(null);
    try {
      const result = await downloadRecordings(cameraId, range, controller.signal);
      if (activity !== activitySeq.current) {
        return;
      }
      setVerifyReport(downloadVerifyReport(result.report, scope, records));
      saveRecordingDownload(result.video, result.filename);
      if (result.report.discontinuous || result.report.overall !== "verified") {
        showToast(result.report.detail, "error");
      }
    } catch (error) {
      if (activity !== activitySeq.current || controller.signal.aborted) {
        return;
      }
      if (error instanceof DownloadVerificationError) {
        setVerifyReport(downloadVerifyReport(error.report, scope, records));
        showToast(error.report.detail, "error");
        return;
      }
      if (error instanceof CamerasApiError) {
        showToast(error.message, "error");
      } else {
        showToast(networkErrorMessage(), "error");
      }
    } finally {
      if (activity === activitySeq.current) {
        setDownloading(false);
      }
    }
  }

  function downloadAppliedRange() {
    if (!applied.startedAt || !applied.endedAt) {
      showToast(
        "Choose a date and time range, then download that recording.",
        "error"
      );
      return;
    }
    void runDownload(
      {
        startedAt: applied.startedAt,
        endedAt: applied.endedAt,
      },
      "full",
      items
    );
  }

  function downloadPartialRange() {
    const window = resolvePartialWindow();
    if (!window) {
      return;
    }
    void runDownload(window, "partial", items);
  }

  function downloadOne(record: VideoRecordPublic) {
    const records = items.some((item) => item.id === record.id)
      ? items
      : [...items, record];
    void runDownload(
      {
        startedAt: record.started_at,
        endedAt: record.ended_at,
      },
      "minute",
      records
    );
  }

  const busy = verifying || downloading;
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
            lang="en-GB"
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
            lang="en-GB"
            value={endInput}
            onChange={(event) => setEndInput(event.target.value)}
            className={ui.input}
          />
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="submit" className={ui.btnPrimary}>
            Search
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={verifyAppliedRange}
            className={ui.btnSecondary}
          >
            {verifying ? "Verifying…" : "Verify"}
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={downloadAppliedRange}
            className={ui.btnSecondary}
          >
            {downloading ? "Downloading…" : "Download"}
          </button>
          <button type="button" onClick={clearSearch} className={ui.btnSecondary}>
            Clear
          </button>
        </div>
      </form>

      {applied.startedAt && applied.endedAt ? (
        <div
          className={`grid gap-3 sm:grid-cols-2 lg:grid-cols-4 lg:items-end ${ui.panel}`}
        >
          <p className={`sm:col-span-2 lg:col-span-4 text-left ${ui.muted}`}>
            Use part of this range. Minutes outside the times below are not
            verified or downloaded.
          </p>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="verify-part-start" className={ui.hint}>
              Part start
            </label>
            <input
              id="verify-part-start"
              type="time"
              lang="en-GB"
              value={partialStart}
              onChange={(event) => setPartialStart(event.target.value)}
              className={ui.input}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="verify-part-end" className={ui.hint}>
              Part end
            </label>
            <input
              id="verify-part-end"
              type="time"
              lang="en-GB"
              value={partialEnd}
              onChange={(event) => setPartialEnd(event.target.value)}
              className={ui.input}
            />
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              disabled={busy}
              onClick={verifyPartialRange}
              className={ui.btnSecondary}
            >
              {verifying ? "Verifying…" : "Verify part"}
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={downloadPartialRange}
              className={ui.btnSecondary}
            >
              {downloading ? "Downloading…" : "Download part"}
            </button>
          </div>
        </div>
      ) : null}

      {verifyReport ? <RecordingVerifyPanel report={verifyReport} /> : null}

      {loading ? (
        <p className={ui.muted}>Loading recordings…</p>
      ) : items.length === 0 ? (
        <p className={`${ui.panelMuted} text-left`}>{emptyMessage}</p>
      ) : (
        <ul className="space-y-3">
          {items.map((record) => {
            const rowStatus = statusForRecord(verifyReport, record.id);
            return (
              <li key={record.id} className={ui.panel}>
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0 space-y-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="font-medium text-landing-ink">
                      {formatLocalWindow(record.started_at, record.ended_at)}
                    </p>
                    {rowStatus ? <VerifyBadge status={rowStatus} /> : null}
                  </div>
                  <p className={`break-all ${ui.hint}`}>CID {record.ipfs_cid}</p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => openWatch(record)}
                    className={ui.btnCompact}
                  >
                    {watchPendingId === record.id ? "Verifying…" : "Watch"}
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => downloadOne(record)}
                    className={ui.btnCompact}
                  >
                    Download
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => verifyOne(record)}
                    className={ui.btnCompact}
                  >
                    Verify
                  </button>
                </div>
              </div>
            </li>
            );
          })}
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

      <VerificationHistory cameraId={cameraId} refreshKey={historyTick} />

      {watching && watchSrc ? (
        <RecordingPlayer
          record={watching}
          src={watchSrc}
          onClose={closeWatch}
          onPlaybackError={handlePlaybackError}
        />
      ) : null}
    </section>
  );
}

function RecordingPlayer({
  record,
  src,
  onClose,
  onPlaybackError,
}: {
  record: VideoRecordPublic;
  src: string;
  onClose: () => void;
  onPlaybackError: () => void;
}) {
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onClose();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-landing-ink/40 p-4"
      role="presentation"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="recording-player-title"
        className={`${ui.panel} w-full max-w-3xl`}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h3 id="recording-player-title" className={ui.sectionTitle}>
              Watch recording
            </h3>
            <p className={`mt-1 ${ui.muted}`}>
              {formatLocalWindow(record.started_at, record.ended_at)}
            </p>
          </div>
          <button type="button" onClick={onClose} className={ui.btnSecondary}>
            Close
          </button>
        </div>
        <video
          key={record.id}
          controls
          autoPlay
          playsInline
          className="w-full rounded-md bg-landing-ink"
          onError={onPlaybackError}
        >
          <source src={src} type="video/mp4" />
        </video>
      </div>
    </div>
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

function isoToLocalDate(iso: string): string {
  const parsed = new Date(iso);
  const year = parsed.getFullYear();
  const month = String(parsed.getMonth() + 1).padStart(2, "0");
  const day = String(parsed.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function isoToLocalTime(iso: string): string {
  const parsed = new Date(iso);
  const hours = String(parsed.getHours()).padStart(2, "0");
  const minutes = String(parsed.getMinutes()).padStart(2, "0");
  return `${hours}:${minutes}`;
}

function downloadVerifyReport(
  report: DownloadVerification,
  scope: "full" | "partial" | "minute",
  records: VideoRecordPublic[]
): VerifyReport {
  const byId = new Map(records.map((record) => [record.id, record]));
  const segments: VerifyMinuteResult[] = report.segments.map((segment) => {
    const known = byId.get(segment.video_record_id) ?? null;
    const record =
      known ??
      (segment.tx_hash
        ? {
            id: segment.video_record_id,
            camera_id: "",
            started_at: segment.started_at,
            ended_at: segment.ended_at,
            ipfs_cid: "",
            segment_hash: "",
            tx_hash: segment.tx_hash,
          }
        : null);
    return {
      slotIso: segment.started_at,
      endedAt: segment.ended_at,
      status: segment.status,
      detail: segment.detail,
      record,
      entry: "segment" as const,
    };
  });
  const gaps: VerifyMinuteResult[] = report.missing_intervals.map((interval) => ({
    slotIso: interval.started_at,
    endedAt: interval.ended_at,
    status: "missing" as const,
    detail: interval.detail,
    record: null,
    entry: "gap" as const,
  }));
  return {
    overall: report.overall,
    results: [...segments, ...gaps].sort(
      (left, right) => Date.parse(left.slotIso) - Date.parse(right.slotIso)
    ),
    scope,
    source: "download",
    detail: report.detail,
  };
}

function verifiedWatchReport(record: VideoRecordPublic): VerifyReport {
  return {
    overall: "verified",
    scope: "minute",
    results: [
      {
        slotIso: record.started_at,
        endedAt: record.ended_at,
        status: "verified",
        detail: "Metadata and file content match the blockchain anchor.",
        record,
      },
    ],
  };
}

function deniedWatchReport(
  record: VideoRecordPublic,
  denial: PlaybackDenial
): VerifyReport {
  const segments = denial.segments.map((segment) => ({
    slotIso: segment.started_at,
    endedAt: segment.ended_at,
    status: segment.status,
    detail: segment.detail,
    record: segment.video_record_id === record.id ? record : null,
  }));
  const gaps = denial.missing_intervals.map((interval) => ({
    slotIso: interval.started_at,
    endedAt: interval.ended_at,
    status: "missing" as const,
    detail: interval.detail,
    record: null,
  }));
  return {
    overall: denial.overall,
    scope: "minute",
    results: [...segments, ...gaps],
  };
}

function statusForRecord(report: VerifyReport | null, recordId: string) {
  return report?.results.find((result) => result.record?.id === recordId)?.status;
}
