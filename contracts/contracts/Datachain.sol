// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title Datachain
/// @notice Anchors one-minute CCTV segment metadata on-chain (CID, hash, time window).
/// @dev Keyed by camera id (UUID as bytes16) and UTC start time. Writes are owner-only.
contract Datachain {
    struct SegmentAnchor {
        bytes16 cameraId;
        uint64 startedAt;
        uint64 endedAt;
        string cid;
        bytes32 segmentHash;
    }

    address public immutable owner;

    mapping(bytes32 => SegmentAnchor) private _anchors;

    error NotOwner();
    error ZeroCameraId();
    error InvalidTimeWindow();
    error EmptyCid();
    error ZeroSegmentHash();
    error AlreadyAnchored();
    error AnchorNotFound();

    event SegmentAnchored(
        bytes16 indexed cameraId,
        uint64 indexed startedAt,
        uint64 endedAt,
        string cid,
        bytes32 segmentHash
    );

    constructor() {
        owner = msg.sender;
    }

    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner();
        _;
    }

    function anchorKey(
        bytes16 cameraId,
        uint64 startedAt
    ) public pure returns (bytes32) {
        return keccak256(abi.encodePacked(cameraId, startedAt));
    }

    function anchorSegment(
        bytes16 cameraId,
        uint64 startedAt,
        uint64 endedAt,
        string calldata cid,
        bytes32 segmentHash
    ) external onlyOwner {
        if (cameraId == bytes16(0)) revert ZeroCameraId();
        if (endedAt <= startedAt) revert InvalidTimeWindow();
        if (bytes(cid).length == 0) revert EmptyCid();
        if (segmentHash == bytes32(0)) revert ZeroSegmentHash();

        bytes32 key = anchorKey(cameraId, startedAt);
        if (bytes(_anchors[key].cid).length != 0) {
            revert AlreadyAnchored();
        }

        _anchors[key] = SegmentAnchor({
            cameraId: cameraId,
            startedAt: startedAt,
            endedAt: endedAt,
            cid: cid,
            segmentHash: segmentHash
        });

        emit SegmentAnchored(cameraId, startedAt, endedAt, cid, segmentHash);
    }

    function getSegment(
        bytes16 cameraId,
        uint64 startedAt
    ) external view returns (SegmentAnchor memory) {
        SegmentAnchor memory anchored = _anchors[anchorKey(cameraId, startedAt)];
        if (bytes(anchored.cid).length == 0) revert AnchorNotFound();
        return anchored;
    }
}
