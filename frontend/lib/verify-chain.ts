import { Contract, JsonRpcProvider } from "ethers";

import { DATACHAIN_ABI } from "./datachain-abi";
import { getVerifyConfig } from "./verify-config";
import {
  unixSeconds,
  uuidToBytes16,
  type ChainRead,
} from "./verify-recordings";

export function createDatachainContract(): Contract {
  const config = getVerifyConfig();
  const provider = new JsonRpcProvider(config.rpcUrl, config.chainId, {
    staticNetwork: true,
  });
  return new Contract(config.contractAddress, DATACHAIN_ABI, provider);
}

export async function readChainSegment(
  contract: Contract,
  cameraId: string,
  startedAtIso: string
): Promise<ChainRead> {
  try {
    const row = (await contract.getSegment(
      uuidToBytes16(cameraId),
      unixSeconds(startedAtIso)
    )) as {
      cameraId: string;
      startedAt: bigint;
      endedAt: bigint;
      cid: string;
      segmentHash: string;
    };
    return {
      kind: "found",
      cameraId: String(row.cameraId),
      startedAt: BigInt(row.startedAt),
      endedAt: BigInt(row.endedAt),
      cid: String(row.cid),
      segmentHash: String(row.segmentHash),
    };
  } catch (error) {
    if (isAnchorNotFound(error)) {
      return { kind: "not_found" };
    }
    return {
      kind: "rpc_error",
      message: error instanceof Error ? error.message : "RPC request failed",
    };
  }
}

export async function mapPool<T, R>(
  items: T[],
  limit: number,
  mapper: (item: T, index: number) => Promise<R>
): Promise<R[]> {
  const results: R[] = new Array(items.length);
  let next = 0;
  const workerCount = Math.max(1, Math.min(limit, items.length));

  async function worker() {
    while (true) {
      const index = next;
      next += 1;
      if (index >= items.length) {
        return;
      }
      results[index] = await mapper(items[index], index);
    }
  }

  await Promise.all(Array.from({ length: workerCount }, () => worker()));
  return results;
}

function isAnchorNotFound(error: unknown): boolean {
  if (typeof error === "object" && error !== null) {
    const typed = error as {
      revert?: { name?: string };
      shortMessage?: string;
      message?: string;
    };
    if (typed.revert?.name === "AnchorNotFound") {
      return true;
    }
    const text = `${typed.shortMessage ?? ""} ${typed.message ?? ""}`;
    if (/AnchorNotFound/i.test(text)) {
      return true;
    }
  }
  return error instanceof Error && /AnchorNotFound/i.test(error.message);
}
