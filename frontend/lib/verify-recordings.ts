import type { VideoRecordPublic } from "./recordings-api";

export const SEGMENT_MS = 60_000;
export const MAX_EXPECTED_MINUTES = 24 * 60;

export type VerifyStatus =
  | "verified"
  | "tampered"
  | "missing"
  | "failed_to_verify";

export type ChainRead =
  | {
      kind: "found";
      cameraId: string;
      startedAt: bigint;
      endedAt: bigint;
      cid: string;
      segmentHash: string;
    }
  | { kind: "not_found" }
  | { kind: "rpc_error"; message: string };

export type VerifyMinuteResult = {
  slotIso: string;
  status: VerifyStatus;
  detail: string;
  record: VideoRecordPublic | null;
};

export type VerifyReport = {
  overall: VerifyStatus;
  results: VerifyMinuteResult[];
};

export function expectedMinuteStarts(
  startedAtIso: string,
  endedAtIso: string
): Date[] {
  const startMs = Date.parse(startedAtIso);
  const endMs = Date.parse(endedAtIso);
  if (!Number.isFinite(startMs) || !Number.isFinite(endMs) || endMs <= startMs) {
    return [];
  }
  const first = Math.floor(startMs / SEGMENT_MS) * SEGMENT_MS;
  const starts: Date[] = [];
  for (let t = first; t < endMs; t += SEGMENT_MS) {
    if (t + SEGMENT_MS > startMs && t < endMs) {
      starts.push(new Date(t));
    }
  }
  return starts;
}

export function findRecordForSlot(
  records: VideoRecordPublic[],
  slot: Date
): VideoRecordPublic | undefined {
  const slotStart = slot.getTime();
  const slotEnd = slotStart + SEGMENT_MS;
  return records.find((record) => {
    const started = Date.parse(record.started_at);
    return started >= slotStart && started < slotEnd;
  });
}

export function unixSeconds(iso: string): bigint {
  return BigInt(Math.floor(Date.parse(iso) / 1000));
}

export function classifySegment(input: {
  cameraId: string;
  record?: VideoRecordPublic | null;
  chain: ChainRead;
}): { status: VerifyStatus; detail: string } {
  const { cameraId, record, chain } = input;

  if (chain.kind === "rpc_error") {
    return {
      status: "failed_to_verify",
      detail:
        "Could not read the blockchain (RPC). This is not a tamper result.",
    };
  }

  if (!record) {
    return {
      status: "missing",
      detail:
        chain.kind === "found"
          ? "No recording in the app for this minute, even though an on-chain proof exists."
          : "No recording for this minute.",
    };
  }

  if (chain.kind === "not_found") {
    return {
      status: "tampered",
      detail:
        "The app has this minute, but no matching proof is on the blockchain.",
    };
  }

  const matches =
    sameCamera(cameraId, chain.cameraId) &&
    sameCid(record.ipfs_cid, chain.cid) &&
    sameHash(record.segment_hash, chain.segmentHash) &&
    unixSeconds(record.started_at) === chain.startedAt &&
    unixSeconds(record.ended_at) === chain.endedAt;

  if (!matches) {
    return {
      status: "tampered",
      detail: "App metadata does not match the blockchain proof.",
    };
  }

  return {
    status: "verified",
    detail: "App CID, hash, and times match the blockchain record.",
  };
}

export function aggregateStatus(statuses: VerifyStatus[]): VerifyStatus {
  if (statuses.length === 0) {
    return "missing";
  }
  if (statuses.some((status) => status === "tampered")) {
    return "tampered";
  }
  if (statuses.some((status) => status === "failed_to_verify")) {
    return "failed_to_verify";
  }
  if (statuses.some((status) => status === "missing")) {
    return "missing";
  }
  return "verified";
}

export function verifyStatusLabel(status: VerifyStatus): string {
  switch (status) {
    case "verified":
      return "Verified";
    case "tampered":
      return "Tampered";
    case "missing":
      return "Missing";
    case "failed_to_verify":
      return "Failed to verify";
  }
}

export function countByStatus(
  results: VerifyMinuteResult[]
): Record<VerifyStatus, number> {
  const counts: Record<VerifyStatus, number> = {
    verified: 0,
    tampered: 0,
    missing: 0,
    failed_to_verify: 0,
  };
  for (const result of results) {
    counts[result.status] += 1;
  }
  return counts;
}

function sameCamera(uuid: string, chainCameraId: string): boolean {
  return uuidToHex(uuid) === bytesToHex(chainCameraId, 32);
}

function sameCid(dbCid: string, chainCid: string): boolean {
  return dbCid.trim() === chainCid.trim();
}

function sameHash(dbHash: string, chainHash: string): boolean {
  return normalizeHex(dbHash) === normalizeHex(chainHash);
}

export function uuidToHex(cameraId: string): string {
  return cameraId.replace(/-/g, "").toLowerCase();
}

export function uuidToBytes16(cameraId: string): string {
  const hex = uuidToHex(cameraId);
  if (!/^[0-9a-f]{32}$/.test(hex)) {
    throw new Error("invalid camera id");
  }
  return `0x${hex}`;
}

function bytesToHex(value: string, hexChars: number): string {
  return value.replace(/^0x/i, "").toLowerCase().padStart(hexChars, "0").slice(0, hexChars);
}

function normalizeHex(value: string): string {
  return value.trim().toLowerCase().replace(/^0x/, "");
}
