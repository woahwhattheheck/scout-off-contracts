#!/usr/bin/env python3
"""Snapshot and restore the paired ScoutChain deployment-address files.

Only local files are touched. The health check remains the responsibility of
rollback.sh after both files have been restored and verified.
"""

import json
import os
from pathlib import Path
import sys
import tempfile

CONTRACTS = ("registration", "verification", "progress", "scout_access")
FIELDS = ("id", "wasm_hash")


class SnapshotError(ValueError):
    """A snapshot is missing, incomplete, or inconsistent."""


def env_values(raw: bytes) -> dict[str, str]:
    values = {}
    for line in raw.decode("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep or not key.isidentifier() or key in values:
            raise SnapshotError(f"invalid or repeated deployment key: {key!r}")
        values[key] = value.strip()
    for name in CONTRACTS:
        prefix = name.upper()
        for field in FIELDS:
            key = f"{prefix}_CONTRACT_{field.upper()}" if field == "id" else f"{prefix}_CONTRACT_WASM_HASH"
            if not values.get(key):
                raise SnapshotError(f"missing deployment key: {key}")
    return values


def normalized(raw_env: bytes, network: str) -> dict:
    values = env_values(raw_env)
    if network not in ("testnet", "mainnet", "local"):
        raise SnapshotError(f"unsupported network: {network}")
    return {
        "network": network,
        "contracts": {
            name: {
                "id": values[f"{name.upper()}_CONTRACT_ID"],
                "wasm_hash": values[f"{name.upper()}_CONTRACT_WASM_HASH"],
            }
            for name in CONTRACTS
        },
    }


def check_pair(raw_env: bytes, raw_json: bytes, expected_network: str | None = None) -> dict:
    try:
        obj = json.loads(raw_json)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SnapshotError(f"invalid deployment JSON: {exc}") from exc
    if not isinstance(obj, dict) or not isinstance(obj.get("network"), str):
        raise SnapshotError("deployment JSON lacks network")
    if expected_network is not None and obj["network"] != expected_network:
        raise SnapshotError(f"snapshot network {obj['network']!r} != requested {expected_network!r}")
    expected = normalized(raw_env, obj["network"])
    if obj.get("contracts") != expected["contracts"]:
        raise SnapshotError("flat and JSON contract addresses / WASM hashes disagree")
    return expected


def atomic_write(path: Path, data: bytes) -> None:
    fd, temp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def snapshot(root: Path, network: str) -> str:
    raw_env = (root / ".env.contracts").read_bytes()
    old_json = root / ".env.contracts.json"
    if old_json.is_file():
        raw_json = old_json.read_bytes()
        check_pair(raw_env, raw_json)
        description = "paired existing JSON"
    else:
        raw_json = (json.dumps(normalized(raw_env, network), indent=2) + "\n").encode()
        description = "legacy JSON reconstructed from flat addresses"
    atomic_write(root / ".env.contracts.json.snapshot", raw_json)
    atomic_write(root / ".env.contracts.snapshot", raw_env)
    return description


def restore(root: Path, network: str) -> str:
    env_snapshot = root / ".env.contracts.snapshot"
    if not env_snapshot.is_file():
        raise SnapshotError("no .env.contracts.snapshot; no previous deployment to restore")
    raw_env = env_snapshot.read_bytes()
    json_snapshot = root / ".env.contracts.json.snapshot"
    if json_snapshot.is_file():
        raw_json = json_snapshot.read_bytes()
        description = "paired snapshot"
        check_pair(raw_env, raw_json, network)
    else:
        raw_json = (json.dumps(normalized(raw_env, network), indent=2) + "\n").encode()
        description = "legacy snapshot; rebuilt matching JSON"
        check_pair(raw_env, raw_json, network)
    env_dest = root / ".env.contracts"
    json_dest = root / ".env.contracts.json"
    previous = [(p, p.read_bytes() if p.exists() else None) for p in (env_dest, json_dest)]
    try:
        atomic_write(env_dest, raw_env)
        atomic_write(json_dest, raw_json)
        check_pair(env_dest.read_bytes(), json_dest.read_bytes(), network)
    except Exception:
        # Best effort: never leave the new flat file paired with an old JSON.
        for path, data in previous:
            if data is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write(path, data)
        raise
    return description


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] not in ("snapshot", "restore"):
        print("usage: contract-env-pair.py {snapshot|restore} {testnet|mainnet|local}", file=sys.stderr)
        return 2
    action, network = sys.argv[1:]
    try:
        detail = snapshot(Path.cwd(), network) if action == "snapshot" else restore(Path.cwd(), network)
    except (OSError, SnapshotError) as exc:
        print(f"ERROR: contract environment {action}: {exc}", file=sys.stderr)
        return 1
    print(f"Contract environment {action} verified ({detail}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
