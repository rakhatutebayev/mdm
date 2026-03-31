"""Cleanup helpers should remove in-memory traces for deleted devices."""
from __future__ import annotations

import sys
import types

sys.modules.setdefault("puresnmp", types.SimpleNamespace())

from collectors import snmp_poller
from core import poll_diag


def test_poll_diag_clear_device():
    poll_diag.record_tier("dev-x", "fast", {"values_published": 1})
    assert poll_diag.get_snapshot("dev-x")
    poll_diag.clear_device("dev-x")
    assert poll_diag.get_snapshot("dev-x") == {}


def test_snmp_poller_forget_device():
    snmp_poller._record_sent("dev-y", "sysName", "host1")
    assert snmp_poller._last_values.get("dev-y")
    assert snmp_poller._last_sent.get("dev-y")
    snmp_poller.forget_device("dev-y")
    assert "dev-y" not in snmp_poller._last_values
    assert "dev-y" not in snmp_poller._last_sent
