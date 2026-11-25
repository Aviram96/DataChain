import assert from "node:assert/strict";
import test from "node:test";

import {
  formatLocalWindow,
  formatLocalWindowParts,
  missingRecordingMessage,
} from "./verify-recordings.ts";

test("formatLocalWindow shows the stored end instead of adding a minute", () => {
  const start = "2026-11-16T10:00:07.440Z";
  const storedEnd = "2026-11-16T10:01:15.000Z";
  const labeled = formatLocalWindow(start, storedEnd);

  assert.match(labeled, /15/);
  assert.match(labeled, /–/);
  assert.notEqual(labeled, formatLocalWindow(start));
});

test("formatLocalWindowParts keeps the date and stored times on separate rows", () => {
  const start = "2026-11-16T10:00:07.440Z";
  const storedEnd = "2026-11-16T10:01:15.000Z";
  const parts = formatLocalWindowParts(start, storedEnd);

  assert.match(parts.time, /15/);
  assert.match(parts.time, /–/);
  assert.equal(parts.date.includes("–"), false);
  assert.notEqual(parts.time, formatLocalWindowParts(start).time);
});

test("a missing recording message names that time range", () => {
  const start = "2026-11-16T10:00:07.440Z";
  const end = "2026-11-16T10:01:15.000Z";
  const message = missingRecordingMessage(start, end);

  assert.equal(
    message,
    `No recorded video is available for ${formatLocalWindow(start, end)}. Playback continues with the next available segment.`
  );
});
