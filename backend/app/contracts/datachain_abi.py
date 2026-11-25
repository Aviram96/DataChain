"""ABI for Datachain.sol (anchorSegment + getSegment; Slice D)."""

_SEGMENT_ANCHOR_COMPONENTS: list[dict[str, object]] = [
    {"internalType": "bytes16", "name": "cameraId", "type": "bytes16"},
    {"internalType": "uint64", "name": "startedAt", "type": "uint64"},
    {"internalType": "uint64", "name": "endedAt", "type": "uint64"},
    {"internalType": "string", "name": "cid", "type": "string"},
    {"internalType": "bytes32", "name": "segmentHash", "type": "bytes32"},
]

DATACHAIN_ABI: list[dict[str, object]] = [
    {
        "inputs": [
            {"internalType": "bytes16", "name": "cameraId", "type": "bytes16"},
            {"internalType": "uint64", "name": "startedAt", "type": "uint64"},
            {"internalType": "uint64", "name": "endedAt", "type": "uint64"},
            {"internalType": "string", "name": "cid", "type": "string"},
            {"internalType": "bytes32", "name": "segmentHash", "type": "bytes32"},
        ],
        "name": "anchorSegment",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "bytes16", "name": "cameraId", "type": "bytes16"},
            {"internalType": "uint64", "name": "startedAt", "type": "uint64"},
        ],
        "name": "getSegment",
        "outputs": [
            {
                "components": _SEGMENT_ANCHOR_COMPONENTS,
                "internalType": "struct Datachain.SegmentAnchor",
                "name": "",
                "type": "tuple",
            }
        ],
        "stateMutability": "view",
        "type": "function",
    },
]
