import assert from "node:assert/strict";
import test from "node:test";

import type { PlaybackDenial, VideoRecordPublic } from "./recordings-api";
import {
  formatVerifySlot,
  reportFromPlaybackDenial,
  verifyStatusMeaning,
  type VerifyStatus,
} from "./verify-recordings.ts";

const statuses: VerifyStatus[] = [
  "verified",
  "tampered",
  "missing",
  "unavailable",
  "failed",
  "failed_to_verify",
];

test("every verification status has a sentence", () => {
  for (const status of statuses) {
    assert.ok(verifyStatusMeaning(status).length > 0);
  }
});

test("formatVerifySlot keeps the stored end instead of a calendar minute", () => {
  const start = "2026-11-16T10:00:07.440Z";
  const storedEnd = "2026-11-16T10:01:15.000Z";
  assert.notEqual(formatVerifySlot(start, storedEnd), formatVerifySlot(start));
  assert.match(formatVerifySlot(start, storedEnd), /15/);
});

test("playback denial report uses stored segment times", () => {
  const record: VideoRecordPublic = {
    id: "rec-1",
    camera_id: "cam",
    started_at: "2026-11-16T10:00:07.440Z",
    ended_at: "2026-11-16T10:01:07.440Z",
    ipfs_cid: "bafytest",
    segment_hash: "abc",
    tx_hash: "0xabc",
  };
  const denial: PlaybackDenial = {
    overall: "tampered",
    detail: "This clip does not match the chain.",
    segments: [
      {
        video_record_id: record.id,
        started_at: record.started_at,
        ended_at: record.ended_at,
        status: "tampered",
        detail: "Hash mismatch",
      },
    ],
    missing_intervals: [
      {
        started_at: "2026-11-16T10:01:07.440Z",
        ended_at: "2026-11-16T10:01:20.000Z",
        detail: "No recording covers this interval.",
      },
    ],
    excluded_intervals: [],
  };
  const report = reportFromPlaybackDenial(denial, record);
  assert.equal(report.source, "watch");
  assert.equal(report.detail, denial.detail);
  assert.equal(report.results[0]?.slotIso, record.started_at);
  assert.equal(report.results[0]?.endedAt, record.ended_at);
  assert.equal(report.results[1]?.entry, "gap");
  assert.equal(report.results[1]?.endedAt, "2026-11-16T10:01:20.000Z");
  assert.equal(JSON.stringify(report).includes("ipfs.io"), false);
  assert.equal(JSON.stringify(report).includes("gateway"), false);
});
