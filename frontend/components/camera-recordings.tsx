"use client";

import { useEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";

import { networkErrorMessage } from "@/lib/api";
import {
  deliverSuccessfulDownload,
  toastForFailedDownload,
} from "@/lib/download-toast";
import { CamerasApiError } from "@/lib/cameras-api";
import {
  sequenceForRequest,
  watchRangeReady,
  type PlaybackSequence,
} from "@/lib/playback-sequence";
import {
  downloadRecordings,
  DownloadVerificationError,
  listAllRecordings,
  saveRecordingDownload,
  type PlaybackDenial,
  type VideoRecordPublic,
} from "@/lib/recordings-api";
import { beginPlaybackTiming, logPlaybackTiming } from "@/lib/playback-timing";
import { ui } from "@/lib/ui";

import { ContinuousPlayback } from "./continuous-playback";
import { useToast } from "./toast-provider";

type CameraRecordingsProps = {
  cameraId: string;
};

export function CameraRecordings({ cameraId }: CameraRecordingsProps) {
  const { showToast } = useToast();
  const [dateInput, setDateInput] = useState("");
  const [startInput, setStartInput] = useState("");
  const [endInput, setEndInput] = useState("");
  const [dayRecords, setDayRecords] = useState<VideoRecordPublic[]>([]);
  const [timesReady, setTimesReady] = useState(false);
  const [opening, setOpening] = useState(false);
  const [stretch, setStretch] = useState<PlaybackSequence | null>(null);
  const [downloading, setDownloading] = useState(false);
  const playbackErrorFor = useRef<string | null>(null);
  const selectedRef = useRef<HTMLElement>(null);
  const scrolledForId = useRef<string | null>(null);
  const activitySeq = useRef(0);
  const openingSeq = useRef(0);
  const downloadSeq = useRef(0);
  const downloadAbort = useRef<AbortController | null>(null);
  const mediaAbort = useRef<AbortController | null>(null);
  const [playbackSession, setPlaybackSession] = useState<{
    signal: AbortSignal;
    generation: number;
    timingId: string;
  } | null>(null);

  useEffect(() => {
    return () => {
      downloadAbort.current?.abort();
      mediaAbort.current?.abort();
    };
  }, []);

  useEffect(() => {
    const marker = stretch?.startedAt ?? null;
    if (!marker) {
      scrolledForId.current = null;
      return;
    }
    if (scrolledForId.current === marker) {
      return;
    }
    scrolledForId.current = marker;
    selectedRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [stretch]);

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
    setStretch(null);
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
    const timingId = beginPlaybackTiming();
    logPlaybackTiming(timingId, "watch-clicked");
    downloadAbort.current?.abort();
    setOpening(true);
    const listStarted = performance.now();
    let listOpen = false;
    try {
      listOpen = true;
      logPlaybackTiming(timingId, "recording-list-started", listStarted);
      const records = await listAllRecordings(cameraId, {
        startedAt: dayStart,
        endedAt: dayEnd,
      });
      listOpen = false;
      logPlaybackTiming(timingId, "recording-list-finished", listStarted, {
        count: records.length,
      });
      if (activity !== activitySeq.current) {
        return;
      }
      const sequence = sequenceForRequest(records, iso, endedAtLimit);
      if (!sequence) {
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
      setPlaybackSession({
        signal: controller.signal,
        generation: activity,
        timingId,
      });
      setStretch(sequence);
      setStartInput(iso);
      setEndInput(endedAtLimit ?? "");
      setDayRecords(records);
      setTimesReady(true);
      if (day !== dateInput) {
        setDateInput(day);
      }
    } catch (error) {
      if (listOpen) {
        logPlaybackTiming(timingId, "recording-list-finished", listStarted, {
          outcome: "error",
        });
      }
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
    setStartInput(iso);
    if (!watchRangeReady(iso, endInput)) {
      setEndInput("");
    }
  }

  function onEndChange(iso: string) {
    setEndInput(iso);
  }

  function closeWatch() {
    mediaAbort.current?.abort();
    mediaAbort.current = null;
    setPlaybackSession(null);
    setStretch(null);
  }

  function handlePlaybackError() {
    const marker = stretch?.startedAt ?? null;
    if (!marker || playbackErrorFor.current === marker) {
      return;
    }
    playbackErrorFor.current = marker;
    showToast(
      "Could not play this recording. The file was not loaded.",
      "error"
    );
  }

  function onSegmentBlocked(
    _record: VideoRecordPublic,
    denial: PlaybackDenial,
    generation: number
  ) {
    if (generation !== activitySeq.current) {
      return;
    }
    showToast(denial.detail, "error");
  }

  async function runDownload(range: { startedAt: string; endedAt: string }) {
    downloadAbort.current?.abort();
    const controller = new AbortController();
    downloadAbort.current = controller;
    const downloadId = ++downloadSeq.current;
    const activity = ++activitySeq.current;
    setDownloading(true);
    try {
      const result = await downloadRecordings(
        cameraId,
        range,
        controller.signal
      );
      if (activity !== activitySeq.current) {
        return;
      }
      deliverSuccessfulDownload(result.report, {
        showToast: (message, variant) => {
          flushSync(() => showToast(message, variant));
        },
        save: () => saveRecordingDownload(result.video, result.filename),
      });
    } catch (error) {
      if (activity !== activitySeq.current || controller.signal.aborted) {
        return;
      }
      if (error instanceof DownloadVerificationError) {
        const notice = toastForFailedDownload(error.report.detail);
        showToast(notice.message, notice.variant);
        return;
      }
      const notice = toastForFailedDownload(
        error instanceof CamerasApiError ? error.message : networkErrorMessage()
      );
      showToast(notice.message, notice.variant);
    } finally {
      if (downloadId === downloadSeq.current) {
        setDownloading(false);
      }
    }
  }

  const timeChoices = boundaryChoices(dayRecords);
  const endChoices = timeChoices.filter(
    (choice) => Date.parse(choice.iso) > Date.parse(startInput)
  );

  return (
    <div className="mx-auto w-full max-w-5xl space-y-6">
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (watchRangeReady(startInput, endInput)) {
            void playContainingVideo(startInput, endInput);
          }
        }}
        className={`grid gap-3 sm:grid-cols-2 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)_auto] lg:items-end ${ui.panel}`}
      >
        <div className="flex flex-col gap-1.5">
          <label htmlFor="recording-date" className={ui.label}>
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
          <label htmlFor="recording-start" className={ui.label}>
            Start
          </label>
          <select
            id="recording-start"
            value={startInput}
            onChange={(event) => onStartChange(event.target.value)}
            disabled={!dateInput || !timesReady || timeChoices.length === 0}
            className={`${ui.select} w-full`}
          >
            <option value="">
              {!timesReady && dateInput
                ? "Loading saved times…"
                : "Choose a saved time"}
            </option>
            {timeChoices.slice(0, -1).map((choice) => (
              <option key={choice.iso} value={choice.iso}>
                {choice.label}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-1.5">
          <label htmlFor="recording-end" className={ui.label}>
            End
          </label>
          <select
            id="recording-end"
            value={endInput}
            onChange={(event) => onEndChange(event.target.value)}
            disabled={!startInput || endChoices.length === 0}
            className={`${ui.select} w-full`}
          >
            <option value="">Choose an end time</option>
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
            disabled={opening || !watchRangeReady(startInput, endInput)}
            className={ui.btnPrimary}
          >
            {opening ? "Opening…" : "Watch"}
          </button>
          <button
            type="button"
            onClick={clearSearch}
            className={ui.btnSecondary}
          >
            Clear
          </button>
        </div>
        <p className={`sm:col-span-2 lg:col-span-full ${ui.hint}`}>
          {dateInput && timesReady && timeChoices.length === 0
            ? "No saved clips on this date."
            : "Choose a start and an end, then press Watch. Playback covers only that range."}
        </p>
      </form>

      {stretch ? (
        <ContinuousPlayback
          sectionRef={selectedRef}
          cameraId={cameraId}
          sequence={stretch}
          signal={playbackSession?.signal}
          generation={playbackSession?.generation ?? 0}
          startupTimingId={playbackSession?.timingId}
          downloading={downloading}
          busy={downloading || opening}
          onClose={closeWatch}
          onDownload={() =>
            runDownload({
              startedAt: stretch.startedAt,
              endedAt: stretch.endedAt,
            })
          }
          onPlaybackError={handlePlaybackError}
          onPlayingChange={() => undefined}
          onActiveRecord={() => undefined}
          onSegmentBlocked={onSegmentBlocked}
        />
      ) : (
        <EmptyPlaybackStage opening={opening} />
      )}
    </div>
  );
}

function EmptyPlaybackStage({ opening }: { opening: boolean }) {
  return (
    <section
      id="open-recording"
      aria-label="Recording player"
      className={`${ui.panel} scroll-mt-6`}
    >
      <div className={ui.videoFrame} aria-busy={opening}>
        <p className="absolute inset-0 flex items-center justify-center px-6 pb-16 text-center text-sm text-white/80">
          {opening
            ? "Opening this recording…"
            : "Choose a start and an end, then press Watch."}
        </p>
        <div className="absolute inset-x-0 bottom-0 z-20 flex flex-wrap items-center gap-2 bg-black/55 px-2 py-2 text-white/70 backdrop-blur-sm">
          <button
            type="button"
            disabled
            title="Play"
            aria-label="Play"
            className="inline-flex h-9 w-9 items-center justify-center rounded-md opacity-40"
          >
            <svg
              viewBox="0 0 16 16"
              aria-hidden="true"
              className="h-4 w-4 fill-current"
            >
              <path d="M4 2.5v11l9-5.5-9-5.5z" />
            </svg>
          </button>
          <p className="shrink-0 text-xs font-medium tabular-nums">
            0:00
            <span className="font-normal text-white/60"> / </span>
            0:00
          </p>
          <input
            type="range"
            min={0}
            max={1}
            value={0}
            disabled
            aria-label="Seek"
            title="Seek"
            className="h-1.5 min-w-24 flex-1 cursor-not-allowed accent-[#1f7a4c]"
          />
        </div>
      </div>
    </section>
  );
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
