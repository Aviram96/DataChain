/** Browser verification config (ethers.js `getSegment` vs API metadata). */

const DEFAULT_RPC_URL = "https://polygon-amoy.drpc.org";
const DEFAULT_CHAIN_ID = 80002;
const DEFAULT_CONTRACT = "0xc957f61ba4f71a114a1a3983f907e450e3e4c9b3";
const DEFAULT_POLYGONSCAN_TX_BASE = "https://amoy.polygonscan.com/tx";

/** Same-origin path proxied to the Amoy RPC (see `next.config.ts`). */
export const AMOY_RPC_PROXY = "/amoy-rpc";

export type VerifyConfig = {
  rpcUrl: string;
  chainId: number;
  contractAddress: string;
  polygonscanTxBase: string;
};

export function getVerifyConfig(): VerifyConfig {
  const rpcUrl =
    typeof window !== "undefined"
      ? AMOY_RPC_PROXY
      : process.env.NEXT_PUBLIC_POLYGON_RPC_URL?.trim() || DEFAULT_RPC_URL;
  const chainRaw = process.env.NEXT_PUBLIC_POLYGON_CHAIN_ID?.trim();
  const parsedChain = chainRaw ? Number.parseInt(chainRaw, 10) : DEFAULT_CHAIN_ID;
  const chainId = Number.isFinite(parsedChain) ? parsedChain : DEFAULT_CHAIN_ID;
  const contractAddress =
    process.env.NEXT_PUBLIC_DATACHAIN_CONTRACT_ADDRESS?.trim() ||
    DEFAULT_CONTRACT;
  const polygonscanTxBase = (
    process.env.NEXT_PUBLIC_POLYGONSCAN_TX_BASE?.trim() ||
    DEFAULT_POLYGONSCAN_TX_BASE
  ).replace(/\/+$/, "");

  return { rpcUrl, chainId, contractAddress, polygonscanTxBase };
}

export function polygonscanTxUrl(txHash: string): string | null {
  const cleaned = txHash.trim();
  if (!cleaned) {
    return null;
  }
  const hash = cleaned.startsWith("0x") ? cleaned : `0x${cleaned}`;
  return `${getVerifyConfig().polygonscanTxBase}/${hash}`;
}
