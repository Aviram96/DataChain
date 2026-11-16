import type { VideoRecordPublic } from "./recordings-api";

const GAP_NOTE_MS = 2000;

/** Minutes recorded a few seconds apart still belong to one video. */
const JOIN_GAP_MS = 30_000;

export type PlaySlice = {
  record: VideoRecordPublic;
  offsetSeconds: number;
  endSeconds: number;
  startedAt: string;
  endedAt: string;
};

export type PlaybackGap = {
  startedAt: string;
  endedAt: string;
};

export type PlaybackSequence = {
  startedAt: string;
  endedAt: string;
  slices: PlaySlice[];
  gaps: PlaybackGap[];
  /** Seconds into the stitched picture where playback should begin. */
  startSeconds: number;
};

type TimedRecord = {
  record: VideoRecordPublic;
  started: number;
  ended: number;
};

function playableRecords(records: VideoRecordPublic[]): TimedRecord[] {
  return records
    .filter((record) => record.ipfs_cid.trim())
    .map((record) => ({
      record,
      started: Date.parse(record.started_at),
      ended: Date.parse(record.ended_at),
    }))
    .filter(
      (item) =>
        Number.isFinite(item.started) &&
        Number.isFinite(item.ended) &&
        item.ended > item.started
    )
    .sort((a, b) => a.started - b.started || a.ended - b.ended);
}

/**
 * The saved video that contains `instantIso`: from the first joined minute
 * through the last, including minutes before the time the user picked.
 */
export function contiguousRecording(
  records: VideoRecordPublic[],
  instantIso: string
): { startedAt: string; endedAt: string } | null {
  const playable = playableRecords(records);
  const instant = Date.parse(instantIso);
  if (playable.length === 0 || !Number.isFinite(instant)) {
    return null;
  }

  let index = playable.findIndex(
    (item) => item.started <= instant && instant < item.ended
  );
  if (index < 0) {
    index = playable.findIndex((item) => item.started === instant);
  }
  if (index < 0) {
    for (let cursor = playable.length - 1; cursor >= 0; cursor -= 1) {
      if (playable[cursor].ended === instant || playable[cursor].started < instant) {
        index = cursor;
        break;
      }
    }
  }
  if (index < 0) {
    return null;
  }

  let first = index;
  while (
    first > 0 &&
    playable[first].started - playable[first - 1].ended <= JOIN_GAP_MS
  ) {
    first -= 1;
  }
  let last = index;
  while (
    last + 1 < playable.length &&
    playable[last + 1].started - playable[last].ended <= JOIN_GAP_MS
  ) {
    last += 1;
  }

  return {
    startedAt: playable[first].record.started_at,
    endedAt: playable[last].record.ended_at,
  };
}

/** Saved clips that cover a requested window, in playback order. */
export function buildPlaybackSequence(
  records: VideoRecordPublic[],
  startedAt: string,
  endedAt: string,
  startAt?: string
): PlaybackSequence {
  const rangeStart = Date.parse(startedAt);
  const rangeEnd = Date.parse(endedAt);
  const slices: PlaySlice[] = [];
  const gaps: PlaybackGap[] = [];
  if (!Number.isFinite(rangeStart) || !Number.isFinite(rangeEnd) || rangeEnd <= rangeStart) {
    return { startedAt, endedAt, slices, gaps, startSeconds: 0 };
  }

  const playable = playableRecords(records);

  let cursor = rangeStart;
  while (cursor < rangeEnd) {
    const cover = playable.filter(
      (item) => item.started <= cursor && cursor < item.ended
    );
    const active = cover[cover.length - 1];
    if (!active) {
      const next = playable.find((item) => item.started > cursor)?.started;
      const gapEnd = next != null && next < rangeEnd ? next : rangeEnd;
      if (gapEnd - cursor >= GAP_NOTE_MS) {
        gaps.push({
          startedAt: new Date(cursor).toISOString(),
          endedAt: new Date(gapEnd).toISOString(),
        });
      }
      if (next == null || next >= rangeEnd) {
        break;
      }
      cursor = next;
      continue;
    }

    const sliceEnd = Math.min(active.ended, rangeEnd);
    if (sliceEnd <= cursor) {
      break;
    }
    slices.push({
      record: active.record,
      offsetSeconds: (cursor - active.started) / 1000,
      endSeconds: (sliceEnd - active.started) / 1000,
      startedAt: new Date(cursor).toISOString(),
      endedAt: new Date(sliceEnd).toISOString(),
    });
    cursor = sliceEnd;
  }

  const sequence: PlaybackSequence = {
    startedAt,
    endedAt,
    slices,
    gaps,
    startSeconds: 0,
  };
  if (startAt && slices.length > 0) {
    const total = slices.reduce(
      (sum, item) => sum + (item.endSeconds - item.offsetSeconds),
      0
    );
    const offset = offsetIntoSequence(sequence, startAt);
    sequence.startSeconds = Math.min(Math.max(0, offset), Math.max(0, total - 0.05));
  }
  return sequence;
}

function offsetIntoSequence(sequence: PlaybackSequence, instantIso: string): number {
  const instant = Date.parse(instantIso);
  if (!Number.isFinite(instant)) {
    return 0;
  }
  let elapsed = 0;
  for (const slice of sequence.slices) {
    const start = Date.parse(slice.startedAt);
    const end = Date.parse(slice.endedAt);
    const span = slice.endSeconds - slice.offsetSeconds;
    if (instant <= start) {
      return elapsed;
    }
    if (instant < end) {
      return elapsed + Math.max(0, (instant - start) / 1000);
    }
    elapsed += span;
  }
  return elapsed;
}
