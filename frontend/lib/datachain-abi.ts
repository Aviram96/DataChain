/** Minimal ABI for browser `getSegment` reads (Slice E / CP-E.C7). */

export const DATACHAIN_ABI = [
  {
    type: "function",
    name: "getSegment",
    stateMutability: "view",
    inputs: [
      { name: "cameraId", type: "bytes16" },
      { name: "startedAt", type: "uint64" },
    ],
    outputs: [
      {
        name: "",
        type: "tuple",
        components: [
          { name: "cameraId", type: "bytes16" },
          { name: "startedAt", type: "uint64" },
          { name: "endedAt", type: "uint64" },
          { name: "cid", type: "string" },
          { name: "segmentHash", type: "bytes32" },
        ],
      },
    ],
  },
  { type: "error", name: "AnchorNotFound", inputs: [] },
] as const;
