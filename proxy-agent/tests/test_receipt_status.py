"""receipt_for_snap must not raise on malformed poll_diag payloads."""
from __future__ import annotations

from core.receipt_status import receipt_for_snap


def test_receipt_bad_inventory_ts_no_crash():
    snap = {
        "fast": {},
        "slow": {},
        "inventory": {"values_published": 3, "ts": "not-a-float"},
    }
    r = receipt_for_snap(snap)
    assert r["state"] == "inventory_only"
    assert "inventory" in r["detail"]


def test_receipt_bad_tier_counters_no_crash():
    snap = {
        "fast": {"tier_total": "x", "macro_skipped": None, "snmp_failed": {}},
        "slow": {},
    }
    r = receipt_for_snap(snap)
    assert "state" in r and "label" in r
