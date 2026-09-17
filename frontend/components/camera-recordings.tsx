"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";

import { networkErrorMessage } from "@/lib/api";
import { CamerasApiError } from "@/lib/cameras-api";
import { ipfsGatewayUrl } from "@/lib/ipfs-gateway";
import {
  listAllRecordings,
  listRecordings,
  type VideoRecordPublic,
} from "@/lib/recordings-api";
import { ui } from "@/lib/ui";
import { createDatachainContract, mapPool, readChainSegment } from "@/lib/verify-chain";
import {
  aggregateStatus,
  classifySegment,
  clipSubRange,
  expectedMinuteStarts,
  findRecordForSlot,
  MAX_EXPECTED_MINUTES,
  type VerifyMinuteResult,
  type VerifyReport,
} from "@/lib/verify-recordings";

import { RecordingVerifyPanel, VerifyBadge } from "./recording-verify-panel";
import { useToast } from "./toast-provider";

const PAGE_SIZE = 10;

const COMING_SOON = "Download will be available in a later step.";

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
  const [verifying, setVerifying] = useState(false);
  const [verifyReport, setVerifyReport] = useState<VerifyReport | null>(null);
  const [partialStart, setPartialStart] = useState("");
  const [partialEnd, setPartialEnd] = useState("");
  const playbackErrorFor = useRef<string | null>(null);

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

  function openWatch(record: VideoRecordPublic) {
    const cid = record.ipfs_cid.trim();
    if (!cid) {
      showToast("This recording has no IPFS CID, so it cannot be played.", "error");
      return;
    }
    playbackErrorFor.current = null;
    setWatching(record);
  }

  function closeWatch() {
    setWatching(null);
  }

  function handlePlaybackError() {
    if (!watching || playbackErrorFor.current === watching.id) {
      return;
    }
    playbackErrorFor.current = watching.id;
    showToast(
      "Could not play this recording from IPFS. Check the gateway URL or try again.",
      "error"
    );
  }

  async function runVerify(
    range: { startedAt: string; endedAt: string },
    recordsOverride?: VideoRecordPublic[],
    scope: VerifyReport["scope"] = "full"
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
      setVerifyReport({
        overall: aggregateStatus(results.map((result) => result.status)),
        results,
        scope,
      });
    } catch (error) {
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

  function verifyPartialRange() {
    if (!applied.startedAt || !applied.endedAt) {
      showToast(
        "Choose a date and time range, then verify part of that recording.",
        "error"
      );
      return;
    }
    if (!partialStart.trim() || !partialEnd.trim()) {
      showToast(
        "Choose a start and end time inside the searched range.",
        "error"
      );
      return;
    }
    const date = isoToLocalDate(applied.startedAt);
    const startedAt = localDateTimeToIso(date, partialStart);
    const endedAt = localDateTimeToIso(date, partialEnd);
    if (!startedAt || !endedAt || Date.parse(endedAt) <= Date.parse(startedAt)) {
      showToast("Choose an end time after the start time.", "error");
      return;
    }
    const clipped = clipSubRange(
      { startedAt: applied.startedAt, endedAt: applied.endedAt },
      { startedAt, endedAt }
    );
    if (clipped === "invalid") {
      showToast("Choose an end time after the start time.", "error");
      return;
    }
    if (clipped === "outside") {
      showToast(
        "Choose a start and end inside the searched date and time range.",
        "error"
      );
      return;
    }
    void runVerify(clipped, undefined, "partial");
  }

  function verifyOne(record: VideoRecordPublic) {
    void runVerify(
      { startedAt: record.started_at, endedAt: record.ended_at },
      [record],
      "minute"
    );
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
          <button
            type="button"
            disabled={verifying}
            onClick={verifyAppliedRange}
            className={ui.btnSecondary}
          >
            {verifying ? "Verifying…" : "Verify"}
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
            Verify part of this range. Minutes outside the times below are not
            checked.
          </p>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="verify-part-start" className={ui.hint}>
              Part start
            </label>
            <input
              id="verify-part-start"
              type="time"
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
              value={partialEnd}
              onChange={(event) => setPartialEnd(event.target.value)}
              className={ui.input}
            />
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              disabled={verifying}
              onClick={verifyPartialRange}
              className={ui.btnSecondary}
            >
              {verifying ? "Verifying…" : "Verify part"}
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
                      {formatWindow(record.started_at, record.ended_at)}
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
                    disabled={verifying}
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

      {watching ? (
        <RecordingPlayer
          record={watching}
          src={ipfsGatewayUrl(watching.ipfs_cid)}
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
              {formatWindow(record.started_at, record.ended_at)}
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

function formatWindow(startedAt: string, endedAt: string): string {
  const start = new Date(startedAt);
  const end = new Date(endedAt);
  return `${start.toLocaleString()} – ${end.toLocaleTimeString()}`;
}

function statusForRecord(report: VerifyReport | null, recordId: string) {
  return report?.results.find((result) => result.record?.id === recordId)?.status;
}
