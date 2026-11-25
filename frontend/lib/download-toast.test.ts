import assert from "node:assert/strict";
import test from "node:test";

import {
  deliverSuccessfulDownload,
  toastForFailedDownload,
  toastForSuccessfulDownload,
} from "./download-toast.ts";
import { toastClassName, toastLabel } from "./toast-variants.ts";

const PARTIAL_DETAIL =
  "The download includes only verified portions. " +
  "Gaps and excluded intervals were left out, so this file " +
  "is not one continuous recording.";

const COMPLETE_DETAIL = "Every segment in this range is verified.";

const FAILURE_DETAIL =
  "No verified video is available for this range, so nothing was downloaded.";

test("a fully verified continuous download uses Success", () => {
  const notice = toastForSuccessfulDownload({
    overall: "verified",
    discontinuous: false,
    detail: COMPLETE_DETAIL,
  });
  assert.equal(notice.variant, "success");
  assert.equal(toastLabel(notice.variant), "Success");
  assert.equal(notice.message, COMPLETE_DETAIL);
  assert.match(toastClassName(notice.variant), /landing-accent/);
});

test("a complete verified download shows Success before the file is saved", () => {
  const calls: string[] = [];
  deliverSuccessfulDownload(
    {
      overall: "verified",
      discontinuous: false,
      detail: COMPLETE_DETAIL,
    },
    {
      showToast: (message, variant) => {
        calls.push(`${variant}:${message}`);
      },
      save: () => {
        calls.push("save");
      },
    }
  );
  assert.deepEqual(calls, [`success:${COMPLETE_DETAIL}`, "save"]);
});

test("Success is already shown if saving the file throws", () => {
  const calls: string[] = [];
  assert.throws(
    () =>
      deliverSuccessfulDownload(
        {
          overall: "verified",
          discontinuous: false,
          detail: COMPLETE_DETAIL,
        },
        {
          showToast: (_message, variant) => {
            calls.push(variant);
          },
          save: () => {
            throw new Error("download click interrupted the page");
          },
        }
      ),
    /download click interrupted the page/
  );
  assert.deepEqual(calls, ["success"]);
});

test("a partial download shows Warning before the file is saved", () => {
  const calls: string[] = [];
  deliverSuccessfulDownload(
    {
      overall: "tampered",
      discontinuous: true,
      detail: PARTIAL_DETAIL,
    },
    {
      showToast: (message, variant) => {
        calls.push(`${variant}:${message}`);
      },
      save: () => {
        calls.push("save");
      },
    }
  );
  assert.deepEqual(calls, [`warning:${PARTIAL_DETAIL}`, "save"]);
});

test("a single verified recording uses Success", () => {
  const notice = toastForSuccessfulDownload({
    overall: "verified",
    discontinuous: false,
    detail: COMPLETE_DETAIL,
  });
  assert.equal(notice.variant, "success");
  assert.equal(notice.message, COMPLETE_DETAIL);
});

test("a download of only verified portions uses Warning and keeps the explanation", () => {
  const notice = toastForSuccessfulDownload({
    overall: "tampered",
    discontinuous: true,
    detail: PARTIAL_DETAIL,
  });
  assert.equal(notice.variant, "warning");
  assert.equal(toastLabel(notice.variant), "Warning");
  assert.equal(notice.message, PARTIAL_DETAIL);
  assert.match(notice.message, /only verified portions/);
  assert.match(notice.message, /Gaps and excluded intervals/);
  assert.match(toastClassName(notice.variant), /landing-caution/);
  assert.equal(toastClassName("error").includes("landing-caution"), false);
});

test("a successful download with a coverage gap uses Warning", () => {
  const notice = toastForSuccessfulDownload({
    overall: "missing",
    discontinuous: true,
    detail: PARTIAL_DETAIL,
  });
  assert.equal(notice.variant, "warning");
  assert.equal(notice.message, PARTIAL_DETAIL);
});

test("a failed download stays Error", () => {
  const notice = toastForFailedDownload(FAILURE_DETAIL);
  assert.equal(notice.variant, "error");
  assert.equal(toastLabel(notice.variant), "Error");
  assert.equal(notice.message, FAILURE_DETAIL);
  assert.match(toastClassName(notice.variant), /landing-warn/);
});

test("toast variants stay distinct for Success, Warning, and Error", () => {
  assert.deepEqual(
    ["success", "warning", "error"].map((variant) =>
      toastLabel(variant as "success" | "warning" | "error")
    ),
    ["Success", "Warning", "Error"]
  );
  const classes = ["success", "warning", "error"].map((variant) =>
    toastClassName(variant as "success" | "warning" | "error")
  );
  assert.equal(new Set(classes).size, 3);
});
