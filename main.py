#!/usr/bin/env python3
"""BTC trend bot for make.fun "Race a BTC trading bot live for 24 hours"
(agent-fun/bars-replay/v1).

Strategy: fast/slow EMA crossover trend-following on 1-minute closes, with
a trailing-stop-only exit and a fresh-breakout re-entry guard.

  * Entry (flat):   fast EMA (4 bars) above slow EMA (15 bars) by > 5 bps of
                    the close, slow EMA rising, and the close above the peak
                    reached by the last position (a fresh breakout; no
                    re-entry into chop).
  * Exit (long):    trailing stop — close more than 90 bps below the highest
                    close since entry — or a hard stop: position value more
                    than 100 bps below its cost. No EMA cross-down exit: a
                    cross-down inside a grinding leg cuts winners short.
  * Sizing:         one position, full size (buy = all cash, capped by the
                    hello weight room), full-position sells. One order max
                    per reply, max_slippage_bps 100.

All arithmetic is integer (prices are integer strings at price_scale 5);
no floats, no randomness, no clock, no environment, no files. The vendored
SDK shim (vendor/makefun_bars.py, byte-for-byte from the competition kit)
owns the wire: one reply per batch, echoing its seq.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bars

BPS = 10_000
FAST_SPAN = 4
SLOW_SPAN = 15
ENTRY_GAP_BPS = 5
TRAIL_BPS = 90
STOP_BPS = 100
MAX_SLIPPAGE_BPS = 100


class _Symbol:
    """Per-symbol trend state (integer EMAs, peak tracking)."""

    __slots__ = ("closes", "ema_fast", "ema_slow", "prev_slow",
                 "peak_close", "last_peak", "last_t")

    def __init__(self):
        self.closes = []
        self.ema_fast = None
        self.ema_slow = None
        self.prev_slow = None
        self.peak_close = None
        self.last_peak = None
        self.last_t = None

    def push(self, close, t):
        if self.last_t is not None and t <= self.last_t:
            return False  # duplicate / out-of-order bar: ignore
        self.last_t = t
        self.closes.append(close)
        if self.ema_fast is None:
            self.ema_fast = close
            self.ema_slow = close
        else:
            self.ema_fast += (close - self.ema_fast) * 2 // (FAST_SPAN + 1)
            self.ema_slow += (close - self.ema_slow) * 2 // (SLOW_SPAN + 1)
        return True


_SYMBOLS = {}


def _get(symbol):
    s = _SYMBOLS.get(symbol)
    if s is None:
        s = _SYMBOLS[symbol] = _Symbol()
    return s


def on_batch(state, batch):
    # No new information (gap minute) -> no new decision.
    if state.warming_up:
        return []
    fresh = []
    for bar in batch.get("bars", []):
        sym = bar["symbol"]
        if sym not in state.symbols:
            continue
        if _get(sym).push(int(bar["c"]), int(bar["t"])):
            fresh.append(sym)
    if not fresh:
        return []

    orders = []
    min_notional = int(state.hello["fees"]["min_notional_quote_units"])
    for symbol in fresh:
        s = _get(symbol)
        if len(s.closes) < SLOW_SPAN + 2:
            continue
        prev_slow = s.prev_slow
        s.prev_slow = s.ema_slow
        if prev_slow is None:
            continue
        close = s.closes[-1]
        held = state.positions.get(symbol)
        if held is not None and held.qty > 0:
            if s.peak_close is None or close > s.peak_close:
                s.peak_close = close
            pos_value = state.value(symbol, held.qty)
            trail_hit = close * BPS < s.peak_close * (BPS - TRAIL_BPS)
            stop_hit = pos_value * BPS < held.cost * (BPS - STOP_BPS)
            if trail_hit or stop_hit:
                orders.append({
                    "side": "sell",
                    "symbol": symbol,
                    "qty": held.qty,
                    "max_slippage_bps": MAX_SLIPPAGE_BPS,
                })
                s.last_peak = s.peak_close
                s.peak_close = None
        else:
            gap_bps = (s.ema_fast - s.ema_slow) * BPS // close if close else 0
            fresh_high = s.last_peak is None or close > s.last_peak
            if (s.ema_fast > s.ema_slow and gap_bps > ENTRY_GAP_BPS
                    and s.ema_slow > prev_slow and fresh_high):
                amount = state.cash
                room = state.weight_room(symbol)
                if room < amount:
                    amount = room
                if amount >= min_notional and amount > 0:
                    orders.append({
                        "side": "buy",
                        "symbol": symbol,
                        "notional_quote_units": amount,
                        "max_slippage_bps": MAX_SLIPPAGE_BPS,
                    })
                    s.peak_close = close
        if len(orders) >= 1:
            break  # at most one order per reply; one symbol in this universe
    return orders


if __name__ == "__main__":
    makefun_bars.run(on_batch)
