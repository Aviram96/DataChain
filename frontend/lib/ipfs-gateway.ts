/** Public IPFS HTTP gateway used to stream recordings in the browser (CP-E.C5). */

const DEFAULT_IPFS_GATEWAY = "https://gateway.pinata.cloud";

export function getIpfsGatewayBase(): string {
  const configured = process.env.NEXT_PUBLIC_IPFS_GATEWAY?.trim();
  const raw = configured && configured.length > 0 ? configured : DEFAULT_IPFS_GATEWAY;
  return raw.replace(/\/+$/, "").replace(/\/ipfs$/i, "");
}

export function ipfsGatewayUrl(cid: string): string {
  const trimmed = cid.trim();
  return `${getIpfsGatewayBase()}/ipfs/${trimmed}`;
}
