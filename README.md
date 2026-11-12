# BTC trading-bot entry — make.fun "Race a BTC trading bot live for 24 hours"

Entry: `main.py` (+ `vendor/makefun_bars.py`, the official SDK shim copied
byte-for-byte from the competition kit, which the rules explicitly allow).
Deadline: **Fri 13 Nov 2026, 2:09 AM IST** (547 entries already at build time).

## Strategy

Fast/slow EMA crossover trend-following on 1-minute closes, with a
trailing-stop-only exit and a fresh-breakout re-entry guard.

| Parameter | Value |
|---|---|
| Fast EMA span | 4 bars |
| Slow EMA span | 15 bars |
| Entry gap | fast > slow by > 5 bps of the close, and slow EMA rising |
| Re-entry guard | close must exceed the peak reached by the last position (no re-entry into chop) |
| Exit | trailing stop: close > 90 bps below the highest close since entry; or hard stop: position value > 100 bps below cost |
| Sizing | one position, full size (buy = all cash, capped by the hello weight room); full-position sells |
| Orders | at most 1 per reply, `max_slippage_bps` = 100 |

Deliberately **no EMA cross-down exit**: on the dev window a cross-down
inside the early leg cut winners short (house baseline: −$72.23, 52 trades).
One full-size round trip costs ~26–28 bps in fees/slippage/impact, so the
bot only trades when a real leg is forming and then rides it; re-entries
need a fresh high, which is what stops the chop bleeding.

All arithmetic is integer (EMAs are integer, truncating `//`); no floats,
no randomness, no clock, no environment, no files. Decisions use only the
bars seen so far plus the account state in the current batch.

## Test results (honest — losses included)

`test_harness.py` drives the real `main.py` as a subprocess over NDJSON,
exactly like the real harness: hello once, one batch per minute, then
`done`. Fills use the exact integer fill math from the competition harness
source (`sim/bars/engine.ts`, verified line-by-line: pool factor,
fee 4 bps, slippage 2 bps, max-slippage rejection, end-of-window flatten at
the last close vs its `c_depth`). The harness validates every reply:
one reply per batch, matching `seq`, ≤ 16 orders, valid order schema.

### Frozen dev window (1,440 bars, 2026-11-11 22:19 UTC → 2026-11-12 22:18 UTC)

| Run | Net PnL | Trades | Fees | Max drawdown | Verdict |
|---|---|---|---|---|---|
| 1 | **+$2.98** | 2 | $0.80 | 1.03% | dev gate **PASS** (PnL > 0) |
| 2 | **+$2.98** | 2 | $0.80 | 1.03% | byte-identical stdout → **deterministic** |

No protocol violations, no order rejections. Guardrails pass (≥ 1 trade,
maxDD 1.03% ≪ 25%). Wall time per full run: ~0.3 s (limit 1,800 s).
Trade: one round trip on the early leg (−2.30% buy-and-hold window; the
bot still finished positive).

### Synthetic 1,440-bar windows (same harness, same bot binary)

| Regime | Net PnL | Trades | Max DD |
|---|---|---|---|
| Uptrend +2%/day | +$222.01 | 1 | 0.65% |
| Slow grind up +0.8%/day | +$105.98 | 1 | 0.61% |
| Whipsaw | +$4.50 | 2 | 1.07% |
| Downtrend −2%/day | −$10.54 | 2 | 1.07% |
| Flat chop | −$25.74 | 6 | 2.80% |
| Crash −5% then recover | −$26.48 | 2 | 5.13% |

Read honestly: this bot **wins on trending days and loses on choppy or
crashing days** — the chop loss (~$26) is repeated false entries; the crash
loss comes from buying early dips (the −5%-in-one-minute crash is far more
extreme than any real 1-minute BTC move). Max drawdown stayed ≤ 5.2% in
every window, far under the 25% guardrail, so a losing race day still ranks
above any guardrail-failing entry. The dev-window margin is thin (+$2.98);
the design was chosen for its robustness profile (best worst-case across
grids and synthetic windows), not for the exact dev-maximum.

Grid work behind the choice: house EMA-cross baseline −$72.23; EMA-crossover
grid best +$1.68; momentum/breakout best +$1.59; EMA + re-entry guard best
+$3.20; this trail-only-exit variant at trail 70 bps gave **+$4.95** on dev
but worst-case −$46.54 (crash window). A follow-up probe (trail 55/70/80/90/
100/110, same harness, same 7 windows) found trail **90 bps** strictly
better on the selection criterion: worst-case −$26.48 (crash) vs −$46.54 at
trail 70, dev still positive at +$2.98; neighbours trail 80/100/110 give
worst-case −$48.44/−$28.45/−$26.48 with dev +$3.84/+$1.76/+$0.86, so 90 bps
is a stable plateau with the highest dev margin among the tied-best. A
120-min momentum-confirmation filter was tried and discarded: it delayed
entry and made the dev window −$4.34.

## Protocol details relied on

- `agent-fun/bars-replay/v1` over NDJSON on stdin/stdout. The bot answers
  **every batch with exactly one reply echoing its `seq`**; there is **no
  reply to `hello`** (the SDK enforces this — see note below).
- This competition has **no warmup bars** (`warmup_bars` absent from the
  kit), so the bot trades from bar ~17 (slow EMA + 2 bars), once its EMAs
  are warmed.
- Each batch's `bars` carries **only the bar closing at that minute** (plus
  a possible empty `bars` on a gap minute — the dev window has exactly one
  gap); the bot accumulates closes itself, deduped by `t`.
- Orders: buy `notional_quote_units` (sized to `min(cash, weight_room)`),
  sell full `qty`; each order carries `max_slippage_bps` 100; a buy fills at
  the next bar's open, a sell closes 100% of the position at the next bar's
  open; orders decided on the last batch are rejected (`after_end`) by the
  engine, which is not a violation.
- Flatten: the engine sells any open position at the last close at the end,
  so a bot that is still long is marked out at the final price (included in
  the harness numbers above).

**Correction to the task brief:** the brief said the bot should "reply
`{"protocol":"agent-fun/bars-replay/v1","role":"bot","version":"1.0"}` to
each hello". The authoritative sources (protocol schema, RULES.txt, and the
official SDK shim) define **no hello-reply message** — the bot only replies
to batches. `main.py` follows the kit, not the brief, on this point.

## What was NOT verified here

The official `grade-local` CLI cannot execute a Python bot on this machine:
its process sandbox runs Node 22 only and Python 3.13 needs Docker, which
is not installed. `grade-local` did load the bot directory (kit verified,
29 files; bot dir recognised) but refused to run it. The numbers above come
from this repo's own harness, whose fill math was checked line-by-line
against the official engine source and which reproduces the in-process
backtester exactly. The real grade still has to run on make.fun's side.

## Files

| File | What it is |
|---|---|
| `main.py` | **The entry** (repo root) |
| `vendor/makefun_bars.py` | Official SDK shim, byte-for-byte from the kit |
| `test_harness.py` | Subprocess replay harness: `python3 test_harness.py dev` / `<synthetic name>` |
| `backtest.py`, `grid.py`, `grid2.py`, `grid3.py`, `strat2.py`, `strat3.py`, `strat4.py`, `synth.py` | Research: in-process backtester, grids, strategy variants, synthetic windows |
| `dev_bars.ndjson.gz` | Frozen dev window (1,439 bars + 1 gap) from the kit |
| `kit/` | Downloaded competition kit (tarball + extracted) |

## How to run

```bash
cd ~/workspace/make-fun-bounties/btc-race-24h
python3 test_harness.py dev            # dev window, two runs, determinism check
python3 test_harness.py "uptrend +2%/day"
python3 test_harness.py "chop flat"
python3 test_harness.py "downtrend -2%/day"
```

## Submission (for the parent agent — not done here)

Only `main.py` (+ `vendor/`) is the entry. It still needs a public GitHub
repo owned by the user's account, the AI-transcript disclosure, and the
make.fun submission before **Fri 13 Nov 2026, 2:09 AM IST**.
