"use client";

import {
  useEffect,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from "react";

import {
  openPlayback,
  reducePlayback,
  type MediaSlice,
  type PlaybackEffect,
  type PlaybackEvent,
  type PlaybackMachine,
  type PlaybackPhase,
} from "@/lib/playback-controller";
import type { PlaybackSequence, PlaySlice } from "@/lib/playback-sequence";
import {
  fetchRecordingPlayback,
  PlaybackVerificationError,
  type PlaybackDenial,
  type VideoRecordPublic,
} from "@/lib/recordings-api";
import {
  logPlaybackTiming,
  playbackTimingForRecord,
} from "@/lib/playback-timing";
import { ui } from "@/lib/ui";
import {
  formatLocalWindow,
  formatLocalWindowParts,
  missingRecordingMessage,
} from "@/lib/verify-recordings";

type ContinuousPlaybackProps = {
  sectionRef: RefObject<HTMLElement | null>;
  cameraId: string;
  sequence: PlaybackSequence;
  signal?: AbortSignal;
  generation: number;
  startupTimingId?: string;
  downloading: boolean;
  busy: boolean;
  onClose: () => void;
  onDownload: () => void;
  onPlaybackError: () => void;
  onPlayingChange: (playing: boolean) => void;
  onActiveRecord: (recordId: string | null) => void;
  onSegmentBlocked: (
    record: VideoRecordPublic,
    denial: PlaybackDenial,
    generation: number
  ) => void;
};

type Failure = {
  detail: string;
  denial: PlaybackDenial | null;
};

type Interruption = {
  id: string;
  startedAt: string;
  endedAt: string;
  detail: string;
};

const SEEK_TOLERANCE_SECONDS = 0.45;

export function ContinuousPlayback({
  sectionRef,
  cameraId,
  sequence,
  signal,
  generation,
  startupTimingId,
  downloading,
  busy,
  onClose,
  onDownload,
  onPlaybackError,
  onPlayingChange,
  onActiveRecord,
  onSegmentBlocked,
}: ContinuousPlaybackProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const sequenceRef = useRef(sequence);
  const machine = useRef<PlaybackMachine>(
    openPlayback(toMedia(sequence), sequence.startSeconds).state
  );
  const sessionAbort = useRef<AbortController | null>(null);
  const byRecord = useRef(new Map<string, string>());
  const byCid = useRef(new Map<string, string>());
  const inflight = useRef(new Map<string, Promise<string | null>>());
  const denied = useRef(new Map<string, Failure>());
  const reported = useRef(new Set<string>());
  const pendingSeek = useRef<{ command: number; mediaTime: number } | null>(
    null
  );
  const mounted = useRef(true);
  const generationRef = useRef(generation);
  const startupTimingIdRef = useRef(startupTimingId);
  const startupTimingPending = useRef(true);
  const onSegmentBlockedRef = useRef(onSegmentBlocked);
  const onPlaybackErrorRef = useRef(onPlaybackError);
  const cameraIdRef = useRef(cameraId);
  const runEffectRef = useRef<(effect: PlaybackEffect) => void>(() => {});
  const [phase, setPhase] = useState<PlaybackPhase>(machine.current.phase);
  const [index, setIndex] = useState(machine.current.index);
  const [elapsed, setElapsed] = useState(machine.current.elapsed);
  const [scrub, setScrub] = useState<number | null>(null);
  const [interruptions, setInterruptions] = useState<Interruption[]>([]);

  sequenceRef.current = sequence;
  generationRef.current = generation;
  startupTimingIdRef.current = startupTimingId;
  onSegmentBlockedRef.current = onSegmentBlocked;
  onPlaybackErrorRef.current = onPlaybackError;
  cameraIdRef.current = cameraId;

  const slice = sequence.slices[index];
  const windowLabel = formatLocalWindow(sequence.startedAt, sequence.endedAt);
  const windowParts = formatLocalWindowParts(
    sequence.startedAt,
    sequence.endedAt
  );
  const totalSeconds = sequence.slices.reduce(
    (sum, item) => sum + Math.max(0, item.endSeconds - item.offsetSeconds),
    0
  );

  function publish(state: PlaybackMachine) {
    if (!mounted.current) {
      return;
    }
    setPhase(state.phase);
    setIndex(state.index);
    setElapsed(state.elapsed);
    if (
      (state.phase === "playing" || state.phase === "paused") &&
      state.positioned
    ) {
      const next = sequenceRef.current.slices[state.index + 1];
      if (next) {
        void verifySlice(next);
      }
    }
  }

  function dispatch(event: PlaybackEvent) {
    const result = reducePlayback(
      machine.current,
      event,
      toMedia(sequenceRef.current)
    );
    machine.current = result.state;
    publish(result.state);
    runEffectRef.current(result.effect);
  }

  function rememberBlock(sliceToReport: PlaySlice, failure: Failure) {
    if (reported.current.has(sliceToReport.record.id)) {
      return;
    }
    reported.current.add(sliceToReport.record.id);
    setInterruptions((current) => [
      ...current,
      {
        id: sliceToReport.record.id,
        startedAt: sliceToReport.record.started_at,
        endedAt: sliceToReport.record.ended_at,
        detail: failure.detail,
      },
    ]);
    if (failure.denial) {
      onSegmentBlockedRef.current(
        sliceToReport.record,
        failure.denial,
        generationRef.current
      );
    }
  }

  function verifySlice(
    target: PlaySlice,
    timingId?: string
  ): Promise<string | null> {
    const id = target.record.id;
    const ready = byRecord.current.get(id);
    if (ready) {
      return Promise.resolve(ready);
    }
    const pending = inflight.current.get(id);
    if (pending) {
      return pending;
    }
    if (denied.current.has(id)) {
      return Promise.resolve(null);
    }
    const requestSignal = sessionAbort.current?.signal;
    const task = fetchRecordingPlayback(
      cameraIdRef.current,
      id,
      requestSignal,
      timingId
    )
      .then((blob) => {
        if (requestSignal?.aborted) {
          throw new DOMException("The operation was aborted.", "AbortError");
        }
        if (!blob) {
          return null;
        }
        const cid = target.record.ipfs_cid.trim();
        let url = byCid.current.get(cid);
        if (!url) {
          url = URL.createObjectURL(blob);
          byCid.current.set(cid, url);
        }
        byRecord.current.set(id, url);
        return url;
      })
      .catch((error: unknown) => {
        if (isAbortError(error)) {
          throw error;
        }
        const denial =
          error instanceof PlaybackVerificationError ? error.denial : null;
        const detail =
          denial?.detail ||
          (error instanceof Error && error.message
            ? error.message
            : "Could not play this part.");
        const failure = { detail, denial };
        denied.current.set(id, failure);
        rememberBlock(target, failure);
        return null;
      })
      .finally(() => {
        if (inflight.current.get(id) === task) {
          inflight.current.delete(id);
        }
      });
    inflight.current.set(id, task);
    return task;
  }

  function seekOrReady(
    video: HTMLVideoElement,
    command: number,
    mediaTime: number
  ) {
    if (machine.current.command !== command) {
      return;
    }
    const closeEnough =
      video.readyState >= 1 &&
      !video.seeking &&
      Math.abs(video.currentTime - mediaTime) <= SEEK_TOLERANCE_SECONDS;
    if (closeEnough) {
      pendingSeek.current = null;
      dispatch({ type: "positioned", command, currentTime: video.currentTime });
      return;
    }
    pendingSeek.current = { command, mediaTime };
    video.currentTime = mediaTime;
    if (
      !video.seeking &&
      Math.abs(video.currentTime - mediaTime) <= SEEK_TOLERANCE_SECONDS
    ) {
      pendingSeek.current = null;
      dispatch({ type: "positioned", command, currentTime: video.currentTime });
    }
  }

  async function show(effect: Extract<PlaybackEffect, { type: "show" }>) {
    const target = sequenceRef.current.slices[effect.index];
    if (!target) {
      return;
    }
    let url: string | null = null;
    const startupId = startupTimingPending.current
      ? startupTimingIdRef.current
      : undefined;
    startupTimingPending.current = false;
    try {
      url = await verifySlice(target, startupId);
    } catch (error) {
      if (isAbortError(error)) {
        return;
      }
      url = null;
    }
    if (machine.current.command !== effect.command) {
      return;
    }
    if (!url || !url.startsWith("blob:")) {
      const failure = denied.current.get(target.record.id);
      if (failure && !failure.denial) {
        onPlaybackErrorRef.current();
      }
      dispatch({
        type: "load-failed",
        command: effect.command,
        index: effect.index,
      });
      return;
    }
    const video = videoRef.current;
    if (!video) {
      return;
    }
    video.pause();
    const timingId = playbackTimingForRecord(target.record.id) ?? startupId;
    if (!sameSource(video, url)) {
      pendingSeek.current = {
        command: effect.command,
        mediaTime: effect.mediaTime,
      };
      if (timingId) {
        logPlaybackTiming(timingId, "src-assigned", performance.now(), {
          recordId: target.record.id,
        });
      }
      video.src = url;
      return;
    }
    seekOrReady(video, effect.command, effect.mediaTime);
  }

  runEffectRef.current = (effect) => {
    const video = videoRef.current;
    if (effect.type === "show") {
      void show(effect);
      return;
    }
    if (!video) {
      return;
    }
    if (effect.type === "play") {
      void video.play().catch(() => {
        if (machine.current.command === effect.command) {
          dispatch({ type: "play-rejected", command: effect.command });
        }
      });
      return;
    }
    if (effect.type === "pause") {
      video.pause();
    }
  };

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    const local = new AbortController();
    sessionAbort.current = local;
    const onParentAbort = () => local.abort();
    if (signal?.aborted) {
      local.abort();
    } else {
      signal?.addEventListener("abort", onParentAbort);
    }
    denied.current.clear();
    reported.current.clear();
    startupTimingPending.current = true;
    setInterruptions([]);
    pendingSeek.current = null;
    const opened = openPlayback(toMedia(sequence), sequence.startSeconds);
    machine.current = opened.state;
    publish(opened.state);
    runEffectRef.current(opened.effect);
    const video = videoRef.current;
    const urlsByCid = byCid.current;
    const urlsByRecord = byRecord.current;
    const pendingLoads = inflight.current;
    const deniedSlices = denied.current;
    return () => {
      local.abort();
      signal?.removeEventListener("abort", onParentAbort);
      if (sessionAbort.current === local) {
        sessionAbort.current = null;
      }
      const cancelled = reducePlayback(
        machine.current,
        { type: "cancel" },
        toMedia(sequenceRef.current)
      );
      machine.current = cancelled.state;
      pendingSeek.current = null;
      if (video) {
        video.pause();
        video.removeAttribute("src");
      }
      for (const url of urlsByCid.values()) {
        URL.revokeObjectURL(url);
      }
      urlsByCid.clear();
      urlsByRecord.clear();
      pendingLoads.clear();
      deniedSlices.clear();
    };
    // Restart only when the open sequence or its session ends.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sequence, signal]);

  useEffect(() => {
    onPlayingChange(phase === "playing");
  }, [onPlayingChange, phase]);

  useEffect(() => {
    onActiveRecord(slice?.record.id ?? null);
    return () => onActiveRecord(null);
  }, [onActiveRecord, slice?.record.id]);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key !== "Escape") {
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
  }, [onClose]);

  function onLoadedMetadata() {
    const activeId =
      sequenceRef.current.slices[machine.current.index]?.record.id;
    const timingId = activeId ? playbackTimingForRecord(activeId) : undefined;
    if (timingId) {
      logPlaybackTiming(timingId, "loadedmetadata");
    }
    const video = videoRef.current;
    const pending = pendingSeek.current;
    if (!video || !pending) {
      return;
    }
    seekOrReady(video, pending.command, pending.mediaTime);
  }

  function onSeeked() {
    const video = videoRef.current;
    const pending = pendingSeek.current;
    if (!video || !pending || pending.command !== machine.current.command) {
      return;
    }
    if (
      Math.abs(video.currentTime - pending.mediaTime) > SEEK_TOLERANCE_SECONDS
    ) {
      video.currentTime = pending.mediaTime;
      return;
    }
    pendingSeek.current = null;
    dispatch({
      type: "positioned",
      command: pending.command,
      currentTime: video.currentTime,
    });
  }

  function onTimeUpdate() {
    const video = videoRef.current;
    if (!video || video.seeking) {
      return;
    }
    dispatch({
      type: "time",
      command: machine.current.command,
      currentTime: video.currentTime,
    });
  }

  function onEnded() {
    const video = videoRef.current;
    if (!video) {
      return;
    }
    dispatch({
      type: "ended",
      command: machine.current.command,
      currentTime: video.currentTime,
    });
  }

  function onMediaError() {
    if (!sessionAbort.current || sessionAbort.current.signal.aborted) {
      return;
    }
    const video = videoRef.current;
    if (!video?.getAttribute("src")) {
      return;
    }
    const state = machine.current;
    if (state.phase === "loading" || state.phase === "transitioning") {
      dispatch({
        type: "load-failed",
        command: state.command,
        index: state.index,
      });
      return;
    }
    dispatch({ type: "play-rejected", command: state.command });
    onPlaybackError();
  }

  function commitScrub(value: string) {
    setScrub(null);
    const seconds = Number(value);
    if (Number.isFinite(seconds)) {
      dispatch({ type: "seek", seconds });
    }
  }

  const checking = phase === "loading" || phase === "transitioning";
  const failed = phase === "blocked";
  const playDisabled = checking || failed;

  const playLabel = phase === "playing" ? "Pause" : "Play";
  const downloadLabel = downloading ? "Downloading" : "Download";
  const bannerText = failed
    ? "Verification failed. This part was not played."
    : checking
      ? "Checking this part…"
      : phase === "ended"
        ? "Ended"
        : null;

  return (
    <section
      ref={sectionRef}
      id="open-recording"
      aria-label="Recording player"
      className={`${ui.panel} scroll-mt-6`}
    >
      <div className={ui.videoFrame} aria-busy={checking}>
        <video
          ref={videoRef}
          playsInline
          preload="auto"
          aria-label={windowLabel}
          className={ui.videoMedia}
          onClick={() => {
            if (!playDisabled) {
              dispatch({ type: "toggle" });
            }
          }}
          onError={onMediaError}
          onLoadedMetadata={onLoadedMetadata}
          onSeeked={onSeeked}
          onTimeUpdate={onTimeUpdate}
          onPlaying={() => {
            const activeId =
              sequenceRef.current.slices[machine.current.index]?.record.id;
            const timingId = activeId
              ? playbackTimingForRecord(activeId)
              : undefined;
            if (timingId) {
              logPlaybackTiming(timingId, "playing");
            }
            dispatch({ type: "playing", command: machine.current.command });
          }}
          onPause={() =>
            dispatch({ type: "paused", command: machine.current.command })
          }
          onEnded={onEnded}
        />
        <div className="pointer-events-none absolute left-2 top-2 z-10 flex max-w-[calc(100%-1rem)] flex-col gap-1 rounded-md bg-black/55 px-2 py-1.5 text-xs leading-4 text-white backdrop-blur-sm">
          <p className="flex items-center gap-1.5">
            <CalendarIcon />
            <span className="min-w-0">{windowParts.date}</span>
          </p>
          <p className="flex items-center gap-1.5">
            <ClockIcon />
            <span className="min-w-0">{windowParts.time}</span>
          </p>
        </div>
        <div className="absolute inset-x-0 bottom-0 z-20">
          <p className="sr-only" aria-live="polite">
            {phaseLabel(phase, elapsed)}
          </p>
          {bannerText ? (
            <p className="pointer-events-none bg-black/70 px-3 py-1.5 text-center text-sm text-white">
              {bannerText}
            </p>
          ) : null}
          <div className="flex flex-wrap items-center gap-2 bg-black/55 px-2 py-2 text-white backdrop-blur-sm">
            <PlayerIconButton
              label={playLabel}
              disabled={playDisabled}
              onClick={() => dispatch({ type: "toggle" })}
            >
              <PlayPauseIcon playing={phase === "playing"} />
            </PlayerIconButton>
            <p className="shrink-0 text-xs font-medium tabular-nums">
              {formatMediaTime(scrub ?? elapsed)}
              <span className="font-normal text-white/60"> / </span>
              {formatMediaTime(totalSeconds)}
            </p>
            <input
              type="range"
              min={0}
              max={Math.max(totalSeconds, 0.1)}
              step={0.1}
              value={Math.min(scrub ?? elapsed, totalSeconds || 0)}
              aria-label="Seek"
              title="Seek"
              onChange={(event) => setScrub(Number(event.target.value))}
              onPointerUp={(event) => commitScrub(event.currentTarget.value)}
              onKeyUp={(event) => commitScrub(event.currentTarget.value)}
              onBlur={(event) => {
                if (scrub !== null) {
                  commitScrub(event.currentTarget.value);
                }
              }}
              className="h-1.5 min-w-24 flex-1 cursor-pointer accent-[#1f7a4c] disabled:cursor-not-allowed"
            />
            <PlayerIconButton
              label={downloadLabel}
              disabled={busy}
              busy={downloading}
              onClick={onDownload}
            >
              <DownloadIcon />
            </PlayerIconButton>
            <PlayerIconButton label="Close" onClick={onClose}>
              <CloseIcon />
            </PlayerIconButton>
          </div>
        </div>
      </div>
      {sequence.gaps.length > 0 ? (
        <ul className="mt-3 space-y-1">
          {sequence.gaps.map((gap) => (
            <li key={`${gap.startedAt}-${gap.endedAt}`} className={ui.hint}>
              {missingRecordingMessage(gap.startedAt, gap.endedAt)}
            </li>
          ))}
        </ul>
      ) : null}
      {interruptions.length > 0 ? (
        <ul className="mt-3 space-y-1">
          {interruptions.map((interval) => (
            <li key={interval.id} className={ui.hint}>
              This part was not played:{" "}
              {formatLocalWindow(interval.startedAt, interval.endedAt)}.{" "}
              {interval.detail}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

function toMedia(sequence: PlaybackSequence): MediaSlice[] {
  return sequence.slices.map((slice) => ({
    id: slice.record.id,
    cid: slice.record.ipfs_cid.trim(),
    offsetSeconds: slice.offsetSeconds,
    endSeconds: slice.endSeconds,
  }));
}

function sameSource(video: HTMLVideoElement, url: string): boolean {
  const attr = video.getAttribute("src");
  return attr === url || video.src === url;
}

function isAbortError(error: unknown): boolean {
  return (
    (error instanceof DOMException && error.name === "AbortError") ||
    (error instanceof Error && error.name === "AbortError")
  );
}

function phaseLabel(phase: PlaybackPhase, elapsed: number): string {
  if (phase === "loading" || phase === "transitioning") {
    return "Checking the next part…";
  }
  if (phase === "playing") {
    return "Playing";
  }
  if (phase === "ended") {
    return "Ended";
  }
  if (phase === "blocked") {
    return "Verification failed";
  }
  if (elapsed < 0.5) {
    return "Ready";
  }
  return "Paused";
}

function PlayerIconButton({
  label,
  disabled,
  busy,
  onClick,
  children,
}: {
  label: string;
  disabled?: boolean;
  busy?: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      aria-busy={busy || undefined}
      disabled={disabled}
      onClick={onClick}
      className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-white transition hover:bg-white/15 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white disabled:cursor-not-allowed disabled:opacity-40"
    >
      {children}
    </button>
  );
}

function PlayPauseIcon({ playing }: { playing: boolean }) {
  return playing ? (
    <svg
      viewBox="0 0 16 16"
      aria-hidden="true"
      className="h-4 w-4 fill-current"
    >
      <rect x="3" y="2" width="3.5" height="12" rx="0.5" />
      <rect x="9.5" y="2" width="3.5" height="12" rx="0.5" />
    </svg>
  ) : (
    <svg
      viewBox="0 0 16 16"
      aria-hidden="true"
      className="h-4 w-4 fill-current"
    >
      <path d="M4 2.5v11l9-5.5-9-5.5z" />
    </svg>
  );
}

function CalendarIcon() {
  return (
    <svg
      viewBox="0 0 16 16"
      aria-hidden="true"
      className="h-3.5 w-3.5 shrink-0 stroke-current"
      fill="none"
    >
      <rect x="2.5" y="3.5" width="11" height="10" rx="1" strokeWidth="1.6" />
      <path
        d="M2.5 6.5h11M5.5 2.2v2.6M10.5 2.2v2.6"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
    </svg>
  );
}

function ClockIcon() {
  return (
    <svg
      viewBox="0 0 16 16"
      aria-hidden="true"
      className="h-3.5 w-3.5 shrink-0 stroke-current"
      fill="none"
    >
      <circle cx="8" cy="8" r="5.25" strokeWidth="1.6" />
      <path
        d="M8 5v3.2L10.3 9.6"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function DownloadIcon() {
  return (
    <svg
      viewBox="0 0 16 16"
      aria-hidden="true"
      className="h-4 w-4 stroke-current"
      fill="none"
    >
      <path
        d="M8 2.5v6.2M5.2 6.3 8 9.1l2.8-2.8M3.5 10.2V13h9v-2.8"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function CloseIcon() {
  return (
    <svg
      viewBox="0 0 16 16"
      aria-hidden="true"
      className="h-4 w-4 stroke-current"
      fill="none"
    >
      <path
        d="M3.5 3.5l9 9M12.5 3.5l-9 9"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
    </svg>
  );
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
