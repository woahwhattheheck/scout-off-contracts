"""Focused regression for contract address rollback, no chain calls."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("pair", Path(__file__).resolve().parents[1] / "scripts" / "contract-env-pair.py")
pair = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pair)


def flat(stamp):
    return ("\n".join(
        f"{name.upper()}_CONTRACT_{field}={stamp}-{name}-{field}"
        for name in pair.CONTRACTS for field in ("ID", "WASM_HASH")
    ) + "\n").encode()


class ContractPairRollback(unittest.TestCase):
    def test_new_snapshot_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = flat("old")
            (root / ".env.contracts").write_bytes(old)
            original_json = (pair.json.dumps(pair.normalized(old, "testnet"), indent=2) + "\n").encode()
            (root / ".env.contracts.json").write_bytes(original_json)
            self.assertIn("paired", pair.snapshot(root, "testnet"))
            (root / ".env.contracts").write_bytes(flat("bad"))
            (root / ".env.contracts.json").write_text('{}')
            pair.restore(root, "testnet")
            self.assertEqual((root / ".env.contracts").read_bytes(), old)
            self.assertEqual((root / ".env.contracts.json").read_bytes(), original_json)

    def test_legacy_flat_only_snapshot_repairs_stale_json(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = flat("old")
            (root / ".env.contracts.snapshot").write_bytes(old)
            (root / ".env.contracts.json").write_text('{}')
            self.assertIn("legacy", pair.restore(root, "testnet"))
            self.assertEqual(pair.check_pair((root / ".env.contracts").read_bytes(), (root / ".env.contracts.json").read_bytes(), "testnet"), pair.normalized(old, "testnet"))

    def test_mismatched_snapshots_do_not_touch_current_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old, bad = flat("old"), flat("bad")
            (root / ".env.contracts.snapshot").write_bytes(old)
            (root / ".env.contracts.json.snapshot").write_text(pair.json.dumps(pair.normalized(bad, "testnet")))
            (root / ".env.contracts").write_bytes(bad)
            (root / ".env.contracts.json").write_text("unchanged")
            with self.assertRaises(pair.SnapshotError):
                pair.restore(root, "testnet")
            self.assertEqual((root / ".env.contracts").read_bytes(), bad)
            self.assertEqual((root / ".env.contracts.json").read_text(), "unchanged")

    def test_wrong_network_does_not_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = flat("old")
            (root / ".env.contracts.snapshot").write_bytes(old)
            (root / ".env.contracts.json.snapshot").write_text(pair.json.dumps(pair.normalized(old, "mainnet")))
            with self.assertRaises(pair.SnapshotError):
                pair.restore(root, "testnet")
            self.assertFalse((root / ".env.contracts").exists())

    def test_missing_current_json_generates_paired_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env.contracts").write_bytes(flat("old"))
            pair.snapshot(root, "local")
            pair.check_pair((root / ".env.contracts.snapshot").read_bytes(), (root / ".env.contracts.json.snapshot").read_bytes(), "local")


if __name__ == "__main__":
    unittest.main()
