"""Tests for `gittensor.validator.utils.datetime_utils.get_lookback_cutoff`.

The cutoff is the surface that controls cross-validator agreement on the
scoring window. Each test pins the property the bug fix depends on:
quantization to UTC midnight removes the per-second wall-clock divergence
that previously decided whether a boundary PR was included.
"""

from datetime import datetime, timedelta, timezone

import pytest

datetime_utils = pytest.importorskip(
    'gittensor.validator.utils.datetime_utils',
    reason='Requires gittensor package',
)

get_lookback_cutoff = datetime_utils.get_lookback_cutoff


def _patch_now(monkeypatch, fixed: datetime) -> None:
    """Pin `datetime.now(...)` inside datetime_utils to `fixed`.

    Subclassing real `datetime` keeps `cutoff - timedelta(...)` and
    `cutoff.replace(...)` operating on a real datetime.
    """

    class _FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed

    monkeypatch.setattr(datetime_utils, 'datetime', _FrozenDateTime)


class TestGetLookbackCutoff:
    def test_returns_utc_midnight(self, monkeypatch):
        _patch_now(monkeypatch, datetime(2026, 5, 5, 14, 30, 45, 123456, tzinfo=timezone.utc))
        cutoff = get_lookback_cutoff(35)
        assert (cutoff.hour, cutoff.minute, cutoff.second, cutoff.microsecond) == (0, 0, 0, 0)

    def test_returns_tz_aware_utc(self, monkeypatch):
        _patch_now(monkeypatch, datetime(2026, 5, 5, 14, 30, 45, tzinfo=timezone.utc))
        cutoff = get_lookback_cutoff(35)
        assert cutoff.tzinfo is timezone.utc

    def test_cutoff_date_is_n_days_before_now_date(self, monkeypatch):
        now = datetime(2026, 5, 5, 14, 30, 45, tzinfo=timezone.utc)
        _patch_now(monkeypatch, now)
        cutoff = get_lookback_cutoff(35)
        assert cutoff.date() == (now - timedelta(days=35)).date()

    @pytest.mark.parametrize('lookback_days', [0, 1, 7, 35, 365])
    def test_lookback_days_parameter_applied(self, monkeypatch, lookback_days):
        now = datetime(2026, 5, 5, 14, 30, 45, tzinfo=timezone.utc)
        _patch_now(monkeypatch, now)
        cutoff = get_lookback_cutoff(lookback_days)
        assert cutoff.date() == (now - timedelta(days=lookback_days)).date()

    def test_stable_across_same_utc_day(self, monkeypatch):
        """The bug fix's invariant: any two reads within the same UTC day must agree.

        Without quantization, a 30-second skew between validators flipped a
        boundary PR's inclusion. With quantization, the cutoff is identical
        for every read between 00:00:00 and 23:59:59 of the same UTC day.
        """
        same_day_times = [
            datetime(2026, 5, 5, 0, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 5, 5, 0, 0, 30, tzinfo=timezone.utc),
            datetime(2026, 5, 5, 12, 34, 56, tzinfo=timezone.utc),
            datetime(2026, 5, 5, 23, 59, 59, 999999, tzinfo=timezone.utc),
        ]
        cutoffs = []
        for t in same_day_times:
            _patch_now(monkeypatch, t)
            cutoffs.append(get_lookback_cutoff(35))
        assert len(set(cutoffs)) == 1

    def test_advances_exactly_one_day_at_utc_midnight(self, monkeypatch):
        """Day-rollover sanity: 23:59:59 -> 00:00:00 next day shifts cutoff by 1 day."""
        before = datetime(2026, 5, 5, 23, 59, 59, tzinfo=timezone.utc)
        after = datetime(2026, 5, 6, 0, 0, 0, tzinfo=timezone.utc)

        _patch_now(monkeypatch, before)
        cutoff_before = get_lookback_cutoff(35)
        _patch_now(monkeypatch, after)
        cutoff_after = get_lookback_cutoff(35)

        assert cutoff_after - cutoff_before == timedelta(days=1)

    def test_does_not_round_forward_within_day(self, monkeypatch):
        """Quantization is floor-to-midnight, never ceil — the window is at most ~24h larger than `lookback_days`, never smaller."""
        now = datetime(2026, 5, 5, 23, 59, 59, tzinfo=timezone.utc)
        _patch_now(monkeypatch, now)
        cutoff = get_lookback_cutoff(35)
        raw = now - timedelta(days=35)
        assert cutoff <= raw
        assert (raw - cutoff) < timedelta(days=1)
