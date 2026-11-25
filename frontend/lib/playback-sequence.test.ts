import assert from "node:assert/strict";
import test from "node:test";

import type { VideoRecordPublic } from "./recordings-api";
import {
  playableSeconds,
  sequenceForRequest,
  watchRangeReady,
} from "./playback-sequence.ts";

function clip(
  id: string,
  startedAt: string,
  endedAt: string,
  cid = id
): VideoRecordPublic {
  return {
    id,
    camera_id: "cam",
    started_at: startedAt,
    ended_at: endedAt,
    ipfs_cid: cid,
    segment_hash: id,
    tx_hash: null,
  };
}

const earlier = clip(
  "earlier",
  "2026-11-16T15:48:25.000Z",
  "2026-11-16T15:49:25.000Z"
);
const first = clip(
  "first",
  "2026-11-16T15:49:25.000Z",
  "2026-11-16T15:50:25.000Z"
);
const second = clip(
  "second",
  "2026-11-16T15:50:25.000Z",
  "2026-11-16T15:51:25.000Z"
);
const third = clip(
  "third",
  "2026-11-16T15:51:25.000Z",
  "2026-11-16T15:52:25.000Z"
);
const later = clip(
  "later",
  "2026-11-16T15:52:25.000Z",
  "2026-11-16T15:53:25.000Z"
);
const joined = [earlier, first, second, third, later];

test("an explicit three-minute range starts at 0:00 and lasts 3:00", () => {
  const sequence = sequenceForRequest(
    joined,
    "2026-11-16T15:49:25.000Z",
    "2026-11-16T15:52:25.000Z"
  );
  assert.ok(sequence);
  assert.equal(sequence.startedAt, "2026-11-16T15:49:25.000Z");
  assert.equal(sequence.endedAt, "2026-11-16T15:52:25.000Z");
  assert.deepEqual(
    sequence.slices.map((slice) => slice.record.id),
    ["first", "second", "third"]
  );
  assert.equal(sequence.startSeconds, 0);
  assert.equal(playableSeconds(sequence), 180);
  assert.equal(sequence.gaps.length, 0);
});

test("a start and end inside stored segments keep those file offsets", () => {
  const sequence = sequenceForRequest(
    joined,
    "2026-11-16T15:49:40.000Z",
    "2026-11-16T15:51:10.000Z"
  );
  assert.ok(sequence);
  assert.deepEqual(
    sequence.slices.map((slice) => ({
      id: slice.record.id,
      offset: slice.offsetSeconds,
      end: slice.endSeconds,
    })),
    [
      { id: "first", offset: 15, end: 60 },
      { id: "second", offset: 0, end: 45 },
    ]
  );
  assert.equal(sequence.startSeconds, 0);
  assert.equal(playableSeconds(sequence), 90);
});

test("gap detection uses stored times instead of calendar minutes", () => {
  const uneven = [
    clip("open", "2026-11-16T15:49:25.500Z", "2026-11-16T15:50:32.779Z"),
    clip("next", "2026-11-16T15:50:40.000Z", "2026-11-16T15:51:40.000Z"),
  ];
  const sequence = sequenceForRequest(
    uneven,
    "2026-11-16T15:49:40.000Z",
    "2026-11-16T15:50:50.000Z"
  );
  assert.ok(sequence);
  assert.equal(sequence.slices[0]?.offsetSeconds, 14.5);
  assert.ok(Math.abs((sequence.slices[0]?.endSeconds ?? 0) - 67.279) < 0.001);
  assert.equal(sequence.slices[1]?.offsetSeconds, 0);
  assert.equal(sequence.slices[1]?.endSeconds, 10);
  assert.equal(sequence.gaps.length, 1);
  assert.equal(sequence.gaps[0]?.startedAt, "2026-11-16T15:50:32.779Z");
  assert.equal(sequence.gaps[0]?.endedAt, "2026-11-16T15:50:40.000Z");
});

test("a start without an end still opens the joined recording", () => {
  const sequence = sequenceForRequest(joined, "2026-11-16T15:49:25.000Z");
  assert.ok(sequence);
  assert.equal(sequence.slices[0]?.record.id, "earlier");
  assert.equal(sequence.startSeconds, 60);
  assert.equal(playableSeconds(sequence), 300);
});

test("identical content stays on separate slices", () => {
  const repeated = [
    clip(
      "a",
      "2026-11-16T15:49:25.000Z",
      "2026-11-16T15:50:25.000Z",
      "same-cid"
    ),
    clip(
      "b",
      "2026-11-16T15:50:25.000Z",
      "2026-11-16T15:51:25.000Z",
      "same-cid"
    ),
    clip(
      "c",
      "2026-11-16T15:51:25.000Z",
      "2026-11-16T15:52:25.000Z",
      "same-cid"
    ),
  ];
  const sequence = sequenceForRequest(
    repeated,
    "2026-11-16T15:49:25.000Z",
    "2026-11-16T15:52:25.000Z"
  );
  assert.ok(sequence);
  assert.deepEqual(
    sequence.slices.map((slice) => slice.record.id),
    ["a", "b", "c"]
  );
  assert.equal(playableSeconds(sequence), 180);
});

test("Watch requires an end time later than the start", () => {
  assert.equal(
    watchRangeReady("2026-11-16T15:49:25.000Z", "2026-11-16T15:52:25.000Z"),
    true
  );
  assert.equal(watchRangeReady("2026-11-16T15:49:25.000Z", ""), false);
  assert.equal(
    watchRangeReady("2026-11-16T15:52:25.000Z", "2026-11-16T15:49:25.000Z"),
    false
  );
});
