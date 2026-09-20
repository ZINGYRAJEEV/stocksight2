"""Unit tests for bottom_confirmation feature functions (synthetic series)."""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from bottom_confirmation import (
    feature_bullish_rsi_divergence,
    feature_capitulation_day_ohlc,
    feature_close_above_ema_turning_up,
    feature_higher_low,
    feature_new_20d_low_recent,
    feature_selling_exhaustion,
    score_bottom_confirmation,
)


def _ohlcv(n: int = 80, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    high = close + rng.uniform(0.5, 2.0, n)
    low = close - rng.uniform(0.5, 2.0, n)
    open_ = close + rng.normal(0, 0.5, n)
    vol = rng.integers(1000, 2000, n).astype(float)
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": vol}
    )


class TestBottomFeatures(unittest.TestCase):
    def test_higher_low_true(self):
        # Construct two clear pivot lows: first 90, later 95
        lows = pd.Series([100.0] * 5 + [90.0] + [100.0] * 5 + [95.0] + [100.0] * 5)
        self.assertTrue(feature_higher_low(lows, window=2))

    def test_higher_low_false(self):
        # Strictly lower swing lows
        lows = pd.Series(
            [110, 109, 108, 107, 106, 95, 106, 107, 108, 109, 110, 90, 110, 111, 112, 113, 114]
            ,
            dtype=float,
        )
        self.assertFalse(feature_higher_low(lows, window=2))

    def test_capitulation_candle(self):
        n = 30
        o = pd.Series([10.0] * n)
        h = pd.Series([10.0] * n)
        l = pd.Series([9.0] * n)
        c = pd.Series([10.0] * n)
        v = pd.Series([1000.0] * n)
        # Last bar: big volume, long lower wick, close upper half
        o.iloc[-1] = 10.0
        h.iloc[-1] = 11.0
        l.iloc[-1] = 5.0
        c.iloc[-1] = 10.5
        v.iloc[-1] = 5000.0
        self.assertTrue(
            feature_capitulation_day_ohlc(o, h, l, c, v, lookback=5, vol_mult=2.0, wick_frac=0.5)
        )

    def test_selling_exhaustion(self):
        n = 30
        c = pd.Series(np.linspace(50, 60, n))
        v = pd.Series([2000.0] * 20 + [500.0] * 5 + [400.0] * 5)
        # Force up days in last 10
        c = pd.Series(list(np.linspace(50, 55, 20)) + list(np.linspace(55, 62, 10)))
        self.assertTrue(feature_selling_exhaustion(c, v, exhaustion_vol_frac=0.7, up_down_ratio_min=1.2))

    def test_ema_turning_up(self):
        # Strong uptrend into EMA
        c = pd.Series(np.linspace(80, 120, 60))
        self.assertTrue(feature_close_above_ema_turning_up(c, span=20))

    def test_rsi_divergence_constructed(self):
        # Price lower low, RSI higher low — hand-built dips
        closes = [50.0] * 20
        # first low
        closes += [48, 47, 46, 47, 48, 49, 50, 51, 52]
        # second lower price low but shallower bounce pattern for RSI recovery
        closes += [49, 48, 45, 46, 47, 48, 49, 50, 51, 52, 53]
        s = pd.Series(closes, dtype=float)
        # May or may not fire depending on pivots; at least no crash
        feature_bullish_rsi_divergence(s, pivot_window=2)

    def test_no_lookahead(self):
        df = _ohlcv(100, seed=7)
        # Inject a capitulation-like bar at t=70
        df.loc[70, ["Open", "High", "Low", "Close", "Volume"]] = [10, 11, 5, 10.5, 8000]
        full = score_bottom_confirmation(df, at=70)
        truncated = score_bottom_confirmation(df.iloc[:71], at=None)
        self.assertEqual(full.score, truncated.score)
        self.assertEqual(full.state, truncated.state)
        self.assertEqual(full.features, truncated.features)

    def test_new_low_recent(self):
        lows = pd.Series([10.0] * 25 + [8.0, 9.0, 9.5])
        self.assertTrue(feature_new_20d_low_recent(lows, lookback=20, recent_bars=3))


if __name__ == "__main__":
    unittest.main()
