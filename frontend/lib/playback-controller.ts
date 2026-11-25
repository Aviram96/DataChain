/**
 * Playback state for one video element.
 * Every recording interval is its own slice. A shared CID never skips a slice.
 */

export type PlaybackPhase =
  | "loading"
  | "playing"
  | "paused"
  | "transitioning"
  | "blocked"
  | "ended";

export type MediaSlice = {
  id: string;
  cid: string;
  offsetSeconds: number;
  endSeconds: number;
};

export type PlaybackMachine = {
  phase: PlaybackPhase;
  index: number;
  elapsed: number;
  targetMediaTime: number;
  command: number;
  positioned: boolean;
  playWhenReady: boolean;
};

export type PlaybackEffect =
  | { type: "none" }
  | {
      type: "show";
      command: number;
      index: number;
      mediaTime: number;
      play: boolean;
    }
  | { type: "play"; command: number }
  | { type: "pause"; command: number };

export type PlaybackEvent =
  | { type: "positioned"; command: number; currentTime: number }
  | { type: "time"; command: number; currentTime: number }
  | { type: "ended"; command: number; currentTime: number }
  | { type: "playing"; command: number }
  | { type: "paused"; command: number }
  | { type: "play-rejected"; command: number }
  | { type: "load-failed"; command: number; index: number }
  | { type: "seek"; seconds: number }
  | { type: "toggle" }
  | { type: "cancel" };

export type PlaybackStep = {
  state: PlaybackMachine;
  effect: PlaybackEffect;
};

const POSITION_TOLERANCE_SECONDS = 0.5;
const SAMPLE_TOLERANCE_SECONDS = 0.35;
const END_EPSILON_SECONDS = 0.08;
const START_GUARD_SECONDS = 0.3;

export function sliceSpan(slice: MediaSlice): number {
  return Math.max(0, slice.endSeconds - slice.offsetSeconds);
}

export function elapsedBefore(slices: MediaSlice[], index: number): number {
  let sum = 0;
  for (let cursor = 0; cursor < index && cursor < slices.length; cursor += 1) {
    sum += sliceSpan(slices[cursor]);
  }
  return sum;
}

export function totalPlayableSeconds(slices: MediaSlice[]): number {
  return elapsedBefore(slices, slices.length);
}

/** Timeline seconds for a file position that belongs to this slice. */
export function sampleElapsed(
  slices: MediaSlice[],
  index: number,
  currentTime: number
): number | null {
  const slice = slices[index];
  if (!slice) {
    return null;
  }
  if (currentTime < slice.offsetSeconds - SAMPLE_TOLERANCE_SECONDS) {
    return null;
  }
  if (currentTime > slice.endSeconds + SAMPLE_TOLERANCE_SECONDS) {
    return null;
  }
  const into = Math.min(
    Math.max(0, currentTime - slice.offsetSeconds),
    sliceSpan(slice)
  );
  return elapsedBefore(slices, index) + into;
}

export function positionAt(
  slices: MediaSlice[],
  seconds: number
): { index: number; mediaTime: number; elapsed: number } {
  if (slices.length === 0) {
    return { index: 0, mediaTime: 0, elapsed: 0 };
  }
  const total = totalPlayableSeconds(slices);
  const clamped = Math.min(Math.max(0, seconds), Math.max(0, total - 0.05));
  let cursor = 0;
  for (let index = 0; index < slices.length; index += 1) {
    const span = sliceSpan(slices[index]);
    const last = index === slices.length - 1;
    if (clamped < cursor + span || last) {
      const into = Math.min(Math.max(0, clamped - cursor), Math.max(0, span));
      return {
        index,
        mediaTime: slices[index].offsetSeconds + into,
        elapsed: cursor + into,
      };
    }
    cursor += span;
  }
  return {
    index: 0,
    mediaTime: slices[0].offsetSeconds,
    elapsed: 0,
  };
}

export function shouldAdvance(
  slice: MediaSlice,
  currentTime: number,
  ended: boolean
): boolean {
  if (currentTime <= slice.offsetSeconds + START_GUARD_SECONDS) {
    return false;
  }
  if (ended) {
    return true;
  }
  return currentTime >= slice.endSeconds - END_EPSILON_SECONDS;
}

export function openPlayback(
  slices: MediaSlice[],
  startSeconds: number
): PlaybackStep {
  const pos = positionAt(slices, startSeconds);
  if (slices.length === 0) {
    return {
      state: {
        phase: "ended",
        index: 0,
        elapsed: 0,
        targetMediaTime: 0,
        command: 1,
        positioned: false,
        playWhenReady: false,
      },
      effect: { type: "none" },
    };
  }
  return {
    state: {
      phase: "loading",
      index: pos.index,
      elapsed: pos.elapsed,
      targetMediaTime: pos.mediaTime,
      command: 1,
      positioned: false,
      playWhenReady: true,
    },
    effect: {
      type: "show",
      command: 1,
      index: pos.index,
      mediaTime: pos.mediaTime,
      play: true,
    },
  };
}

export function reducePlayback(
  state: PlaybackMachine,
  event: PlaybackEvent,
  slices: MediaSlice[]
): PlaybackStep {
  if (event.type === "cancel") {
    const command = state.command + 1;
    return {
      state: {
        ...state,
        phase: "loading",
        command,
        positioned: false,
        playWhenReady: false,
      },
      effect: { type: "pause", command },
    };
  }

  if (event.type === "seek") {
    const pos = positionAt(slices, event.seconds);
    const play =
      state.phase === "playing" ||
      ((state.phase === "transitioning" || state.phase === "loading") &&
        state.playWhenReady);
    return showSlice(
      state,
      slices,
      pos.index,
      pos.mediaTime,
      pos.elapsed,
      play
    );
  }

  if (event.type === "toggle") {
    return toggle(state, slices);
  }

  if ("command" in event && event.command !== state.command) {
    return hold(state);
  }

  switch (event.type) {
    case "positioned":
      return onPositioned(state, slices, event.currentTime);
    case "time":
      return onTime(state, slices, event.currentTime);
    case "ended":
      return onEnded(state, slices, event.currentTime);
    case "playing":
      if (!state.positioned || !state.playWhenReady) {
        return hold(state);
      }
      return {
        state: { ...state, phase: "playing" },
        effect: { type: "none" },
      };
    case "paused":
      if (
        state.phase === "transitioning" ||
        state.phase === "loading" ||
        state.phase !== "playing"
      ) {
        return hold(state);
      }
      return {
        state: { ...state, phase: "paused", playWhenReady: false },
        effect: { type: "none" },
      };
    case "play-rejected":
      return {
        state: { ...state, phase: "paused", playWhenReady: false },
        effect: { type: "none" },
      };
    case "load-failed":
      if (event.index !== state.index) {
        return hold(state);
      }
      return {
        state: {
          ...state,
          phase: "blocked",
          positioned: false,
          playWhenReady: false,
        },
        effect: { type: "pause", command: state.command },
      };
    default:
      return hold(state);
  }
}

function toggle(state: PlaybackMachine, slices: MediaSlice[]): PlaybackStep {
  if (state.phase === "playing") {
    return {
      state: { ...state, phase: "paused", playWhenReady: false },
      effect: { type: "pause", command: state.command },
    };
  }
  if (state.phase === "paused" && state.positioned) {
    return {
      state: { ...state, phase: "playing", playWhenReady: true },
      effect: { type: "play", command: state.command },
    };
  }
  if (state.phase === "ended" && slices.length > 0) {
    const pos = positionAt(slices, 0);
    return showSlice(
      state,
      slices,
      pos.index,
      pos.mediaTime,
      pos.elapsed,
      true
    );
  }
  if (state.phase === "loading" || state.phase === "transitioning") {
    return {
      state: { ...state, playWhenReady: !state.playWhenReady },
      effect: { type: "none" },
    };
  }
  return hold(state);
}

function onPositioned(
  state: PlaybackMachine,
  slices: MediaSlice[],
  currentTime: number
): PlaybackStep {
  if (
    Math.abs(currentTime - state.targetMediaTime) > POSITION_TOLERANCE_SECONDS
  ) {
    return hold(state);
  }
  const elapsed =
    sampleElapsed(slices, state.index, currentTime) ?? state.elapsed;
  if (
    state.positioned &&
    ((state.playWhenReady && state.phase === "playing") ||
      (!state.playWhenReady && state.phase === "paused"))
  ) {
    return { state: { ...state, elapsed }, effect: { type: "none" } };
  }
  return {
    state: {
      ...state,
      phase: state.playWhenReady ? "playing" : "paused",
      positioned: true,
      elapsed,
    },
    effect: state.playWhenReady
      ? { type: "play", command: state.command }
      : { type: "pause", command: state.command },
  };
}

function onTime(
  state: PlaybackMachine,
  slices: MediaSlice[],
  currentTime: number
): PlaybackStep {
  if (
    (state.phase !== "playing" && state.phase !== "paused") ||
    !state.positioned
  ) {
    return hold(state);
  }
  const slice = slices[state.index];
  if (!slice) {
    return hold(state);
  }
  const elapsed = sampleElapsed(slices, state.index, currentTime);
  const sampled = elapsed == null ? state : { ...state, elapsed };
  if (state.phase === "playing" && shouldAdvance(slice, currentTime, false)) {
    return advance(sampled, slices);
  }
  return { state: sampled, effect: { type: "none" } };
}

function onEnded(
  state: PlaybackMachine,
  slices: MediaSlice[],
  currentTime: number
): PlaybackStep {
  if (state.phase !== "playing" || !state.positioned) {
    return hold(state);
  }
  const slice = slices[state.index];
  if (!slice || !shouldAdvance(slice, currentTime, true)) {
    return hold(state);
  }
  return advance(state, slices);
}

function advance(state: PlaybackMachine, slices: MediaSlice[]): PlaybackStep {
  if (state.phase === "transitioning" || state.phase === "loading") {
    return hold(state);
  }
  const next = state.index + 1;
  if (next >= slices.length) {
    return {
      state: {
        ...state,
        phase: "ended",
        elapsed: totalPlayableSeconds(slices),
        positioned: true,
        playWhenReady: false,
      },
      effect: { type: "pause", command: state.command },
    };
  }
  const slice = slices[next];
  return showSlice(
    state,
    slices,
    next,
    slice.offsetSeconds,
    elapsedBefore(slices, next),
    true
  );
}

function showSlice(
  state: PlaybackMachine,
  _slices: MediaSlice[],
  index: number,
  mediaTime: number,
  elapsed: number,
  play: boolean
): PlaybackStep {
  const command = state.command + 1;
  return {
    state: {
      phase: "transitioning",
      index,
      elapsed,
      targetMediaTime: mediaTime,
      command,
      positioned: false,
      playWhenReady: play,
    },
    effect: { type: "show", command, index, mediaTime, play },
  };
}

function hold(state: PlaybackMachine): PlaybackStep {
  return { state, effect: { type: "none" } };
}
