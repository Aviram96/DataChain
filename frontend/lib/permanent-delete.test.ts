import assert from "node:assert/strict";
import test from "node:test";

import {
  performPermanentDelete,
  permanentDeleteErrorText,
  permanentDeletePath,
  permanentDeleteSuccessMessage,
  submitPermanentDelete,
  type PermanentDeleteResult,
} from "./permanent-delete.ts";

const CAMERA_ID = "3c0911cb-907f-49f5-9225-ed79539ec5d3";

function deletedResult(
  overrides: Partial<PermanentDeleteResult> = {}
): PermanentDeleteResult {
  return {
    camera_id: CAMERA_ID,
    deleted: true,
    message: "Camera deleted.",
    ...overrides,
  };
}

test("a finished delete reports only that the camera was deleted", () => {
  const message = permanentDeleteSuccessMessage();

  assert.equal(message, "Camera deleted.");
  assert.doesNotMatch(message, /pin/i);
  assert.doesNotMatch(message, /ipfs/i);
  assert.doesNotMatch(message, /blockchain/i);
  assert.doesNotMatch(message, /recording/i);
});

test("API errors stay on the page and say nothing was deleted", () => {
  assert.match(
    permanentDeleteErrorText({
      status: 400,
      message: "Camera name confirmation does not match.",
    }),
    /does not match/i
  );
  assert.match(
    permanentDeleteErrorText({ status: 404, message: "Camera not found." }),
    /could not be found/i
  );
  assert.match(
    permanentDeleteErrorText({
      status: 409,
      message:
        "This camera contains saved recordings or related data and cannot be permanently deleted.",
    }),
    /cannot be permanently deleted/i
  );
  assert.match(
    permanentDeleteErrorText({
      status: 409,
      message:
        "This camera is still recording. Try again after recording has stopped.",
    }),
    /still recording/i
  );
  for (const status of [400, 404, 409]) {
    assert.match(
      permanentDeleteErrorText({ status, message: "detail" }),
      /Nothing was deleted/
    );
  }
  assert.match(
    permanentDeleteErrorText(new TypeError("fetch failed")),
    /Cannot reach the API/
  );
});

test("a second submission does not send another request", async () => {
  const lock = { current: false };
  let calls = 0;
  let release: () => void = () => {};
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });

  const send = async (confirmName: string) => {
    calls += 1;
    assert.equal(confirmName, "Lobby");
    await gate;
    return deletedResult();
  };

  const first = submitPermanentDelete({
    cameraName: "Lobby",
    lock,
    send,
  });
  const second = await submitPermanentDelete({
    cameraName: "Lobby",
    lock,
    send,
  });

  assert.equal(second.status, "duplicate");
  assert.equal(calls, 1);
  release();
  const finished = await first;
  assert.equal(finished.status, "deleted");
  assert.equal(calls, 1);
  assert.equal(lock.current, false);
});

test("delete sends the selected camera name exactly once", async () => {
  const seen: string[] = [];
  const outcome = await submitPermanentDelete({
    cameraName: "Lobby North",
    lock: { current: false },
    send: async (confirmName) => {
      seen.push(confirmName);
      return deletedResult();
    },
  });

  assert.equal(outcome.status, "deleted");
  assert.deepEqual(seen, ["Lobby North"]);
});

test("the delete request posts confirm_name and reads the result", async () => {
  const seen: { url: string; init: RequestInit | undefined }[] = [];
  const result = await performPermanentDelete({
    confirmName: "Lobby",
    url: `http://example.test${permanentDeletePath(CAMERA_ID)}`,
    fetchImpl: async (url, init) => {
      seen.push({ url, init });
      return new Response(JSON.stringify(deletedResult()), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    },
  });

  assert.equal(seen.length, 1);
  assert.equal(
    seen[0].url,
    `http://example.test/cameras/${CAMERA_ID}/permanent-delete`
  );
  assert.equal(seen[0].init?.method, "POST");
  assert.equal(seen[0].init?.body, JSON.stringify({ confirm_name: "Lobby" }));
  assert.equal(result.deleted, true);
  assert.equal(result.message, "Camera deleted.");
  assert.equal(permanentDeleteSuccessMessage(), "Camera deleted.");
});

test("mocked 400, 404, and 409 responses are reported once", async () => {
  const cases = [
    { status: 400, detail: "Camera name confirmation does not match." },
    { status: 404, detail: "Camera not found." },
    {
      status: 409,
      detail:
        "This camera is still recording. Try again after recording has stopped.",
    },
  ];

  for (const item of cases) {
    let calls = 0;
    await assert.rejects(
      () =>
        performPermanentDelete({
          confirmName: "Lobby",
          url: `http://example.test${permanentDeletePath(CAMERA_ID)}`,
          fetchImpl: async () => {
            calls += 1;
            return new Response(JSON.stringify({ detail: item.detail }), {
              status: item.status,
              headers: { "Content-Type": "application/json" },
            });
          },
        }),
      (error: unknown) => {
        assert.equal(
          permanentDeleteErrorText(error).includes("Nothing was deleted"),
          true
        );
        const statusError = error as { status: number; message: string };
        assert.equal(statusError.status, item.status);
        assert.equal(statusError.message, item.detail);
        return true;
      }
    );
    assert.equal(calls, 1);
  }
});

test("a network failure does not look like a completed delete", async () => {
  await assert.rejects(
    () =>
      performPermanentDelete({
        confirmName: "Lobby",
        url: `http://example.test${permanentDeletePath(CAMERA_ID)}`,
        fetchImpl: async () => {
          throw new TypeError("fetch failed");
        },
      }),
    (error: unknown) => {
      assert.match(permanentDeleteErrorText(error), /Cannot reach the API/);
      assert.match(permanentDeleteErrorText(error), /Nothing was deleted/);
      return true;
    }
  );
});
