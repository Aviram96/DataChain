"use client";

import {
  FormEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
  type RefObject,
} from "react";

import { networkErrorMessage } from "@/lib/api";
import { CamerasApiError } from "@/lib/cameras-api";
import { ipfsGatewayUrl } from "@/lib/ipfs-gateway";
import {
  downloadRecordings,
  listAllRecordings,
  listRecordings,
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
  minuteAlreadyCovered,
  formatLocalWindow,
  formatVerifySlot,
  MAX_EXPECTED_MINUTES,
  verifyStatusMeaning,
  type VerifyMinuteResult,
  type VerifyReport,
} from "@/lib/verify-recordings";

import {
  ChainTransaction,
  RecordingVerifyPanel,
  VerifyBadge,
} from "./recording-verify-panel";
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
  const [verifying, setVerifying] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [verifyReport, setVerifyReport] = useState<VerifyReport | null>(null);
  const [historyTick, setHistoryTick] = useState(0);
  const [partialStart, setPartialStart] = useState("");
  const [partialEnd, setPartialEnd] = useState("");
  const [verifyTargetId, setVerifyTargetId] = useState<string | null>(null);
  const [mediaPlaying, setMediaPlaying] = useState(false);
  const playbackErrorFor = useRef<string | null>(null);
  const selectedRef = useRef<HTMLElement>(null);
  const scrolledForId = useRef<string | null>(null);

  const load = useCallback(
    async (pageToLoad: number, options?: { silent?: boolean }) => {
      if (!options?.silent) {
        setLoading(true);
      }
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
        if (options?.silent) {
          return;
        }
        if (error instanceof CamerasApiError) {
          showToast(error.message, "error");
        } else {
          showToast(networkErrorMessage(), "error");
        }
        setItems([]);
        setTotal(0);
      } finally {
        if (!options?.silent) {
          setLoading(false);
        }
      }
    },
    [applied, cameraId, showToast]
  );

  useEffect(() => {
    void load(page);
  }, [load, page]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      void load(page, { silent: true });
    }, 20000);
    return () => window.clearInterval(timer);
  }, [load, page]);

  useEffect(() => {
    if (!watching) {
      scrolledForId.current = null;
      return;
    }
    if (scrolledForId.current === watching.id) {
      return;
    }
    scrolledForId.current = watching.id;
    selectedRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [watching]);

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
    setMediaPlaying(false);
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

    setVerifyTargetId(
      scope === "minute" ? (recordsOverride?.[0]?.id ?? null) : null
    );
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
      const slotWork = slots.flatMap((slot) => {
        if (minuteAlreadyCovered(records, slot, range)) {
          return [];
        }
        const record = findRecordForSlot(records, slot) ?? null;
        if (record) {
          used.add(record.id);
        }
        return [{ slot, record }];
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
      };
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
        setHistoryTick((tick) => tick + 1);
      } catch (persistError) {
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
      if (error instanceof CamerasApiError) {
        showToast(error.message, "error");
      } else {
        showToast(networkErrorMessage(), "error");
      }
    } finally {
      setVerifying(false);
      setVerifyTargetId(null);
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
    playbackErrorFor.current = null;
    setWatching(record);
    void runVerify(
      { startedAt: record.started_at, endedAt: record.ended_at },
      [record],
      "minute"
    );
  }

  const onPlayingChange = useCallback((playing: boolean) => {
    setMediaPlaying(playing);
  }, []);

  async function runDownload(range: { startedAt: string; endedAt: string }) {
    setDownloading(true);
    try {
      await downloadRecordings(cameraId, range);
    } catch (error) {
      if (error instanceof CamerasApiError) {
        showToast(error.message, "error");
      } else {
        showToast(networkErrorMessage(), "error");
      }
    } finally {
      setDownloading(false);
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
    void runDownload({
      startedAt: applied.startedAt,
      endedAt: applied.endedAt,
    });
  }

  function downloadPartialRange() {
    const window = resolvePartialWindow();
    if (!window) {
      return;
    }
    void runDownload(window);
  }

  function downloadOne(record: VideoRecordPublic) {
    void runDownload({
      startedAt: record.started_at,
      endedAt: record.ended_at,
    });
  }

  const busy = verifying || downloading;
  const hasRange = Boolean(applied.startedAt || applied.endedAt);
  const emptyMessage = hasRange
    ? "No recordings match that date and time range."
    : "No one-minute clips saved for this camera yet. The 10 most recent will appear here.";
  const listSummary = recordingListSummary({
    hasRange,
    page,
    pageSize: PAGE_SIZE,
    total,
  });

  const minuteReportOnOpenClip =
    watching != null &&
    verifyReport?.scope === "minute" &&
    verifyReport.results.some((result) => result.record?.id === watching.id);
  const rangeVerifying = verifying && verifyTargetId === null;

  return (
    <div className="space-y-8">
      <SelectedRecording
        sectionRef={selectedRef}
        record={watching}
        report={verifyReport}
        checking={verifying && verifyTargetId === watching?.id}
        downloading={downloading}
        busy={busy}
        onClose={closeWatch}
        onVerify={() => {
          if (watching) {
            verifyOne(watching);
          }
        }}
        onDownload={() => {
          if (watching) {
            downloadOne(watching);
          }
        }}
        onPlaybackError={handlePlaybackError}
        onPlayingChange={onPlayingChange}
      />

      <section className="space-y-4">
      <div>
        <h2 className={`${ui.sectionTitle} text-left`}>Saved clips</h2>
        <p className={`mt-1 ${ui.pageSubtitle}`}>
          {hasRange
            ? "Clips that overlap the date and time you chose."
            : "The 10 newest one-minute clips. Search by date and time to narrow the list."}
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
            Check or download this search, or only the part between the times
            below.
          </p>
          <div className="flex flex-wrap gap-2 sm:col-span-2 lg:col-span-4">
            <button
              type="button"
              disabled={busy}
              onClick={verifyAppliedRange}
              className={ui.btnSecondary}
            >
              {rangeVerifying ? "Verifying…" : "Verify search"}
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={downloadAppliedRange}
              className={ui.btnSecondary}
            >
              {downloading ? "Downloading…" : "Download search"}
            </button>
          </div>
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
              {rangeVerifying ? "Verifying…" : "Verify part"}
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

      {verifyReport && !minuteReportOnOpenClip ? (
        <RecordingVerifyPanel report={verifyReport} />
      ) : null}

      {loading ? (
        <p className={ui.muted}>Loading recordings…</p>
      ) : items.length === 0 ? (
        <p className={`${ui.panelMuted} text-left`}>{emptyMessage}</p>
      ) : (
        <ul className="space-y-3" aria-label="Saved clips">
          {items.map((record) => {
            const rowStatus = statusForRecord(verifyReport, record.id);
            const open = watching?.id === record.id;
            return (
              <li
                key={record.id}
                aria-current={open ? "true" : undefined}
                className={`${ui.panel} ${open ? "ring-2 ring-landing-accent/35" : ""}`}
              >
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0 space-y-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="font-medium text-landing-ink">
                      {formatLocalWindow(record.started_at, record.ended_at)}
                    </p>
                    <p className={ui.hint}>
                      {clipLengthLabel(record.started_at, record.ended_at)}
                    </p>
                    {open ? (
                      <span className="text-xs font-semibold text-landing-accent">
                        {mediaPlaying ? "Playing" : "Selected"}
                      </span>
                    ) : null}
                    {rowStatus ? <VerifyBadge status={rowStatus} /> : null}
                  </div>
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
                    {verifying && verifyTargetId === record.id
                      ? "Verifying…"
                      : "Verify"}
                  </button>
                </div>
              </div>
            </li>
            );
          })}
        </ul>
      )}

      {!loading && total > 0 ? (
        <div className="flex flex-wrap items-center justify-between gap-4 border-t border-landing-ink/10 pt-4">
          <p className={ui.hint}>{listSummary}</p>
          {pages > 1 ? (
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
          ) : null}
        </div>
      ) : null}
      </section>

      <VerificationHistory cameraId={cameraId} refreshKey={historyTick} />
    </div>
  );
}

function SelectedRecording({
  sectionRef,
  record,
  report,
  checking,
  downloading,
  busy,
  onClose,
  onVerify,
  onDownload,
  onPlaybackError,
  onPlayingChange,
}: {
  sectionRef: RefObject<HTMLElement | null>;
  record: VideoRecordPublic | null;
  report: VerifyReport | null;
  checking: boolean;
  downloading: boolean;
  busy: boolean;
  onClose: () => void;
  onVerify: () => void;
  onDownload: () => void;
  onPlaybackError: () => void;
  onPlayingChange: (playing: boolean) => void;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [position, setPosition] = useState<{
    current: number;
    duration: number | null;
  }>({ current: 0, duration: null });
  const [playing, setPlaying] = useState(false);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key !== "Escape" || !record) {
        return;
      }
      const target = event.target;
      if (
        target instanceof HTMLInputElement ||
        target instanceof HTMLTextAreaElement ||
        target instanceof HTMLSelectElement
      ) {
        return;
      }
      onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, record]);

  useEffect(() => {
    setPosition({ current: 0, duration: null });
    setPlaying(false);
  }, [record?.id]);

  useEffect(() => {
    onPlayingChange(playing);
  }, [onPlayingChange, playing]);

  useEffect(() => {
    return () => onPlayingChange(false);
  }, [onPlayingChange]);

  function syncPosition() {
    const video = videoRef.current;
    if (!video) {
      return;
    }
    setPosition({
      current: video.currentTime,
      duration: Number.isFinite(video.duration) ? video.duration : null,
    });
  }

  const clipStatus = record
    ? statusForRecord(checking ? null : report, record.id)
    : undefined;
  const windowLabel = record
    ? formatLocalWindow(record.started_at, record.ended_at)
    : "";
  const cid = record?.ipfs_cid.trim() ?? "";

  return (
    <section
      ref={sectionRef}
      id="open-recording"
      aria-labelledby="open-recording-title"
      className={`${ui.panel} scroll-mt-6`}
    >
      <h2 id="open-recording-title" className={ui.sectionTitle}>
        This recording
      </h2>
      {record ? (
        <div className="mt-3 space-y-4">
          <div>
            <p className="text-base font-medium text-landing-ink">{windowLabel}</p>
            <p className={`mt-1 ${ui.muted}`}>
              {clipLengthLabel(record.started_at, record.ended_at)} saved
            </p>
          </div>

          {cid ? (
            <video
              key={record.id}
              ref={videoRef}
              controls
              autoPlay
              playsInline
              aria-label={windowLabel}
              className="w-full rounded-md bg-landing-ink"
              onError={onPlaybackError}
              onLoadedMetadata={syncPosition}
              onDurationChange={syncPosition}
              onTimeUpdate={syncPosition}
              onSeeked={syncPosition}
              onPlay={() => {
                setPlaying(true);
                syncPosition();
              }}
              onPause={() => {
                setPlaying(false);
                syncPosition();
              }}
              onEnded={() => {
                setPlaying(false);
                syncPosition();
              }}
            >
              <source src={ipfsGatewayUrl(cid)} type="video/mp4" />
            </video>
          ) : (
            <p className={ui.muted}>
              This clip has no file address, so it cannot be played.
            </p>
          )}

          <PlaybackPosition
            current={position.current}
            duration={position.duration}
            playing={playing}
            windowLabel={windowLabel}
            canPlay={Boolean(cid)}
          />

          <div>
            <h3 className="text-sm font-semibold text-landing-ink">
              Evidence for this clip
            </h3>
            <dl className="mt-3 space-y-3">
              <div>
                <dt className={ui.hint}>Time window</dt>
                <dd className="text-sm text-landing-ink/85">{windowLabel}</dd>
              </div>
              <div>
                <dt className={ui.hint}>Duration</dt>
                <dd className="text-sm text-landing-ink/85">
                  {clipLengthLabel(record.started_at, record.ended_at)}
                </dd>
              </div>
              <div>
                <dt className={ui.hint}>IPFS CID</dt>
                <dd className="mt-0.5 break-all font-mono text-xs leading-relaxed text-landing-ink/85">
                  {cid || "—"}
                </dd>
                <p className={`mt-0.5 ${ui.hint}`}>Address of this file in storage.</p>
              </div>
              <div>
                <dt className={ui.hint}>Segment hash</dt>
                <dd className="mt-0.5 break-all font-mono text-xs leading-relaxed text-landing-ink/85">
                  {record.segment_hash.trim() || "—"}
                </dd>
                <p className={`mt-0.5 ${ui.hint}`}>Fingerprint of this minute.</p>
              </div>
              <div>
                <dt className={ui.hint}>Transaction</dt>
                <dd className="mt-0.5">
                  <ChainTransaction txHash={record.tx_hash} />
                </dd>
              </div>
            </dl>
          </div>

          <div className="rounded-xl border border-landing-ink/10 bg-white/70 p-3">
            <p className={ui.hint}>Check</p>
            {checking ? (
              <p className={`mt-1 ${ui.muted}`}>
                Checking this clip against the chain…
              </p>
            ) : clipStatus ? (
              <div className="mt-1 space-y-2">
                <VerifyBadge status={clipStatus} />
                <p className={ui.muted}>{verifyStatusMeaning(clipStatus)}</p>
                {report?.scope === "minute" && report.results.length > 1 ? (
                  <ul className="space-y-2">
                    {report.results.map((result) => (
                      <li
                        key={`${result.slotIso}-${result.record?.id ?? "gap"}`}
                        className="flex flex-wrap items-center justify-between gap-2"
                      >
                        <span className="text-sm text-landing-ink/85">
                          {formatVerifySlot(result.slotIso, result.record?.ended_at)}
                        </span>
                        <VerifyBadge status={result.status} />
                      </li>
                    ))}
                  </ul>
                ) : null}
              </div>
            ) : (
              <p className={`mt-1 ${ui.muted}`}>
                Not checked yet. Verify this clip to see whether it matches the
                chain.
              </p>
            )}
          </div>

          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              disabled={busy}
              onClick={onVerify}
              className={ui.btnPrimary}
            >
              {checking ? "Verifying…" : "Verify"}
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={onDownload}
              className={ui.btnSecondary}
            >
              {downloading ? "Downloading…" : "Download"}
            </button>
            <button type="button" onClick={onClose} className={ui.btnSecondary}>
              Close
            </button>
          </div>
        </div>
      ) : (
        <p className={`mt-2 ${ui.muted}`}>
          No clip is open. Choose Watch on a saved minute below. The picture,
          the time, and the proof for that minute show up here.
        </p>
      )}
    </section>
  );
}

function PlaybackPosition({
  current,
  duration,
  playing,
  windowLabel,
  canPlay,
}: {
  current: number;
  duration: number | null;
  playing: boolean;
  windowLabel: string;
  canPlay: boolean;
}) {
  const percent =
    duration && duration > 0
      ? Math.min(100, Math.max(0, (current / duration) * 100))
      : 0;
  const totalLabel = duration == null ? "—" : formatMediaTime(duration);

  return (
    <div>
      <p className={ui.hint}>Playback</p>
      <p className="mt-1 text-base font-medium tabular-nums text-landing-ink">
        {canPlay ? formatMediaTime(current) : "—"}
        <span className="font-normal text-landing-ink/45"> / </span>
        {canPlay ? totalLabel : "—"}
      </p>
      <div
        className="mt-2 h-1.5 overflow-hidden rounded-full bg-landing-ink/10"
        aria-hidden
      >
        <div
          className="h-full rounded-full bg-landing-accent"
          style={{ width: `${percent}%` }}
        />
      </div>
      <p className={`mt-2 ${ui.muted}`}>
        {canPlay ? (playing ? "Playing" : "Paused") : "Not playing"}
        {" · "}
        {windowLabel}. Highlighted in the list below.
      </p>
    </div>
  );
}

function recordingListSummary(input: {
  hasRange: boolean;
  page: number;
  pageSize: number;
  total: number;
}): string {
  const start = (input.page - 1) * input.pageSize + 1;
  const end = Math.min(input.page * input.pageSize, input.total);
  if (input.hasRange) {
    return `Showing ${start}–${end} of ${input.total} clips in this search.`;
  }
  if (input.total <= input.pageSize) {
    const noun = input.total === 1 ? "clip" : "clips";
    return `Showing ${input.total} most recent one-minute ${noun}.`;
  }
  if (input.page === 1) {
    return `Showing the ${input.pageSize} most recent of ${input.total} one-minute clips.`;
  }
  return `Showing ${start}–${end} of ${input.total} one-minute clips, newest first.`;
}

function formatMediaTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) {
    return "—";
  }
  const total = Math.floor(seconds);
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  return `${minutes}:${String(rest).padStart(2, "0")}`;
}

function clipLengthLabel(startedAt: string, endedAt: string): string {
  const seconds = Math.round(
    (new Date(endedAt).getTime() - new Date(startedAt).getTime()) / 1000
  );
  if (!Number.isFinite(seconds) || seconds <= 0) {
    return "One segment";
  }
  if (seconds >= 50 && seconds <= 70) {
    return "1 minute";
  }
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  if (minutes > 0 && rest === 0) {
    return `${minutes} minute${minutes === 1 ? "" : "s"}`;
  }
  if (minutes > 0) {
    return `${minutes} min ${rest} sec`;
  }
  return `${seconds} sec`;
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

function statusForRecord(report: VerifyReport | null, recordId: string) {
  return report?.results.find((result) => result.record?.id === recordId)?.status;
}
