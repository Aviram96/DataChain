import assert from "node:assert/strict";
import { describe, it } from "node:test";
import hre from "hardhat";

const CAMERA_ID = "0x0123456789abcdef0123456789abcdef" as const;
const SEGMENT_HASH =
  "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" as const;
const STARTED_AT = 1_700_000_000n;
const ENDED_AT = STARTED_AT + 60n;
const CID = "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi";

const ANCHOR_ARGS = [
  CAMERA_ID,
  STARTED_AT,
  ENDED_AT,
  CID,
  SEGMENT_HASH,
] as const;

describe("Datachain", async function () {
  const { viem } = await hre.network.create();

  it("deploys", async function () {
    const datachain = await viem.deployContract("Datachain");
    assert.match(datachain.address, /^0x[a-fA-F0-9]{40}$/);
  });

  it("stores and returns camera id, CID, segment hash, start time, and end time", async function () {
    const datachain = await viem.deployContract("Datachain");

    await datachain.write.anchorSegment([...ANCHOR_ARGS]);

    const anchored = await datachain.read.getSegment([CAMERA_ID, STARTED_AT]);
    assert.equal(anchored.cameraId, CAMERA_ID);
    assert.equal(anchored.cid, CID);
    assert.equal(anchored.segmentHash, SEGMENT_HASH);
    assert.equal(anchored.startedAt, STARTED_AT);
    assert.equal(anchored.endedAt, ENDED_AT);
  });

  it("rejects a second anchor for the same camera and start time", async function () {
    const datachain = await viem.deployContract("Datachain");
    await datachain.write.anchorSegment([...ANCHOR_ARGS]);

    await assert.rejects(
      () => datachain.write.anchorSegment([...ANCHOR_ARGS]),
      /AlreadyAnchored/,
    );
  });

  it("rejects missing anchors and invalid fields", async function () {
    const datachain = await viem.deployContract("Datachain");

    await assert.rejects(
      () => datachain.read.getSegment([CAMERA_ID, STARTED_AT]),
      /AnchorNotFound/,
    );
    await assert.rejects(
      () =>
        datachain.write.anchorSegment([
          CAMERA_ID,
          STARTED_AT,
          STARTED_AT,
          CID,
          SEGMENT_HASH,
        ]),
      /InvalidTimeWindow/,
    );
    await assert.rejects(
      () =>
        datachain.write.anchorSegment([
          CAMERA_ID,
          STARTED_AT,
          ENDED_AT,
          "",
          SEGMENT_HASH,
        ]),
      /EmptyCid/,
    );
  });
});
