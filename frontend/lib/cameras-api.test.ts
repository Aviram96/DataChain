import assert from "node:assert/strict";
import test from "node:test";

import { restoreFailureMessage } from "./camera-archive.ts";

test("restore name conflict explains that nothing was changed", () => {
  const message = restoreFailureMessage({
    status: 409,
    message: "You already have a camera with this name.",
  });

  assert.match(message, /already uses this name/i);
  assert.match(message, /Nothing was changed/);
});

test("other restore failures keep the API message", () => {
  const message = restoreFailureMessage({
    status: 409,
    message: "This camera is not archived.",
  });

  assert.equal(message, "This camera is not archived.");
});
