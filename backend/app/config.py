"""Runtime configuration from environment variables."""

from __future__ import annotations

import os


def get_jwt_secret() -> str:
    key = os.getenv("JWT_SECRET_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "JWT_SECRET_KEY is not set. Set it in the environment "
            "(see backend/.env.example)."
        )
    return key


def get_jwt_access_token_expire_minutes() -> int:
    raw = os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60")
    try:
        return max(1, min(60 * 24 * 7, int(raw)))  # cap at 7 days
    except ValueError:
        return 60


def get_camera_probe_timeout_seconds() -> float:
    raw = os.getenv("CAMERA_PROBE_TIMEOUT_SECONDS", "2")
    try:
        return max(0.5, min(10.0, float(raw)))
    except ValueError:
        return 2.0


def get_pinata_jwt() -> str:
    token = os.getenv("PINATA_JWT", "").strip()
    if not token:
        raise RuntimeError(
            "PINATA_JWT is not set. Set it in the environment "
            "(see backend/.env.example)."
        )
    return token


def get_pinata_timeout_seconds() -> float:
    raw = os.getenv("PINATA_TIMEOUT_SECONDS", "120")
    try:
        return max(5.0, min(600.0, float(raw)))
    except ValueError:
        return 120.0


def get_polygon_rpc_url() -> str:
    url = (
        os.getenv("POLYGON_RPC_URL", "").strip()
        or os.getenv("AMOY_RPC_URL", "").strip()
        or "https://rpc-amoy.polygon.technology"
    )
    return url


def get_polygon_chain_id() -> int:
    raw = os.getenv("POLYGON_CHAIN_ID", "80002")
    try:
        return int(raw)
    except ValueError:
        return 80002


def get_datachain_contract_address() -> str:
    address = os.getenv("DATACHAIN_CONTRACT_ADDRESS", "").strip()
    if not address:
        raise RuntimeError(
            "DATACHAIN_CONTRACT_ADDRESS is not set. Deploy with "
            "npm run deploy:amoy and copy the address "
            "(see backend/.env.example)."
        )
    return address


def get_anchor_private_key() -> str:
    key = (
        os.getenv("DATACHAIN_PRIVATE_KEY", "").strip()
        or os.getenv("AMOY_PRIVATE_KEY", "").strip()
    )
    if not key:
        raise RuntimeError(
            "DATACHAIN_PRIVATE_KEY (or AMOY_PRIVATE_KEY) is not set. "
            "Use the contract owner testnet key (see backend/.env.example)."
        )
    return key


def get_anchor_rpc_timeout_seconds() -> float:
    raw = os.getenv("ANCHOR_RPC_TIMEOUT_SECONDS", "30")
    try:
        return max(5.0, min(120.0, float(raw)))
    except ValueError:
        return 30.0


def get_anchor_max_attempts() -> int:
    raw = os.getenv("ANCHOR_MAX_ATTEMPTS", "3")
    try:
        return max(1, min(10, int(raw)))
    except ValueError:
        return 3


def get_anchor_retry_delay_seconds() -> float:
    raw = os.getenv("ANCHOR_RETRY_DELAY_SECONDS", "2")
    try:
        return max(0.0, min(30.0, float(raw)))
    except ValueError:
        return 2.0
