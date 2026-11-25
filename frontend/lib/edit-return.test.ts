import assert from "node:assert/strict";
import test from "node:test";

import {
  cameraEditCancelHref,
  cameraEditHref,
  cameraEditSaveHref,
} from "./edit-return.ts";

const cameraId = "3c0911cb-907f-49f5-9225-ed79539ec5d3";

test("Edit from the camera list returns Cancel to the list", () => {
  const href = cameraEditHref(cameraId, "list");
  const from = new URL(href, "http://localhost").searchParams.get("from");

  assert.equal(href, `/cameras/${cameraId}/edit?from=list`);
  assert.equal(cameraEditCancelHref(cameraId, from), "/cameras");
});

test("Edit from camera details returns Cancel to that camera", () => {
  const href = cameraEditHref(cameraId, "details");
  const from = new URL(href, "http://localhost").searchParams.get("from");

  assert.equal(href, `/cameras/${cameraId}/edit`);
  assert.equal(cameraEditCancelHref(cameraId, from), `/cameras/${cameraId}`);
});

test("opening the edit URL directly returns Cancel to that camera", () => {
  assert.equal(cameraEditCancelHref(cameraId, null), `/cameras/${cameraId}`);
  assert.equal(cameraEditCancelHref(cameraId, ""), `/cameras/${cameraId}`);
});

test("Save Changes from the camera list returns to the list", () => {
  const href = cameraEditHref(cameraId, "list");
  const from = new URL(href, "http://localhost").searchParams.get("from");

  assert.equal(cameraEditSaveHref(cameraId, from, true), "/cameras");
});

test("Save Changes from camera details returns to that camera", () => {
  const href = cameraEditHref(cameraId, "details");
  const from = new URL(href, "http://localhost").searchParams.get("from");

  assert.equal(
    cameraEditSaveHref(cameraId, from, true),
    `/cameras/${cameraId}`
  );
});

test("a failed save stays on the edit page", () => {
  assert.equal(cameraEditSaveHref(cameraId, "list", false), null);
  assert.equal(cameraEditSaveHref(cameraId, null, false), null);
});

test("Cancel ignores an arbitrary return destination", () => {
  assert.equal(
    cameraEditCancelHref(cameraId, "https://evil.example/phish"),
    `/cameras/${cameraId}`
  );
  assert.equal(
    cameraEditCancelHref(cameraId, "/cameras?next=https://evil.example"),
    `/cameras/${cameraId}`
  );
  assert.equal(
    cameraEditCancelHref(cameraId, "list/../admin"),
    `/cameras/${cameraId}`
  );
});
