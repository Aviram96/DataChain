"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type RefObject,
} from "react";

import { networkErrorMessage } from "@/lib/api";
import { CamerasApiError } from "@/lib/cameras-api";
import {
  buildPlaybackSequence,
  contiguousRecording,
  type PlaybackSequence,
} from "@/lib/playback-sequence";
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
  minuteAlreadyCovered,
  formatLocalWindow,
  formatVerifySlot,
  MAX_EXPECTED_MINUTES,
  reportFromPlaybackDenial,
  verifyStatusMeaning,
  type VerifyMinuteResult,
  type VerifyReport,
} from "@/lib/verify-recordings";

import {
  ChainTransaction,
  RecordingVerifyPanel,
  VerifyBadge,
} from "./recording-verify-panel";
import { ContinuousPlayback } from "./continuous-playback";
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
  const [dayRecords, setDayRecords] = useState<VideoRecordPublic[]>([]);
  const [timesReady, setTimesReady] = useState(false);
  const [opening, setOpening] = useState(false);
  const [stretch, setStretch] = useState<PlaybackSequence | null>(null);
  const [activeStretchId, setActiveStretchId] = useState<string | null>(null);
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
  const activitySeq = useRef(0);
  const openingSeq = useRef(0);
  const verifySeq = useRef(0);
  const downloadSeq = useRef(0);
  const downloadAbort = useRef<AbortController | null>(null);
  const mediaAbort = useRef<AbortController | null>(null);
  const [playbackSession, setPlaybackSession] = useState<{
    signal: AbortSignal;
    generation: number;
  } | null>(null);

  useEffect(() => {
    return () => {
      downloadAbort.current?.abort();
      mediaAbort.current?.abort();
    };
  }, []);

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
    const marker = watching?.id ?? stretch?.startedAt ?? null;
    if (!marker) {
      scrolledForId.current = null;
      return;
    }
    if (scrolledForId.current === marker) {
      return;
    }
    scrolledForId.current = marker;
    selectedRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [stretch, watching]);

  useEffect(() => {
    setVerifyReport(null);
    if (applied.startedAt && applied.endedAt) {
      setPartialStart(applied.startedAt);
      setPartialEnd(applied.endedAt);
    } else {
      setPartialStart("");
      setPartialEnd("");
    }
  }, [applied, cameraId]);

  useEffect(() => {
    if (!dateInput) {
      setDayRecords([]);
      setTimesReady(false);
      return;
    }
    const startedAt = localDateTimeToIso(dateInput, "00:00:00");
    const next = new Date(`${dateInput}T00:00:00`);
    if (!startedAt || Number.isNaN(next.getTime())) {
      setDayRecords([]);
      setTimesReady(true);
      return;
    }
    next.setDate(next.getDate() + 1);
    let cancelled = false;
    setTimesReady(false);
    listAllRecordings(cameraId, {
      startedAt,
      endedAt: next.toISOString(),
    })
      .then((records) => {
        if (!cancelled) {
          setDayRecords(records);
        }
      })
      .catch((error) => {
        if (cancelled) {
          return;
        }
        setDayRecords([]);
        if (error instanceof CamerasApiError) {
          showToast(error.message, "error");
        } else {
          showToast(networkErrorMessage(), "error");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setTimesReady(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [cameraId, dateInput, showToast]);

  function clearSearch() {
    mediaAbort.current?.abort();
    mediaAbort.current = null;
    setPlaybackSession(null);
    setDateInput("");
    setStartInput("");
    setEndInput("");
    setPage(1);
    setStretch(null);
    setApplied({});
  }

  async function playContainingVideo(iso: string, endedAtLimit?: string) {
    const day = dateInput || localDateKey(iso);
    const dayStart = day ? localDateTimeToIso(day, "00:00:00") : null;
    const dayEnd = day ? nextLocalMidnightIso(day) : null;
    if (!iso || !dayStart || !dayEnd) {
      showToast("Choose a saved time.", "error");
      return;
    }
    const activity = ++activitySeq.current;
    const openId = ++openingSeq.current;
    downloadAbort.current?.abort();
    setOpening(true);
    try {
      const records = await listAllRecordings(cameraId, {
        startedAt: dayStart,
        endedAt: dayEnd,
      });
      if (activity !== activitySeq.current) {
        return;
      }
      const span = contiguousRecording(records, iso);
      if (!span) {
        showToast("No saved clips cover that time.", "error");
        return;
      }
      const limit = Date.parse(endedAtLimit ?? "");
      const spanStart = Date.parse(span.startedAt);
      const spanEnd = Date.parse(span.endedAt);
      const windowEnd =
        endedAtLimit &&
        Number.isFinite(limit) &&
        limit > spanStart &&
        limit < spanEnd
          ? endedAtLimit
          : span.endedAt;
      const sequence = buildPlaybackSequence(
        records,
        span.startedAt,
        windowEnd,
        iso
      );
      if (sequence.slices.length === 0) {
        showToast("No saved clips cover that time.", "error");
        return;
      }
      if (activity !== activitySeq.current) {
        return;
      }
      downloadAbort.current?.abort();
      mediaAbort.current?.abort();
      const controller = new AbortController();
      mediaAbort.current = controller;
      playbackErrorFor.current = null;
      setWatching(null);
      setVerifyReport(null);
      setPlaybackSession({ signal: controller.signal, generation: activity });
      setStretch(sequence);
      setPage(1);
      setApplied({
        startedAt: sequence.startedAt,
        endedAt: sequence.endedAt,
      });
      setStartInput(iso);
      setEndInput(windowEnd);
      setDayRecords(records);
      setTimesReady(true);
      if (day !== dateInput) {
        setDateInput(day);
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
      if (openId === openingSeq.current) {
        setOpening(false);
      }
    }
  }

  function onDateChange(value: string) {
    setDateInput(value);
    setStartInput("");
    setEndInput("");
  }

  function onStartChange(iso: string) {
    if (!iso) {
      setStartInput("");
      setEndInput("");
      return;
    }
    void playContainingVideo(iso);
  }

  function onEndChange(iso: string) {
    if (startInput && iso) {
      void playContainingVideo(startInput, iso);
    }
  }

  function closeWatch() {
    mediaAbort.current?.abort();
    mediaAbort.current = null;
    setPlaybackSession(null);
    setWatching(null);
    setStretch(null);
    setMediaPlaying(false);
  }

  function handlePlaybackError() {
    const marker = watching?.id ?? stretch?.startedAt ?? null;
    if (!marker || playbackErrorFor.current === marker) {
      return;
    }
    playbackErrorFor.current = marker;
    showToast("Could not play this recording. The file was not loaded.", "error");
  }

  function onSegmentBlocked(
    record: VideoRecordPublic,
    denial: PlaybackDenial,
    generation: number
  ) {
    if (generation !== activitySeq.current) {
      return;
    }
    setVerifyReport(reportFromPlaybackDenial(denial, record));
    showToast(denial.detail, "error");
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
    const verifyId = ++verifySeq.current;
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
      if (verifyId === verifySeq.current) {
        setVerifying(false);
        setVerifyTargetId(null);
      }
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
    const startedAt = partialStart;
    const endedAt = partialEnd;
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
    void runVerify(
      { startedAt: record.started_at, endedAt: record.ended_at },
      [record],
      "minute"
    );
  }

  const onPlayingChange = useCallback((playing: boolean) => {
    setMediaPlaying(playing);
  }, []);

  const onActiveRecord = useCallback((recordId: string | null) => {
    setActiveStretchId(recordId);
  }, []);

  async function runDownload(
    range: { startedAt: string; endedAt: string },
    scope: "full" | "partial" | "minute",
    records: VideoRecordPublic[]
  ) {
    downloadAbort.current?.abort();
    const controller = new AbortController();
    downloadAbort.current = controller;
    const downloadId = ++downloadSeq.current;
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
      if (downloadId === downloadSeq.current) {
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
      dayRecords.length > 0 ? dayRecords : items
    );
  }

  function downloadPartialRange() {
    const window = resolvePartialWindow();
    if (!window) {
      return;
    }
    void runDownload(window, "partial", dayRecords.length > 0 ? dayRecords : items);
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
  const timeChoices = boundaryChoices(dayRecords);
  const endChoices = timeChoices.filter(
    (choice) => Date.parse(choice.iso) > Date.parse(startInput)
  );
  const partChoices = timeChoices.filter((choice) => {
    if (!applied.startedAt || !applied.endedAt) {
      return false;
    }
    const instant = Date.parse(choice.iso);
    return (
      instant >= Date.parse(applied.startedAt) &&
      instant <= Date.parse(applied.endedAt)
    );
  });
  const partEndChoices = partChoices.filter(
    (choice) => Date.parse(choice.iso) > Date.parse(partialStart)
  );
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
      {stretch ? (
        <ContinuousPlayback
          sectionRef={selectedRef}
          cameraId={cameraId}
          sequence={stretch}
          signal={playbackSession?.signal}
          generation={playbackSession?.generation ?? 0}
          downloading={downloading}
          busy={busy || opening}
          onClose={closeWatch}
          onDownload={() =>
            runDownload(
              {
                startedAt: stretch.startedAt,
                endedAt: stretch.endedAt,
              },
              "full",
              dayRecords.length > 0
                ? dayRecords
                : stretch.slices.map((slice) => slice.record)
            )
          }
          onPlaybackError={handlePlaybackError}
          onPlayingChange={onPlayingChange}
          onActiveRecord={onActiveRecord}
          onSegmentBlocked={onSegmentBlocked}
        />
      ) : (
        <SelectedRecording
          cameraId={cameraId}
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
          onDenied={onSegmentBlocked}
          onPlaybackError={handlePlaybackError}
          onPlayingChange={onPlayingChange}
          generation={playbackSession?.generation ?? 0}
        />
      )}

      <section className="space-y-4">
      <div>
        <h2 className={`${ui.sectionTitle} text-left`}>Saved clips</h2>
        <p className={`mt-1 ${ui.pageSubtitle}`}>
          {hasRange
            ? "Clips inside the video you are watching."
            : "Choose a saved time to play the whole video. Each row is one minute of that video."}
        </p>
      </div>

      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (startInput) {
            void playContainingVideo(startInput, endInput || undefined);
          }
        }}
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
            onChange={(event) => onDateChange(event.target.value)}
            className={ui.input}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <label htmlFor="recording-start" className={ui.hint}>
            Time
          </label>
          <select
            id="recording-start"
            value={startInput}
            onChange={(event) => onStartChange(event.target.value)}
            disabled={!dateInput || !timesReady || timeChoices.length === 0}
            className={`${ui.select} w-full`}
          >
            <option value="">
              {!timesReady && dateInput ? "Loading saved times…" : "Choose a saved time"}
            </option>
            {timeChoices.slice(0, -1).map((choice) => (
              <option key={choice.iso} value={choice.iso}>
                {choice.label}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-1.5">
          <label htmlFor="recording-end" className={ui.hint}>
            End time
          </label>
          <select
            id="recording-end"
            value={endInput}
            onChange={(event) => onEndChange(event.target.value)}
            disabled={!startInput || endChoices.length === 0}
            className={`${ui.select} w-full`}
          >
            {!endInput ? <option value="">End of this video</option> : null}
            {endChoices.map((choice) => (
              <option key={choice.iso} value={choice.iso}>
                {choice.label}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="submit"
            disabled={opening || !startInput}
            className={ui.btnPrimary}
          >
            {opening ? "Opening…" : "Watch"}
          </button>
          <button type="button" onClick={clearSearch} className={ui.btnSecondary}>
            Clear
          </button>
        </div>
        <p className={`sm:col-span-2 lg:col-span-4 ${ui.hint}`}>
          {dateInput && timesReady && timeChoices.length === 0
            ? "No saved clips on this date."
            : "Choose a saved time to play the whole video. It starts there and continues through the last saved minute. Shorten the end time only if you want it to stop sooner."}
        </p>
      </form>

      {stretch ? (
        <div
          className={`grid gap-3 sm:grid-cols-2 lg:grid-cols-4 lg:items-end ${ui.panel}`}
        >
          <p className={`sm:col-span-2 lg:col-span-4 text-left ${ui.muted}`}>
            Verify the whole video, or only the part between the times below.
          </p>
          <div className="flex flex-wrap gap-2 sm:col-span-2 lg:col-span-4">
            <button
              type="button"
              disabled={busy}
              onClick={verifyAppliedRange}
              className={ui.btnSecondary}
            >
              {rangeVerifying ? "Verifying…" : "Verify whole video"}
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={downloadAppliedRange}
              className={ui.btnSecondary}
            >
              {downloading ? "Downloading…" : "Download whole video"}
            </button>
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="verify-part-start" className={ui.hint}>
              Part start
            </label>
            <select
              id="verify-part-start"
              value={partialStart}
              onChange={(event) => {
                const next = event.target.value;
                setPartialStart(next);
                if (Date.parse(partialEnd) <= Date.parse(next)) {
                  const later = partChoices.filter(
                    (choice) => Date.parse(choice.iso) > Date.parse(next)
                  );
                  setPartialEnd(later[later.length - 1]?.iso ?? "");
                }
              }}
              className={`${ui.select} w-full`}
            >
              {partChoices.slice(0, -1).map((choice) => (
                <option key={choice.iso} value={choice.iso}>
                  {choice.label}
                </option>
              ))}
            </select>
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="verify-part-end" className={ui.hint}>
              Part end
            </label>
            <select
              id="verify-part-end"
              value={partialEnd}
              onChange={(event) => setPartialEnd(event.target.value)}
              className={`${ui.select} w-full`}
            >
              {partEndChoices.map((choice) => (
                <option key={choice.iso} value={choice.iso}>
                  {choice.label}
                </option>
              ))}
            </select>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              disabled={busy || !partialStart || !partialEnd}
              onClick={verifyPartialRange}
              className={ui.btnSecondary}
            >
              {rangeVerifying ? "Verifying…" : "Verify this part"}
            </button>
            <button
              type="button"
              disabled={busy || !partialStart || !partialEnd}
              onClick={downloadPartialRange}
              className={ui.btnSecondary}
            >
              {downloading ? "Downloading…" : "Download this part"}
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
            const inStretch =
              stretch?.slices.some((slice) => slice.record.id === record.id) ??
              false;
            const open = watching?.id === record.id || inStretch;
            const playingRow =
              mediaPlaying &&
              (watching?.id === record.id || activeStretchId === record.id);
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
                        {playingRow ? "Playing" : inStretch ? "In this video" : "Selected"}
                      </span>
                    ) : null}
                    {rowStatus ? <VerifyBadge status={rowStatus} /> : null}
                  </div>
                </div>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    disabled={opening || !record.ipfs_cid.trim()}
                    onClick={() => {
                      if (!record.ipfs_cid.trim()) {
                        showToast(
                          "This recording has no IPFS CID, so it cannot be played.",
                          "error"
                        );
                        return;
                      }
                      void playContainingVideo(record.started_at);
                    }}
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
  cameraId,
  sectionRef,
  record,
  report,
  checking,
  downloading,
  busy,
  onClose,
  onVerify,
  onDownload,
  onDenied,
  onPlaybackError,
  onPlayingChange,
  generation,
}: {
  cameraId: string;
  sectionRef: RefObject<HTMLElement | null>;
  record: VideoRecordPublic | null;
  report: VerifyReport | null;
  checking: boolean;
  downloading: boolean;
  busy: boolean;
  onClose: () => void;
  onVerify: () => void;
  onDownload: () => void;
  onDenied: (
    record: VideoRecordPublic,
    denial: PlaybackDenial,
    generation: number
  ) => void;
  onPlaybackError: () => void;
  onPlayingChange: (playing: boolean) => void;
  generation: number;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [position, setPosition] = useState<{
    current: number;
    duration: number | null;
  }>({ current: 0, duration: null });
  const [playing, setPlaying] = useState(false);
  const [mediaUrl, setMediaUrl] = useState<string | null>(null);
  const [playbackNote, setPlaybackNote] = useState<string | null>(null);
  const onDeniedRef = useRef(onDenied);
  const onPlaybackErrorRef = useRef(onPlaybackError);
  onDeniedRef.current = onDenied;
  onPlaybackErrorRef.current = onPlaybackError;

  useEffect(() => {
    if (!record) {
      setMediaUrl(null);
      setPlaybackNote(null);
      return;
    }
    const controller = new AbortController();
    let url: string | null = null;
    let cancelled = false;
    setMediaUrl(null);
    setPlaybackNote("Checking this clip before it plays.");
    void fetchRecordingPlayback(cameraId, record.id, controller.signal)
      .then((blob) => {
        if (cancelled) {
          return;
        }
        url = URL.createObjectURL(blob);
        setMediaUrl(url);
        setPlaybackNote(null);
      })
      .catch((error: unknown) => {
        if (cancelled || controller.signal.aborted) {
          return;
        }
        if (error instanceof PlaybackVerificationError) {
          setPlaybackNote(`This part was not played. ${error.denial.detail}`);
          onDeniedRef.current(record, error.denial, generation);
          return;
        }
        setPlaybackNote("This part was not played.");
        onPlaybackErrorRef.current();
      });
    return () => {
      cancelled = true;
      controller.abort();
      const video = videoRef.current;
      if (video) {
        video.onerror = null;
        video.removeAttribute("src");
        video.load();
      }
      if (url) {
        URL.revokeObjectURL(url);
      }
    };
  }, [cameraId, generation, record]);

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

          {mediaUrl ? (
            <video
              key={mediaUrl}
              ref={videoRef}
              src={mediaUrl}
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
            />
          ) : (
            <p className={ui.muted}>{playbackNote}</p>
          )}

          <PlaybackPosition
            current={position.current}
            duration={position.duration}
            playing={playing}
            windowLabel={windowLabel}
            canPlay={Boolean(mediaUrl)}
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
          No video is open. Choose a saved time below to play the whole recording.
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

function boundaryChoices(
  records: VideoRecordPublic[]
): { iso: string; label: string }[] {
  const byInstant = new Map<number, string>();
  for (const record of records) {
    for (const iso of [record.started_at, record.ended_at]) {
      const instant = Date.parse(iso);
      if (Number.isFinite(instant) && !byInstant.has(instant)) {
        byInstant.set(instant, iso);
      }
    }
  }
  return [...byInstant.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([, iso]) => ({ iso, label: formatLocalClock(iso) }));
}

function formatLocalClock(iso: string): string {
  const parsed = new Date(iso);
  const hours = String(parsed.getHours()).padStart(2, "0");
  const minutes = String(parsed.getMinutes()).padStart(2, "0");
  const seconds = String(parsed.getSeconds()).padStart(2, "0");
  return `${hours}:${minutes}:${seconds}`;
}

function localDateKey(iso: string): string {
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) {
    return "";
  }
  const year = parsed.getFullYear();
  const month = String(parsed.getMonth() + 1).padStart(2, "0");
  const day = String(parsed.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function nextLocalMidnightIso(date: string): string | null {
  const next = new Date(`${date}T00:00:00`);
  if (Number.isNaN(next.getTime())) {
    return null;
  }
  next.setDate(next.getDate() + 1);
  return next.toISOString();
}

function localDateTimeToIso(date: string, time: string): string | null {
  const withSeconds = time.length === 5 ? `${time}:00` : time;
  const parsed = new Date(`${date}T${withSeconds}`);
  if (Number.isNaN(parsed.getTime())) {
    return null;
  }
  return parsed.toISOString();
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
  const covered = new Set(
    report.segments.map(
      (segment) =>
        `${segment.video_record_id}|${segment.started_at}|${segment.ended_at}`
    )
  );
  const excluded: VerifyMinuteResult[] = report.excluded_intervals
    .filter(
      (interval) =>
        !covered.has(
          `${interval.video_record_id}|${interval.started_at}|${interval.ended_at}`
        )
    )
    .map((interval) => ({
      slotIso: interval.started_at,
      endedAt: interval.ended_at,
      status: interval.status,
      detail: interval.detail,
      record: byId.get(interval.video_record_id) ?? null,
      entry: "segment" as const,
    }));
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
    results: [...segments, ...excluded, ...gaps].sort(
      (left, right) => Date.parse(left.slotIso) - Date.parse(right.slotIso)
    ),
    scope,
    source: "download",
    detail: report.detail,
  };
}

function statusForRecord(report: VerifyReport | null, recordId: string) {
  return report?.results.find((result) => result.record?.id === recordId)?.status;
}
