"use client";

import { useEffect, useRef, useState, type RefObject } from "react";

import { ipfsGatewayUrl } from "@/lib/ipfs-gateway";
import type { PlaybackSequence, PlaySlice } from "@/lib/playback-sequence";
import { ui } from "@/lib/ui";
import { formatLocalWindow } from "@/lib/verify-recordings";

type ContinuousPlaybackProps = {
  sectionRef: RefObject<HTMLElement | null>;
  sequence: PlaybackSequence;
  downloading: boolean;
  busy: boolean;
  onClose: () => void;
  onDownload: () => void;
  onPlaybackError: () => void;
  onPlayingChange: (playing: boolean) => void;
  onActiveRecord: (recordId: string | null) => void;
};

type Slot = 0 | 1;

type Armed = {
  sliceIndex: number;
  mediaTime: number;
  play: boolean;
  token: number;
};

type Handoff = {
  from: Slot;
  to: Slot;
  index: number;
};

const READY_STATE = 3;

export function ContinuousPlayback({
  sectionRef,
  sequence,
  downloading,
  busy,
  onClose,
  onDownload,
  onPlaybackError,
  onPlayingChange,
  onActiveRecord,
}: ContinuousPlaybackProps) {
  const videoA = useRef<HTMLVideoElement>(null);
  const videoB = useRef<HTMLVideoElement>(null);
  const sequenceRef = useRef(sequence);
  const indexRef = useRef(0);
  const slotRef = useRef<Slot>(0);
  const advancingRef = useRef(false);
  const playingRef = useRef(false);
  const slotToken = useRef<[number, number]>([0, 0]);
  const armed = useRef<[Armed | null, Armed | null]>([null, null]);
  const pendingHandoff = useRef<Handoff | null>(null);
  const [slot, setSlot] = useState<Slot>(0);
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [elapsed, setElapsed] = useState(sequence.startSeconds);
  const [scrub, setScrub] = useState<number | null>(null);
  const slice = sequence.slices[index];
  const windowLabel = formatLocalWindow(sequence.startedAt, sequence.endedAt);
  const totalSeconds = sequence.slices.reduce((sum, item) => sum + sliceSpan(item), 0);
  sequenceRef.current = sequence;
  playingRef.current = playing;

  useEffect(() => {
    const start = positionAt(sequence, sequence.startSeconds);
    indexRef.current = start.index;
    slotRef.current = 0;
    pendingHandoff.current = null;
    advancingRef.current = true;
    setSlot(0);
    setIndex(start.index);
    setElapsed(start.elapsed);
    setPlaying(false);
    for (const which of [0, 1] as const) {
      slotToken.current[which] += 1;
      armed.current[which] = null;
      const video = videoOf(which);
      if (!video) {
        continue;
      }
      video.pause();
      video.removeAttribute("src");
      video.load();
    }
    if (!sequence.slices[start.index]) {
      advancingRef.current = false;
      return;
    }
    arm(0, start.index, start.mediaTime, true);
    const ahead = differentSliceAfter(sequence, start.index);
    if (ahead >= 0) {
      arm(1, ahead, sequence.slices[ahead].offsetSeconds, false);
    }
    // The open sequence is the only restart signal. arm() reads refs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sequence]);

  useEffect(() => {
    if (index !== indexRef.current) {
      return;
    }
    warmAhead(indexRef.current);
    // Buffer the following minute after the visible minute is on screen.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [index, slot]);

  useEffect(() => {
    onPlayingChange(playing);
  }, [onPlayingChange, playing]);

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

  function videoOf(which: Slot): HTMLVideoElement | null {
    return which === 0 ? videoA.current : videoB.current;
  }

  function other(which: Slot): Slot {
    return which === 0 ? 1 : 0;
  }

  function elapsedBefore(sliceIndex: number): number {
    return sequenceRef.current.slices
      .slice(0, sliceIndex)
      .reduce((sum, item) => sum + sliceSpan(item), 0);
  }

  function arm(which: Slot, sliceIndex: number, mediaTime: number, play: boolean) {
    const nextSlice = sequenceRef.current.slices[sliceIndex];
    const video = videoOf(which);
    if (!nextSlice || !video) {
      return;
    }
    const token = ++slotToken.current[which];
    armed.current[which] = { sliceIndex, mediaTime, play, token };
    video.muted = !play;
    const url = ipfsGatewayUrl(nextSlice.record.ipfs_cid.trim());
    if (!sameSource(video, url)) {
      video.src = url;
      return;
    }
    if (video.readyState >= 1) {
      park(which);
    }
  }

  function park(which: Slot) {
    const video = videoOf(which);
    const pending = armed.current[which];
    if (!video || !pending || pending.token !== slotToken.current[which]) {
      return;
    }
    const max = Number.isFinite(video.duration)
      ? Math.max(0, video.duration - 0.05)
      : pending.mediaTime;
    const target = Math.min(Math.max(0, pending.mediaTime), max);
    if (Math.abs(video.currentTime - target) > 0.2) {
      video.currentTime = target;
      return;
    }
    if (!pending.play) {
      return;
    }
    if (pendingHandoff.current?.to === which) {
      showPrepared(which, pending.sliceIndex);
      return;
    }
    if (which !== slotRef.current) {
      return;
    }
    pending.play = false;
    video.muted = false;
    void video.play().catch(() => {
      if (slotRef.current === which) {
        advancingRef.current = false;
        setPlaying(false);
      }
    });
  }

  function showPrepared(which: Slot, sliceIndex: number) {
    const nextVideo = videoOf(which);
    if (!nextVideo) {
      advancingRef.current = false;
      pendingHandoff.current = null;
      return;
    }
    const pending = armed.current[which];
    if (pending) {
      pending.play = false;
    }
    const previous = videoOf(other(which));
    nextVideo.muted = false;
    pendingHandoff.current = null;
    indexRef.current = sliceIndex;
    slotRef.current = which;
    setIndex(sliceIndex);
    setSlot(which);
    advancingRef.current = true;
    if (previous && previous !== nextVideo && !previous.paused) {
      previous.pause();
    }
    void nextVideo.play().catch(() => {
      advancingRef.current = false;
      setPlaying(false);
    });
  }

  function readyFor(which: Slot, sliceIndex: number, mediaTime: number): boolean {
    const video = videoOf(which);
    const pending = armed.current[which];
    const nextSlice = sequenceRef.current.slices[sliceIndex];
    if (!video || !pending || !nextSlice) {
      return false;
    }
    if (pending.token !== slotToken.current[which] || pending.sliceIndex !== sliceIndex) {
      return false;
    }
    if (video.readyState < READY_STATE) {
      return false;
    }
    if (!sameSource(video, ipfsGatewayUrl(nextSlice.record.ipfs_cid.trim()))) {
      return false;
    }
    return Math.abs(video.currentTime - mediaTime) <= 0.45;
  }

  function warmAhead(fromIndex: number) {
    const ahead = differentSliceAfter(sequenceRef.current, fromIndex);
    if (ahead < 0) {
      return;
    }
    const standby = other(slotRef.current);
    const pending = armed.current[standby];
    if (pending && pending.sliceIndex === ahead && pending.token === slotToken.current[standby]) {
      return;
    }
    arm(standby, ahead, sequenceRef.current.slices[ahead].offsetSeconds, false);
  }

  function finishSlice() {
    if (advancingRef.current) {
      return;
    }
    const seq = sequenceRef.current;
    const current = indexRef.current;
    const currentSlice = seq.slices[current];
    const active = slotRef.current;
    const activeVideo = videoOf(active);
    if (!currentSlice || !activeVideo) {
      return;
    }
    const next = current + 1;
    if (next >= seq.slices.length) {
      activeVideo.pause();
      setPlaying(false);
      setElapsed(seq.slices.reduce((sum, item) => sum + sliceSpan(item), 0));
      return;
    }
    const nextSlice = seq.slices[next];
    if (nextSlice.record.ipfs_cid.trim() === currentSlice.record.ipfs_cid.trim()) {
      indexRef.current = next;
      setIndex(next);
      warmAhead(next);
      return;
    }
    const standby = other(active);
    const mediaTime = nextSlice.offsetSeconds;
    advancingRef.current = true;
    pendingHandoff.current = { from: active, to: standby, index: next };
    if (readyFor(standby, next, mediaTime)) {
      showPrepared(standby, next);
      return;
    }
    arm(standby, next, mediaTime, true);
  }

  function syncElapsed(which: Slot) {
    if (which !== slotRef.current) {
      return;
    }
    const video = videoOf(which);
    const currentSlice = sequenceRef.current.slices[indexRef.current];
    if (!video || !currentSlice || advancingRef.current || video.seeking) {
      return;
    }
    const into = Math.max(0, video.currentTime - currentSlice.offsetSeconds);
    const span = sliceSpan(currentSlice);
    setElapsed(elapsedBefore(indexRef.current) + Math.min(into, span));
    if (atSliceEnd(video, currentSlice)) {
      finishSlice();
    }
  }

  function seekTo(seconds: number) {
    const seq = sequenceRef.current;
    if (seq.slices.length === 0) {
      return;
    }
    const pos = positionAt(seq, seconds);
    setElapsed(pos.elapsed);
    const active = slotRef.current;
    const activeVideo = videoOf(active);
    pendingHandoff.current = null;
    if (
      pos.index === indexRef.current &&
      activeVideo &&
      activeVideo.readyState >= 1 &&
      activeVideo.getAttribute("src")
    ) {
      const max = Number.isFinite(activeVideo.duration)
        ? Math.max(0, activeVideo.duration - 0.05)
        : pos.mediaTime;
      activeVideo.currentTime = Math.min(pos.mediaTime, max);
      warmAhead(pos.index);
      return;
    }
    advancingRef.current = true;
    indexRef.current = pos.index;
    setIndex(pos.index);
    arm(active, pos.index, pos.mediaTime, playingRef.current);
    warmAhead(pos.index);
  }

  function handlePlaying(which: Slot) {
    if (which !== slotRef.current) {
      videoOf(which)?.pause();
      return;
    }
    advancingRef.current = false;
    setPlaying(true);
  }

  function handlePause(which: Slot) {
    if (which !== slotRef.current || advancingRef.current) {
      return;
    }
    setPlaying(false);
  }

  function handleEnded(which: Slot) {
    if (which !== slotRef.current) {
      return;
    }
    const video = videoOf(which);
    const currentSlice = sequenceRef.current.slices[indexRef.current];
    if (!video || !currentSlice || advancingRef.current) {
      return;
    }
    if (video.currentTime <= currentSlice.offsetSeconds + 0.3) {
      return;
    }
    finishSlice();
  }

  function handleError(which: Slot) {
    if (which !== slotRef.current && pendingHandoff.current?.to !== which) {
      return;
    }
    advancingRef.current = false;
    pendingHandoff.current = null;
    onPlaybackError();
  }

  function commitScrub(value: string) {
    setScrub(null);
    const seconds = Number(value);
    if (Number.isFinite(seconds)) {
      seekTo(seconds);
    }
  }

  function togglePlay() {
    const video = videoOf(slotRef.current);
    if (!video) {
      return;
    }
    if (video.paused) {
      void video.play().catch(() => setPlaying(false));
      return;
    }
    video.pause();
  }

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
      <div className="mt-3 space-y-4">
        <div>
          <p className="text-base font-medium text-landing-ink">{windowLabel}</p>
          <p className={`mt-1 ${ui.muted}`}>
            {formatMediaTime(totalSeconds)} saved, playing as one video.
          </p>
        </div>
        {slice ? (
          <div className="relative w-full overflow-hidden rounded-md bg-landing-ink">
            {([0, 1] as const).map((which) => (
              <video
                key={which}
                ref={which === 0 ? videoA : videoB}
                playsInline
                preload="auto"
                aria-hidden={slot !== which}
                aria-label={slot === which ? windowLabel : undefined}
                className={
                  slot === which
                    ? "relative z-10 w-full"
                    : "pointer-events-none absolute inset-0 z-0 w-full opacity-0"
                }
                onClick={slot === which ? togglePlay : undefined}
                onError={() => handleError(which)}
                onLoadedMetadata={() => park(which)}
                onCanPlay={() => park(which)}
                onSeeked={() => {
                  park(which);
                  syncElapsed(which);
                }}
                onTimeUpdate={() => syncElapsed(which)}
                onPlay={() => {
                  if (which === slotRef.current) {
                    setPlaying(true);
                  }
                }}
                onPlaying={() => handlePlaying(which)}
                onPause={() => handlePause(which)}
                onEnded={() => handleEnded(which)}
              />
            ))}
          </div>
        ) : null}
        <div>
          <p className={ui.hint}>Playback</p>
          <p className="mt-1 text-base font-medium tabular-nums text-landing-ink">
            {formatMediaTime(scrub ?? elapsed)}
            <span className="font-normal text-landing-ink/45"> / </span>
            {formatMediaTime(totalSeconds)}
          </p>
          <input
            type="range"
            min={0}
            max={Math.max(totalSeconds, 0.1)}
            step={0.1}
            value={Math.min(scrub ?? elapsed, totalSeconds || 0)}
            aria-label="Position in the whole video"
            onChange={(event) => setScrub(Number(event.target.value))}
            onPointerUp={(event) => commitScrub(event.currentTarget.value)}
            onKeyUp={(event) => commitScrub(event.currentTarget.value)}
            className="mt-2 h-1.5 w-full cursor-pointer accent-[#1f7a4c]"
          />
          <p className={`mt-2 ${ui.muted}`}>
            {playing ? "Playing" : "Paused"}
            {" · "}
            {windowLabel}
          </p>
          <p className={`mt-1 ${ui.hint}`}>
            This is the whole saved video. The bar does not restart at each minute.
          </p>
        </div>
        {sequence.gaps.length > 0 ? (
          <ul className="space-y-1">
            {sequence.gaps.map((gap) => (
              <li key={`${gap.startedAt}-${gap.endedAt}`} className={ui.hint}>
                No saved picture for {formatLocalWindow(gap.startedAt, gap.endedAt)}. Playback
                continues with the next saved clip.
              </li>
            ))}
          </ul>
        ) : null}
        <p className={ui.hint}>This plays the saved picture. Verification is a separate step.</p>
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={togglePlay} className={ui.btnSecondary}>
            {playing ? "Pause" : "Play"}
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
    </section>
  );
}

function sliceSpan(slice: PlaySlice): number {
  return Math.max(0, slice.endSeconds - slice.offsetSeconds);
}

function differentSliceAfter(sequence: PlaybackSequence, fromIndex: number): number {
  const cid = sequence.slices[fromIndex]?.record.ipfs_cid.trim() ?? "";
  for (let index = fromIndex + 1; index < sequence.slices.length; index += 1) {
    if (sequence.slices[index].record.ipfs_cid.trim() !== cid) {
      return index;
    }
  }
  return -1;
}

function sameSource(video: HTMLVideoElement, url: string): boolean {
  const attr = video.getAttribute("src");
  return attr === url || video.src === url;
}

function positionAt(
  sequence: PlaybackSequence,
  seconds: number
): { index: number; mediaTime: number; elapsed: number } {
  const spans = sequence.slices.map(sliceSpan);
  const total = spans.reduce((sum, span) => sum + span, 0);
  const clamped = Math.min(Math.max(0, seconds), Math.max(0, total - 0.05));
  let cursor = 0;
  for (let i = 0; i < sequence.slices.length; i += 1) {
    const span = spans[i] ?? 0;
    const last = i === sequence.slices.length - 1;
    if (clamped < cursor + span || last) {
      const into = Math.min(Math.max(0, clamped - cursor), Math.max(0, span));
      return {
        index: i,
        mediaTime: sequence.slices[i].offsetSeconds + into,
        elapsed: cursor + into,
      };
    }
    cursor += span;
  }
  return {
    index: 0,
    mediaTime: sequence.slices[0]?.offsetSeconds ?? 0,
    elapsed: 0,
  };
}

function atSliceEnd(video: HTMLVideoElement, slice: PlaySlice): boolean {
  if (video.ended) {
    return true;
  }
  const fileEnd = Number.isFinite(video.duration) ? video.duration : slice.endSeconds;
  const stopAt = Math.min(slice.endSeconds, fileEnd);
  return video.currentTime >= stopAt - 0.08 && video.currentTime > slice.offsetSeconds + 0.3;
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
