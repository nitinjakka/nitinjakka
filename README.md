# Trading Suite

> Personal trading/research workspace. Work in progress. **Not investment advice.**
>
> **Time convention: every time in this README is US Eastern (ET).** Robinhood MCP
> responses return UTC — convert before writing anything down.

One project group covering an intraday ORB/VWAP breakout strategy (Pine + Python
backtests), a live bridge that lets Claude read and drive the TradingView Desktop app, two
Robinhood toolsets (direct `robin_stocks` scripts and an MCP-based history/P&L analysis), a
0DTE credit-spread cycler bot, and a SPY dip-call options study. Everything lives under
`E:\Nitin_Hadoop\Claude` on a Windows 10 Pro for Workstations machine, except the
credit-spread and Mode-B bots, which are built to run on a Linux jump server under
`/opt/option_spread`.

## Components

**`robinhood-orders`, `spy-dip-calls` and `tradingview-mcp` are SIBLING folders of
`trading-suite-repo`, not subfolders.** All of them sit directly under `E:\Nitin_Hadoop\Claude`.

| Component | Path on E: | What it does |
|---|---|---|
| **Trading Suite** (this repo) | `E:\Nitin_Hadoop\Claude\trading-suite-repo` | ORB + VWAP intraday strategy: spec, Pine v6 reference implementation, backtests |
| suite-backtest | `…\trading-suite-repo\suite-backtest` | Python backtest engines, raw 1m/5m data, options P&L results |
| option-spread | `…\trading-suite-repo\option-spread` | `spread_cycler` — repeat-cycle 0DTE credit-spread bot; places real multi-leg orders when `LIVE=1` |
| robinhood-tools | `…\trading-suite-repo\robinhood-tools` | Standalone `robin_stocks` scripts: balances, sell-all, order-test stubs |
| jump-bot | `…\trading-suite-repo\jump-bot` | Mode-B bot + symbol-pool rotation systemd units for the jump server |
| **tradingview-mcp** *(sibling)* | `E:\Nitin_Hadoop\Claude\tradingview-mcp` | MCP bridge (84 tools + a `tv` CLI) from Claude to the running TradingView Desktop app over CDP port 9222 |
| **robinhood-orders** *(sibling)* | `E:\Nitin_Hadoop\Claude\robinhood-orders` | Full Robinhood order-history export + realized/unrealized P&L analysis |
| **spy-dip-calls** *(sibling)* | `E:\Nitin_Hadoop\Claude\spy-dip-calls` | Backtest + live screen for buying long SPY calls on −5% dips |
| **rh_agentic** *(sibling)* | `E:\Nitin_Hadoop\Claude\rh_agentic` | Aggregation scripts + saved pages for the Agentic-account order pull |

---

## 1. Trading Suite — strategy, Pine, backtests

**Prerequisites:** a TradingView account for the Pine studies; Python 3 for
`suite-backtest/`. No credentials or env vars.
**Run:** the Pine files load in TradingView; the backtests are plain scripts, e.g.
`python suite-backtest/bt_frac100.py`. `azure-pipelines.yml` is the repo's CI definition.

`strategy-spec.md` is the authoritative, platform-independent specification;
`combined-suite.pine` is the Pine v6 reference implementation (Module 5 = trade engine).

### Validated results (methodology in `strategy-spec.md` §8)
- ORB 1-min, 29 sessions: **90.3% win, PF 1.90** (84.4% held out); all-day mode 1-min:
  90.5% win, PF 1.29.
- **SPY/VOO does NOT work** (PF < 1 in every test) — trade NVDA/QQQ/TSLA/AAPL-class movers.
- $100 accounts: options structurally unviable; fractional underlying (`bt_frac100.py`,
  Mode B long-only, 4 tickers) or a trend-filtered leveraged ETF (`bt_trend100.py`,
  TQQQ / 200-SMA) are the viable vehicles.

*Discrepancy: the TradingView setup notes quote an **87%** win rate for the same ORB config,
measured on underlying price moves over a different sample than the 90.3% above. Neither
figure is option-premium P&L — see §2.8 open items.*

### Strategy reference
**Trend — 6-vote confluence:** `EMA 9/21` · `Price vs EMA50` · `RSI 14` · `MACD` · `DMI` ·
`60m HTF`. Needs **|score| ≥ 2** to call CALL or PUT. **ADX < 20 = NO-GO** (chop filter —
this is what protects against theta bleed in rangebound tape).

**Entry:** 9:30 gap below **0.30%** = NO-GO → 9:30–9:35 mark the opening range, don't trade
→ after 9:35 break above OR high = **CALL**, below OR low = **PUT** → **VWAP must confirm**
→ no new signals after **150 min** (≈12:00 ET) → skip if S/R is closer than **0.25%**.

**Exit, first to hit:** stop at the opposite side of the opening range · target
**0.5 × ATR(14)** capped at the nearest S/R · time stop 390 bars (1m) · **EOD flat 15:55 ET,
always**. The tight 0.5×ATR target is what produces the high hit rate.

**S&R:** Module 1 Swing S&R = 25-bar pivots, solid → dotted once broken; Module 3 Pivot S/R
= 3 levels per side, and these cap the targets.

---

## 2. tradingview-mcp — Claude ⇄ TradingView Desktop bridge

*`E:\Nitin_Hadoop\Claude\tradingview-mcp` (sibling). Set up 2026-08-23. Upstream:
<https://github.com/tradesdontlie/tradingview-mcp>, cloned with `git clone --depth 1`. MIT.*

Different from the hosted `tradingview` MCP screener in Claude Code: that one serves market
data from TradingView's public API, **this one reads the actual desktop app**, including
custom Pine indicator values that exist nowhere else.

```
Claude Desktop  ←→  MCP server (stdio)  ←→  CDP :9222  ←→  TradingView Desktop (Electron)
```

MCP over stdio (84 tools) plus a `tv` CLI (30 commands / 66 subcommands); Chrome DevTools
Protocol on **localhost:9222**; streaming is a poll-and-diff loop emitting JSONL to stdout.
Only dependencies are `@modelcontextprotocol/sdk` and `chrome-remote-interface`.

### 2.1 Prerequisites
TradingView Desktop with a **valid paid subscription**; **Node.js 18+** (installed here:
v24.18.0 / npm 11.16.0); Claude Desktop or Claude Code with MCP support, or any terminal
for the CLI. No API keys or tokens — the bridge only talks to localhost:9222.

### 2.2 Install

```bash
git clone https://github.com/tradesdontlie/tradingview-mcp.git
cd tradingview-mcp
npm install
```

### 2.3 Launching TradingView with CDP (Windows / Microsoft Store build)

**Every time**, start TradingView with:

```
E:\Nitin_Hadoop\Claude\Start TradingView for Claude.bat
```

Double-click it; consider pinning it to the taskbar. It calls `Start-TradingView-CDP.ps1`
via `powershell.exe -NoProfile -ExecutionPolicy Bypass`.

⚠️ **Starting TradingView normally from the Start Menu leaves port 9222 closed and the
connection dead.** The debug port can only be enabled at launch.

TradingView here is a **Microsoft Store (MSIX) package**, not a normal desktop install:
package `TradingView.Desktop`, PackageFamilyName `TradingView.Desktop_n534cwy3pjxzj`, AUMID
`TradingView.Desktop_n534cwy3pjxzj!TradingView.Desktop`, installed at
`C:\Program Files\WindowsApps\TradingView.Desktop_<version>_x64__n534cwy3pjxzj` — **the
`<version>` changes on every update; never hardcode this path.** That folder is
ACL-protected, so every documented launch method fails (see Troubleshooting). **What works**
is the `IApplicationActivationManager::ActivateApplication` COM API, which passes `argv`
through to Desktop-Bridge/Electron apps; `Start-TradingView-CDP.ps1` implements it,
resolving the package with `Get-AppxPackage` at runtime and reading the app id from
`AppxManifest.xml`, so TradingView updates won't break it. `Get-AppxPackage` fails under
PowerShell 7 — run Appx cmdlets via `powershell.exe` (Windows PowerShell 5.1).

Upstream launchers for other platforms / non-Store installs:

```bash
scripts\launch_tv_debug.bat                          # Windows
./scripts/launch_tv_debug_mac.sh                     # Mac
./scripts/launch_tv_debug_linux.sh                   # Linux
/path/to/TradingView --remote-debugging-port=9222    # manual, any platform
```

If auto-detection fails, TradingView usually lives at
`/Applications/TradingView.app/Contents/MacOS/TradingView` (Mac),
`%LOCALAPPDATA%\TradingView\TradingView.exe` or
`%PROGRAMFILES%\WindowsApps\TradingView*\TradingView.exe` (Windows), and
`/opt/TradingView/tradingview`, `~/.local/share/TradingView/TradingView` or
`/snap/tradingview/current/tradingview` (Linux). The key flag is always
`--remote-debugging-port=9222`.

### 2.4 Configuration

**Claude Desktop** — `C:\Users\Nitin\AppData\Roaming\Claude\claude_desktop_config.json`
(`%APPDATA%\Claude\`); existing `coworkUserFilesPath` and `preferences` were preserved, and
the pre-edit backup is `claude_desktop_config.json.20260823-223158.bak`:

```json
"mcpServers": {
  "tradingview": {
    "command": "node",
    "args": ["E:\\Nitin_Hadoop\\Claude\\tradingview-mcp\\src\\server.js"]
  }
}
```

**Claude Code** — `~/.claude/.mcp.json` or a project `.mcp.json`, same shape with
`"args": ["/path/to/tradingview-mcp/src/server.js"]`.

**After editing, Claude Desktop must be FULLY quit** — right-click the tray icon → Quit;
closing the window is not enough. New tools only appear in **new** conversations.

### 2.5 Verify

```bash
node E:\Nitin_Hadoop\Claude\tradingview-mcp\src\cli\index.js status
```

Healthy output has `"cdp_connected": true` and `"api_available": true`. Or ask Claude
*"Use tv_health_check to verify TradingView is connected"*. `npm test` runs 29 tests (Pine
static analysis, server-side compile, CLI routing) and needs TradingView up on 9222.

### 2.6 CLI

Every MCP tool is also a `tv` command; all output is JSON for piping with `jq`. Install
globally with `npm link`, or run `node src/cli/index.js <command>` — locally that is
`node tradingview-mcp/src/cli/index.js <cmd>` from `E:\Nitin_Hadoop\Claude`.

```
tv status              CDP connection health          tv launch / discover / ui-state
tv state               symbol, timeframe, indicator list + entity ids
tv quote               live price                     tv ohlcv / values / info / search
tv symbol / timeframe / type / range / scroll
tv data tables         indicator dashboard (bias, S/R, ORB, position)
tv data lines          S&R levels drawn by Pine       tv data labels/boxes/strategy/
tv data values         current indicator values         trades/equity/depth/indicator
tv layout list / switch                                saved layouts
tv tab list / switch / new / close                     needed after layout switches
tv indicator get <id>  all input values               tv indicator add/remove/toggle
tv indicator set <id> -i '{...}'                       change inputs (use Bash for JSON)
tv screenshot -r chart visual check                    (regions: full, chart, strategy_tester)
tv pine list           saved Pine scripts             tv pine get/set/compile/analyze/
                                                        check/save/new/open/errors/console
tv draw shape/list/get/remove/clear                    tv alert list/create/delete
tv watchlist get/add                                   tv pane list/layout/focus/symbol
tv replay start/step/stop/status/autoplay/trade
tv stream quote/bars/values/lines/labels/tables/all
tv ui click/keyboard/hover/scroll/find/eval/type/panel/fullscreen/mouse
```

Streaming polls the local Desktop instance over CDP only; nothing connects to TradingView's
servers. Examples: `tv stream quote | jq '.close'`, `tv stream lines --filter "NY Levels"`,
`tv stream tables --filter Profiler`, `tv stream all`. Use `study_filter` to target one
indicator, `summary: true` on OHLCV, and `verbose: true` only when raw data is needed.

Full tool reference and Claude's tool decision tree: `tradingview-mcp/CLAUDE.md` (read
automatically). Also present: `SETUP_GUIDE.md`, `RESEARCH.md`, `SECURITY.md`, `CONTRIBUTING.md`.

### 2.7 Chart layouts

| Layout | ID | Notes |
|---|---|---|
| **Claude** | 201759691 | 3 panes: SPY 1m (main) / 15m / 5m — the working layout |
| 10s1m5m | 42047031 | Multi-pane SPY |
| New_try | 120823986 | Currently on QCOM 1m (listing says AAPL — stale metadata) |
| Multiple | 200690451 | NVDA 1m |

⚠️ `layout list` reports the **saved** symbol, which drifts from what the layout actually
opens. Don't trust that column.

Indicators on the `Claude` layout: **Combined Suite — Swing S&R + CALL/PUT Bias + Pivot S/R
+ Open/ORB + Trades** (Pine v6, 547 lines; local source `combined-suite.pine`, TradingView
saved id `USER;5da0fd8cf47b4b308b7e0bc022d45333`, v6.0 — the newer of two saved copies),
**Volume Weighted Average Price**, and **Volume**.

### 2.8 Combined Suite — validated inputs

The 87% win-rate config is **ORB + opposite-OR stop + 0.5×ATR target + EOD flat**. Input
ids as exposed by `indicator get`:

| Input | Setting | Value |
|---|---|---|
| `in_37` | Entry trigger | **`ORB breakout`** |
| `in_40` | Target = ATR × | **0.5** |
| `in_41` | ORB stop at opposite side of OR | **true** |
| `in_34` | Require VWAP confirmation | **true** |
| `in_49` | EOD flat | **true** |
| `in_50` | EOD exit (min after 9:30) | 385 → 15:55 ET |
| `in_48` | Max bars held | **390** (see warning) |
| `in_39` | Stop = ATR × | 3.0 |
| `in_33` | Opening-range length | 5 min |
| `in_35` | Stop new ORB signals after | 150 min (≈12:00 ET) |
| `in_31` | 9:30 gap threshold | 0.30% |
| `in_44` | S/R entry buffer | 0.25% |

⚠️ **`in_48` is timeframe-relative.** The stock default of 78 means "full day on a **5m**
chart"; on a 1m chart it is a 78-*minute* stop that cuts trades hours early. Use **390 for
1m**, 78 for 5m.
⚠️ The layout shipped with `in_37 = "Session breakout (all-day)"`, which is **not** the
validated configuration. Check it after loading any layout.

```bash
node tradingview-mcp/src/cli/index.js indicator set <entity_id> -i '{"in_37":"ORB breakout"}'
```

Use **Bash, not PowerShell** — PowerShell mangles the JSON quoting.

**Open items:** option-premium P&L is still unvalidated (the 87% was measured on
*underlying* price moves; a 0.5×ATR move taking 40 minutes can still lose on a short-dated
contract after theta and spread — combining live ORB levels with `stock_options_chain` is
the route to closing the gap); consider making the **5m pane** primary, the timeframe the
87% was validated on and free of the 1m line-cap clutter; two saved copies of Combined
Suite (v1.0 and v6.0) exist in TradingView — consider deleting the stale v1.0.

*Not affiliated with or endorsed by TradingView Inc.; requires a valid subscription, bypasses
no paywall, connects to no TradingView server. It does use undocumented internal Electron
APIs that can break on any update, and programmatic consumption of TradingView data may
conflict with their Terms of Use. Use at your own risk.*

---

## 3. option-spread — `spread_cycler` credit-spread bot

*`…\trading-suite-repo\option-spread`; deployed to `/opt/option_spread` on the jump server.*
Sells a short vertical credit spread, buys it back at a profit target, logs the exit price,
then re-opens at a lower target credit — up to `MAX_CYCLES` times per session.
**This places real multi-leg option orders when `LIVE=1`. Read the risk notes first.**

**Prerequisites:** Python 3 with `venv` on the jump server; a Robinhood account at option
level 2+ (`robin_stocks`, unofficial API).

```bash
cd /opt/option_spread
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp spread_cycler.env.example spread_cycler.env   # fill in credentials
.venv/bin/python spread_cycler.py                # PAPER by default
```

Paper mode simulates fills at the spread mid and writes the same logs as live, so a full
session can be read out of `trades.csv` before anything is risked.

### Configuration — `spread_cycler.env` (gitignored; copy of `spread_cycler.env.example`)
Credentials by name: `RH_USERNAME`, `RH_PASSWORD`, `RH_MFA_SECRET` (the TOTP *setup key*,
not the 6-digit code), `RH_ACCOUNT_NUMBER` (empty = default account). Never commit the real
file.

| Group | Variables |
|---|---|
| Mode | `LIVE` (0 = paper, 1 = real orders) |
| What to trade | `SYMBOL`, `SIDE` (`call` = bearish call credit spread, `put` = bullish put credit spread), `WIDTH`, `QUANTITY`, `EXPIRY` (blank = today's 0DTE) |
| Cycle rule | `MAX_CYCLES`, `TARGET_CREDIT`, `CREDIT_STEP`, `MIN_CREDIT`, `MIN_OTM_PCT`, `ENTRY_RULE` (`below_exit` \| `step`) |
| Exits | `PROFIT_PCT`, `STOP_MULT`, `MAX_DAILY_LOSS` |
| Timing (ET) | `ENTRY_CUTOFF`, `FLATTEN_TIME`, `POLL_SECONDS` |
| Limit-price walking | `ORDER_TIMEOUT`, `REPRICE_SECONDS`, `PRICE_STEP` |

### A cycle
**Pick** the vertical at least `MIN_OTM_PCT` OTM whose mid-credit is closest to this cycle's
target → **sell** at the mid, re-priced by `PRICE_STEP` every `REPRICE_SECONDS` toward the
natural price until filled or `ORDER_TIMEOUT` → **hold**, polling the mid every
`POLL_SECONDS` → **close** on target (mid ≤ credit × (1 − `PROFIT_PCT`/100)), stop (mid ≥
credit × `STOP_MULT`), or flatten (`FLATTEN_TIME`, at natural price) → **step down**: next
target = min(previous target, achieved credit) − `CREDIT_STEP`, floored at `MIN_CREDIT`.
Every close appends a row to `trades.csv`; `state.json` holds resume state and resets each
calendar day, so a mid-session restart resumes rather than double-counting.

### Risk — read this
With `ENTRY_RULE=below_exit` the credit shrinks by `PROFIT_PCT` every cycle (at the default
50% it halves: $0.32 → $0.16 → $0.08 → $0.04) and hits `MIN_CREDIT` on cycle 3 or 4. The
count you actually get is `cycles ≈ log(MIN_CREDIT / TARGET_CREDIT) / log(1 − PROFIT_PCT/100) + 1`;
ten cycles from $0.32 to a $0.10 floor needs `PROFIT_PCT≈12`, i.e. ten round trips (ten day
trades) for ~$25 gross before commissions and slippage. Use `ENTRY_RULE=step` to control the
cycle count directly. The economics also worsen each cycle — on a $1-wide spread, cycle 1
risks $68 to make $32 (68% break-even win rate); cycle 4 $76/$24 (76%); cycle 7 $84/$16
(84%); cycle 10 $89/$11 (89%). `CREDIT_STEP=0` holds the ratio flat, or raise `MIN_CREDIT`.

- **0DTE assignment.** Anything open at `FLATTEN_TIME` is closed with maximum urgency; an
  ITM short call reaching expiry means 100 short shares per contract. **Never disable flatten.**
- **PDT.** Ten cycles is ten day trades — under $25k on margin that flags you.
- **Theta** burns the whole chain through the day; ten sellable entries usually needs the
  underlying to keep moving. **Strike granularity:** SPY's $1-wide strikes step credit by
  ~$0.09, so a smaller `CREDIT_STEP` won't reach a different strike until it accumulates.
- **Unofficial API.** `robin_stocks` uses Robinhood's private endpoints; heavy automated
  order flow carries real account risk.
- **`STOP_MULT=0` means no stop** — a losing spread is held until profitable, but a 0DTE
  contract expires the same day, so `FLATTEN_TIME` closes it at whatever it's worth,
  possibly full max loss (~$89 on a $1-wide spread sold for $0.11). `STOP_MULT=2.0` caps
  each trade near one credit. *Discrepancy: the old README described `STOP_MULT=0` as the
  default while `spread_cycler.env.example` ships `STOP_MULT=2.0` — the env example is what
  a fresh copy actually does.*

**Safety controls:** `LIVE=0` (default, simulated fills) · `touch /opt/option_spread/STOP`
(no new cycles; open positions still exit normally) · `MAX_DAILY_LOSS` (session realized-loss
cap) · `STOP_MULT` (per-trade stop) · `FLATTEN_TIME` (hard close-everything deadline) ·
`ENTRY_CUTOFF` (no new cycles after this time) · `MAX_ENTRY_FAILS` (give up after N
consecutive failed entries).

---

## 4. robinhood-tools — balances, sell-all, order stubs

*`…\trading-suite-repo\robinhood-tools`.* Standalone Python that logs into Robinhood
directly via `robin_stocks` (**no MCP**) and prints total portfolio value, day change, cash,
buying power, equity positions and crypto.

**Windows:** fill in your Robinhood email and password in `.env`, then double-click
**`balance_check.bat`**. The first run creates a `.venv` here and installs everything into
it (needs internet, once); nothing goes in system-wide.
*(The original doc said to extract the folder to `E:\Tradeing\robinhood`; it now lives inside
this repo.)*

```bash
cd robinhood-tools
cp .env.example .env       # fill in credentials (never committed)
chmod +x balance_check.sh && ./balance_check.sh      # macOS / Linux
# or manually:
pip install -r requirements.txt && python robinhood_balance.py
```

**Configuration:** `.env` (gitignored) holds `RH_USERNAME`, `RH_PASSWORD` and
`RH_MFA_SECRET`. With SMS/email 2FA the first run prompts for the code; with an
authenticator app put the TOTP *secret* (setup key, not the 6-digit code) in
`RH_MFA_SECRET`. After the first successful login a session token is cached under
`~/.tokens`, so you usually aren't re-prompted.

**Logs:** every run writes full output and any traceback to a timestamped file in `logs\`
next to the script, e.g. `logs\balance_2026-07-23_18-45-12.log`. Created automatically,
never auto-deleted, `logs/` is in `.gitignore`.

**Selling everything of one symbol:** `sell_all.bat SOL` (or `sell_all.sh`) sells **all** of
one symbol at market — crypto positions are checked first, then equities. **There is no
confirmation prompt; running it places the order immediately.** It prints a preview, sends a
market order, and if Robinhood rejects it (crypto market sells often 422) retries as a limit
sell ~1% below the current price. Logged to `logs\sell_SOL_<timestamp>.log` with
Robinhood's raw order response. Crypto trades 24/7; stock market orders placed outside
market hours sit pending until the open.

**Extending:** `trading.py` is a stub on the same login exposing `buy_market`, `sell_market`,
`buy_limit`, `sell_limit` etc., each behind a `DRY_RUN` guard — nothing fires until
`DRY_RUN = False`. Option helpers live in `robin_stocks.robinhood.orders`; see the notes at
the bottom of `robinhood_balance.py`. Other entry points: `buy_test.py` / `.bat` / `.sh`,
`diagnose_accounts.py`. **This is Robinhood's unofficial/private API** — widely used, not
sanctioned; prefer read-only balance checks and go easy on request volume.

---

## 5. robinhood-orders — order-history export & P&L analysis

*`E:\Nitin_Hadoop\Claude\robinhood-orders` (sibling).* Data pulled through the **Robinhood
MCP** (not `robin_stocks`). No install; the exports are CSV/JSON next to the scripts.

**Account scope.** The 2026-08-31/09-01 export and P&L cover individual brokerage
`5SE32399` (`••••2399`, rhs `118323997` / `••••3997`) only — excluding "Agentic", "sha", the
managed individual account, both IRAs and the custodial UTMA. **Extended 2026-09-09** to the
**Agentic** account `408835270` (limited margin, option level 2, `agentic_allowed=true`,
crypto acct `••••1942`) — the only account this agent can trade. Do not mix the two.

| File | Contents |
|---|---|
| `equity_orders_all.{csv,json}` | 2,221 orders (1,974 filled), 2017-06-07 → 2026-08-31 |
| `option_orders_all.{csv,json}` | 5,524 orders (3,557 filled), 2020-02-04 → 2026-08-31 |
| `crypto_orders_all.{csv,json}` | 204 orders (197 filled), 2018-08-06 → 2026-08-19 |
| `pnl_trades_all.{csv,json}` | 2,317 closed trades, 2024-01-02 → 2026-08-31 |
| `agentic_positions_20260909.csv` | 48 Agentic positions + total, 2026-09-09 close |
| `agentic_positions_20260910.csv` | 41 Agentic positions + total, 2026-09-10 close |

**How to refresh.** `get_equity_orders` / `get_option_orders` → `account_number = 5SE32399`
(Agentic: `408835270`). `get_crypto_orders` / `get_pnl_trade_history` →
`rhs_account_number = 118323997` (for Agentic, rhs equals the account number). Also
`get_accounts`, `get_equity_positions`, `get_crypto_positions` on the same split. Results
overflow the tool-result cap and land in files — paginate via the `cursor` query param of
`data.next` until absent; `get_equity_orders` with no filter overflows, so filter by `state`
or `symbol`; `get_equity_quotes` drops the official-close block above 20 symbols, so batch
in 16s. Consolidation script: `consolidate_option_orders.ps1` (same pattern for the others).
Agentic aggregation scripts and the final page live in `E:\Nitin_Hadoop\Claude\rh_agentic\`.

**Data caveats.** Robinhood's P&L hub only goes back to **2024-01-02** while the order
history reaches 2017. The P&L API returns no trade id, strike/expiry, realized-% or
asset-class field — `asset_class_guess` is heuristic (`option_guess` = blank side,
`equity`/`equity_guess` = buy/sell rows, blank symbol = event contracts). 13 byte-identical
rows were dropped by full-row dedupe and, with no id, a few may have been genuine duplicate
expiration rows. One USDG crypto sell (2026-07-23) has an empty `realized_gain`.

**Findings** (numbers reproducible from the CSVs above). Main account 2024-01-02 →
2026-08-31: 2,316 closed trades, net **−$15,104**, options −$12,595 on 1,479 trades at a
**63.0%** win rate (avg win +$257, avg loss −$478, payoff ratio **0.54** vs the **0.57**
needed to break even) — **a sizing and exit problem, not a selection problem**, confirmed by
ORCL −$21,590 on 2 trades and MSFT −$26,240 on 23. By year: 2024 −$15,893, 2025 **+$55,745**
(82.0% win), 2026 **−$52,447** — understand the 2026 reversal before adding leverage or
frequency. Agentic at 2026-09-09: 48 positions, **unrealized −$200.12 (−7.75%)** against
realized **+$170.81 at an 88.3% win rate** over 682 trades → **net −$29.31**; the scalping
engine works, the residuals it abandons eat all the profit (AMAT: six small profitable round
trips, then one buy at 7× the prior size, held since). A mechanical 10-name momentum list was
derived 2026-09-09 (MU, TSM, DELL, AMD, NVDA, PLTR from the book; SNDK, MPC, VLO, COP from a
market-wide screen) — the output of a stated filter, not a buy list, effectively two bets (AI
hardware and energy), and it does **not** fix the missing exit/size rules.

**Open items.** (1) Stale MSFT alerts at **$478 / $480** (created 2026-01-02, already
through) — delete or re-point; the only two alerts account-wide. (2) 33 of 48 holdings are on
no watchlist (AMAT included) while GS and SOFI are tracked but never bought — decide whether
the watchlist gates entries. (3) **A per-trade max-size cap and a per-name exposure cap are
still not built**, now supported by three independent datasets. (4) Reconstruct open→close
option round trips from `option_orders_all.json` (match by chain/strike/expiry) for hold
times and per-trade DTE, which the P&L feed lacks. (5) Decide LEAPS-swing vs
intraday-frequency, then build the screener (option OI/volume floors, max bid/ask as % of
premium, IV rank, earnings proximity, underlying ADV) and backtest it against this dataset
before it trades live.

## 6. spy-dip-calls — SPY dip-call backtest & screen

*`E:\Nitin_Hadoop\Claude\spy-dip-calls` (sibling).* Study of buying long SPY calls on dips,
2026-08-31 → 09-01. Report artifact:
<https://claude.ai/code/artifact/d12ba20c-bd11-44e6-ba31-40cbf1d51b4e> · screen artifact:
<https://claude.ai/code/artifact/3678b5fb-f858-41f1-ae27-d8a72a176de0>

**Prerequisites / run:** Python 3 with `yfinance`. `download_data.py` pulls SPY/VIX/SPMO
dailies into `data/` (Yahoo); the `analyze_*.py` scripts write into `results/`;
`verify_adversarial.py` and `verify_checks.py` re-derive the headline numbers.

**Bot rules.** *Entry:* SPY closes ≤ **−5%** from its 52-week closing high (`dd_252`) —
~4.7 signals/yr, one entry per episode, re-arm after recovery above −5%, never buy a first
−20% touch; a 1-day drop ≥3% is a secondary confirming signal only. *Position* (<$5k acct):
1× **180-DTE** ATM-to-5%-OTM call (~$2.4k at SPY 767 / VIX 15), keep ~half as reserve; add
tranche 2 (180 DTE, near-ATM) only if the dip extends to −7%. *Exit:* limit sell at
**+100%**; at +50% arm a **15–20% trailing stop** on the option price; disaster stop **−75%**
of premium; force exit at **~30 DTE**. **No flat 5% trail** — 99.5% of trades stop out ≤5
days (mean hold 1.57d); winners routinely trade 25–67% underwater first, so −25/−50% stops
destroy the edge. Crash tests (2000–02, 2008, 2022) had dip-bought calls expiring ~worthless
at both 90 and 365 DTE; only COVID-2020 rewarded riding, and only at 365. Longer DTE is
monotonically better (45d −0.2% → 365d +9.0%); short-dated OTM is a consistent loser; SPMO
options are too thin, SPY is the vehicle. **Caveat:** most of the raw return is leverage on
market drift (unconditional 365-DTE buying +44.6% vs +51% dip-timed) — trust the *rankings*,
not absolute means. The sim is Black-Scholes on VIX-derived IV: no skew, no dividends, exact
fills, synthetic pre-2005 fills.

**Candidate screen (2026-09-01).** 88 optionable names run through the dip rules, then gated
on **real** option liquidity from live Robinhood chains (2027-03-19 expiry, 2026-08-31
close). The backtest assumed a 1% round-trip cost and **only SPY is anywhere near it** (grade
A, ~5%-OTM 180d cost $2,195, 0.3% spread); then QQQ/AAPL/NVDA (B), CSCO/AXP/ANET/MSFT/GOOGL
(C), V (D). Rejected on tradability despite good history: XLK (29.7% spread, 0 volume),
QUAL, **SPMO** (only 5 expirations, none near 180d), VGT, MTUM, HD, SBUX, UNH. Single-stock
dips lack the index's mean reversion — the rules were validated on SPY only.

**Live position (opened 2026-09-01 11:34 ET).** **XLF $62 Call 2027-03-19 — 1 contract,
filled at a $1.33 limit, $132.04 total** (Robinhood Individual account). Plan: GTC limit sell
at **$2.64** (+100%); arm a 15–20% trail once the option ≥ **$1.98** (+50%); disaster stop
**$0.33** (−75%); time exit **~2027-02-17** (30 DTE); expiry breakeven XLF **$63.33**.
**Caveat logged:** this entry did *not* come from the −5% `dd_252` trigger (XLF was only
−1.3% off its 52-week high), so the dip-recovery stats do not apply.

**LEAPS follow-up (2026-09-02).** Pick at a $484/$400 budget: **XLF $62C 2028-01-21 @ ~$4.22**
(delta 0.522, IV 16.3%, spread 3.6%, breakeven 66.22); theta −0.17%/day vs −0.54%/day on the
Mar-27. Exits: target $8.44, trail at $6.33, stop $1.06, time exit ~2027-12-22.
**CONCENTRATION FLAG:** that is a second XLF position at the *same* $62 strike — alternatives
offered were KO 100C or rolling the Mar-27 62C to fund XLF 60C Jan-28 at $525.

**Not built yet:** the full-auto entry+exit bot (Robinhood; spec is in the report artifact's
"Bot specification" section). Reuse **modeb-bot's auth-backoff lesson (429 lockout)** — see
`trading-suite-repo/jump-bot/`.

---

## Scheduling / automation

| Runner | Where | What it does |
|---|---|---|
| `E:\Nitin_Hadoop\Claude\Start TradingView for Claude.bat` | Windows | Double-click launcher; runs `Start-TradingView-CDP.ps1` via `powershell.exe -NoProfile -ExecutionPolicy Bypass`. **Must** be used every time or CDP :9222 stays closed |
| `E:\Nitin_Hadoop\Claude\Start-TradingView-CDP.ps1` | Windows PowerShell 5.1 | Resolves the MSIX package (`Get-AppxPackage`), reads the app id from `AppxManifest.xml`, activates via COM with `--remote-debugging-port=9222`. Fails under PowerShell 7 |
| `option-spread/option-spread.service` + `option-spread.timer` | Linux jump server | One session per fire, then exits. `sudo systemctl enable --now option-spread.timer`; watch with `sudo journalctl -u option-spread -f`; deploy with `option-spread/deploy.sh` |
| `jump-bot/modeb-bot.service` | Linux jump server | Mode-B bot unit (`modeb_bot.py`, config `modeb_bot.env.example`) |
| `jump-bot/rotate-pool.service` + `rotate-pool.timer` | Linux jump server | Symbol-pool rotation (`rotate_pool.py`, `candidates.txt`, `watchlist.txt`) |
| `robinhood-tools/balance_check`, `sell_all`, `buy_test` (`.bat` / `.sh`) | Windows / Unix | Manual runners, not scheduled |

No Windows Task Scheduler entries, `.vbs` runners or cron jobs are documented in any source
— the only scheduled automation is the systemd timers on the jump server.

---

## Troubleshooting

### TradingView bridge

| Symptom | Cause / fix |
|---|---|
| `tv status` / `tv_health_check` fails | TradingView not running, started normally instead of via the launcher, or no chart tab open |
| `tv launch` → `spawn EPERM`; `Start-Process` → `Access is denied`; `Invoke-CommandInDesktopPackage` → `COMException 0x800704C7` | Store-app ACL on `C:\Program Files\WindowsApps`. Use `Start TradingView for Claude.bat` |
| `explorer.exe shell:AppsFolder\<AUMID>` launches but nothing connects | It silently drops all arguments |
| `Get-AppxPackage` → *Operation is not supported on this platform* | PowerShell 7 can't load the `Appx` module. Use `powershell.exe` (5.1) |
| Claude Settings → Developer shows "No servers added" | Claude Desktop wasn't fully quit (tray icon → Quit); check Task Manager for leftover `claude` processes. New tools only appear in new conversations |
| `indicator add` → `success:false`, `new_study_count:0` | **Broken for built-ins too.** Use the Indicators dialog (Favorites) or the Pine editor ▷ button |
| `pine compile` clicks **Save** instead of *Add to chart* | Click the **▷ arrow** beside the script name in the Pine Editor header (≈ `1634,79` at 1920px) — no text label, so `ui find` can't see it |
| `layout switch` reports success but the chart looks unchanged | It opened the layout in a **new tab**: run `tab list`, then `tab switch <n>`. Happens when the current layout has unsaved changes |
| `tab close` → `success:false` | Doesn't work; close the tab manually in the UI |
| Pine warning *shorttitle is too long (14 chars)* | Pre-existing, **non-blocking** |
| 500-line cap hit on Swing S&R | 25-bar pivots on 1m generate hundreds of levels and old lines silently drop. **Use the 5m pane** |
| npm reports 7 vulnerabilities | Expected. **Do not run `npm audit fix`** |
| `indicator set` JSON rejected | Use **Bash, not PowerShell** — PowerShell mangles the quoting |
| Bridge breaks after a TradingView update | It rides undocumented internal Electron APIs; pin the Desktop version if stability matters |
| `pine_get_source` floods context | 200KB+ on complex scripts — use `study_filter`, summary modes, and `verbose` only when needed |

### Robinhood (both toolsets)

| Symptom | Cause / fix |
|---|---|
| Prompted for a 2FA code every run | Put the TOTP *setup key* in `RH_MFA_SECRET`; the token cached under `~/.tokens` suppresses re-prompts |
| Crypto market sell returns 422 | Known. `sell_all` auto-retries as a limit sell ~1% below the current price |
| A stock order placed outside market hours does nothing | Market orders sit pending until the open; crypto trades 24/7 |
| Rate limit / 429 lockout | Go easy on request volume; reuse modeb-bot's auth-backoff pattern (`jump-bot/`) |
| MCP tool result truncated or spilled to a file | `get_equity_orders` with no filter overflows the cap — filter by `state` or `symbol` and paginate via `data.next`'s `cursor` |
| `get_equity_quotes` missing the official-close block | It drops it above 20 symbols — batch in 16s |
| `spread_cycler` stops before `MAX_CYCLES` | Credit decayed to `MIN_CREDIT` (see the cycle formula), or `CREDIT_STEP` is smaller than strike granularity (~$0.09 on SPY $1-wides) |
| A losing spread is held indefinitely | `STOP_MULT=0` disables the stop; `FLATTEN_TIME` still closes it at whatever it's worth. Set `STOP_MULT=2.0` |
| Need to halt the bot now | `touch /opt/option_spread/STOP` — no new cycles, open positions still exit normally |
| Flagged as a pattern day trader | Ten cycles = ten day trades on an account under $25k |

---

## File map

```
E:\Nitin_Hadoop\Claude\
├─ Start TradingView for Claude.bat / Start-TradingView-CDP.ps1   TV launcher (CDP :9222)
├─ combined-suite.pine · options-bias-entry-exit.pine · swing-high-low-sr.pine ·
│     strategy-spec.md                    working copies
│
├─ trading-suite-repo\                    ← this repo
│   ├─ README.md (this file) · .gitignore · azure-pipelines.yml · KTS_Upgrade.docx ·
│   │     useful_commands.txt
│   ├─ strategy-spec.md                   the strategy, platform-independent
│   ├─ combined-suite.pine                Pine v6 reference (Module 5 = trade engine)
│   ├─ options-bias-entry-exit.pine · swing-high-low-sr.pine · suite-modeB-strategy.pine
│   ├─ purge_atlas_deleted_entities_modified_v4.py / _v5.py   (unrelated Atlas utilities)
│   ├─ suite-backtest\   backtest.py, bt1m.py, bt_orig.py, bt_930.py, bt_935.py, bt_20day.py,
│   │     bt_20orig.py, bt_20stocks.py, bt_13list.py, bt_tv3mo.py, bt_frac.py,
│   │     bt_frac100.py ($100 fractional, Mode B, 4 tickers), bt_trend100.py (TQQQ/200-SMA),
│   │     fetch_data.py, fetch_tv.py, scan_universe.py, search.py, sweep_frac.py,
│   │     gen_trades*.py, refine*.py, tweak*_1m.py, run_1m_scenarios.py, run_5mo.py,
│   │     last30*.py, aggregate_options.py, final_check.py, *_5m_tv.csv raw bars,
│   │     data\ data_1m\ data_ext\ data_rh\ options_results\ options_results_1m\,
│   │     trades_1m_orb.csv, trades_1m_daybreak.csv, trades_recent.csv, universe_ok.txt
│   ├─ option-spread\   spread_cycler.py, spread_cycler.env.example → spread_cycler.env,
│   │     requirements.txt, deploy.sh, option-spread.service, option-spread.timer;
│   │     at runtime: trades.csv, state.json, logs\, STOP
│   ├─ robinhood-tools\   robinhood_balance.py, balance_check.bat/.sh, sell_all.py + .bat/.sh,
│   │     buy_test.py + .bat/.sh, diagnose_accounts.py, trading.py (DRY_RUN stubs),
│   │     requirements.txt, .env (gitignored), logs\
│   └─ jump-bot\   modeb_bot.py, modeb-bot.service, modeb_bot.env.example, rotate_pool.py,
│         rotate-pool.service, rotate-pool.timer, candidates.txt, watchlist.txt, logs\
│
├─ tradingview-mcp\   ← sibling: the CDP bridge. src\server.js (MCP entry point, referenced
│     by both configs), src\cli\index.js (the `tv` CLI), CLAUDE.md (full tool reference +
│     decision tree), SETUP_GUIDE.md, RESEARCH.md, SECURITY.md, CONTRIBUTING.md,
│     LICENSE (MIT), package.json, eslint.config.mjs, tests\, agents\, skills\,
│     screenshots\, node_modules\, scripts\launch_tv_debug.bat / _mac.sh / _linux.sh
│
├─ robinhood-orders\   ← sibling: equity_orders_all.{csv,json}, option_orders_all.{csv,json},
│     crypto_orders_all.{csv,json}, pnl_trades_all.{csv,json},
│     agentic_positions_20260909.csv, agentic_positions_20260910.csv,
│     consolidate_option_orders.ps1
│
├─ spy-dip-calls\   ← sibling: download_data.py (SPY/VIX/SPMO → data\ via yfinance),
│     sim_core.py (BS pricing, VIX term-blended IV, intraday-aware stops, 0.5%/side costs,
│     dip_signals(), simulate_trade()), analyze_entry.py, analyze_exits.py,
│     analyze_downside.py, analyze_sizing.py, screen_universe.py, merge_candidates.py,
│     verify_adversarial.py, verify_checks.py, data\, results\ (entry_analysis, exit_grid
│     (120 configs), downside, crisis_trades, winner_interim_drawdowns, moneyness_grid,
│     dollar_costs_today, ladder + per-trade CSVs)
│
└─ rh_agentic\   ← sibling: Agentic-account aggregation scripts
```

---

## 2026-09-10 — Agentic account health check (post-close)

Live check of the **Agentic** account `408835270` at the close. Nothing is broken
mechanically — orders route, fill and settle, no rejects, no stuck state — but the day
produced the account's first losing session and it failed in exactly the way the 09-09
analysis predicted. **All times below are US Eastern (ET).**

### State at the close

| | |
|---|---|
| Portfolio value | **$2,731.08** = equities $1,991.14 + cash $739.94 |
| Unsettled funds | $601.02 (limited margin — still spendable) |
| Open equity positions | **41**, cost $2,195.70, value $1,990.63 |
| Unrealized | **−$205.08 (−9.34%)** — **0 of 41 green** |
| Options / crypto | none, and none ever — option level 2 unused since inception |
| Open or queued orders | none |
| Snapshot file | `robinhood-orders\agentic_positions_20260910.csv` |

Was 48 positions / −$200.12 (−7.75%) yesterday. Ten names were sold today, cost basis fell
$386, and the unrealized loss still got *bigger*.

### The day: 27 fills, every one `placed_agent=agentic`

Realized **−$35.57** on 17 closing trades (−5.59%) — worst day on record for this account
(prior week: +$5.02, +$5.99, +$2.39). Two unrelated behaviours ran side by side:

| Behaviour | Trades | Realized |
|---|---|---|
| $25 intraday scalps — VLO, MPC ×2, COP ×2, SNDK, MRK | 7 round trips | **+$0.71** |
| Position liquidations — SOXL, AFRM, UBER, PANW, SMH, QCOM, RBLX, CRWD, NET, META | 10 exits | **−$36.28** |

- **SOXL alone −$18.30** (3× leveraged, held to −19.6%) — 51% of the day's loss.
- Median scalp gain **$0.10**. It takes **363 winning scalps to pay for one SOXL exit.**
- The two sells at the open (SMH, QCOM) were **created 7:59 AM pre-market as market orders**
  and queued unpriced until **9:30:00**. No limit, no open-print protection.

Sequence (ET): 7:59 SMH + QCOM queued → 9:30:00/01 both fill → 9:34 META → 9:43 CRWD →
9:47 NET → 10:25 SOXL + AFRM → 10:30 RBLX → 10:31 VLO buy / 10:44 sell → 10:43 MPC buy /
11:02 sell → 10:46 COP buy / 11:32 sell → 11:05 MRK buy / 3:59 PM sell → 11:28 MPC buy /
11:53 sell → 11:38 PANW → 12:02 VLO buy *(held)* → 12:08 COP buy / 1:10 PM sell → 12:15 MPC
buy *(held)* → 12:42 SNDK buy / 12:57 sell → 12:47 UBER → 3:25 PM SNDK buy *(held)*.

### Cumulative

Realized since the account began trading in **2026-07**: **+$135.24** over **699** closing
trades (+0.57% per trade). Against unrealized −$205.08 that is **net −$69.84**.
Yesterday: +$170.81 / 682 trades, −$200.12 unrealized, net −$29.31. **One session moved net
P&L by −$40.53** — a third of two months of accumulated scalping gains, gone in a day.

### The 50 → 10 universe cut is half-executed

Today reads as a partial run of the 09-09 momentum cut. All ten screened names are now
accounted for — MU, TSM, DELL, AMD, NVDA, PLTR held from before; **VLO, MPC, SNDK bought
today**; COP traded twice and closed flat. Everything sold today was **off-list**.

- On-list, 9 held: unrealized **−$19.91**
- Off-list, 32 held: unrealized **−$185.22**

**Finishing the cut at today's prices realizes roughly −$185 more.** That number should be a
decision, not a surprise — 10 exits today already cost −$36.28 with no rule saying when.
One off-list buy also still happened today (MRK, 11:05 AM), so the list is not gating entries.

### What is missing — verified live, not inferred

1. **No stop-loss and no time-stop.** Today's ten exits were a batch capitulation after drift
   of −1.4% to −19.6%, not a rule firing. This is the third independent dataset showing it.
2. **No per-trade size cap and no per-name cap** — open item (3) from 09-09, still not built.
   AMAT is still the worst holding at **−$32.36 (−18.8%)** and is still held, unchanged.
3. **No daily loss limit / kill switch.** Nothing would have stopped today at −$35.57.
4. **Position sprawl.** 41 names averaging **$48.55** each in a $2.7k account — index-fund
   breadth with a scalper's turnover, and every one of them red.
5. **Dust residual: AMD 0.0037 sh = $1.86**, left behind by a partial sell. Nothing prunes it.
6. **Stale alerts still live** — MSFT `price_above` **$478** and **$480**, created 2026-01-02,
   both still `enabled`. MSFT closed **$492.49**, so both are permanently through. Still the
   only two alerts account-wide. Open item (1) from 09-09, unchanged.
7. **Leveraged ETF exposure remains** — TQQQ (3×) is still held at −$2.90. SOXL was the same
   instrument class and produced 51% of today's loss on its own.
8. **Sizing asymmetry is now measured, not argued.** Scalp win ≈ $0.10; exit loss ≈ $3.63
   average, $18.30 worst. Nothing in the loop connects entry size to exit risk.

Net read: **the execution layer is healthy, the risk layer does not exist.** Order routing,
fills, settlement and the scalp engine all work. Every dollar they earn is handed back by
positions nothing is responsible for closing.

### Addendum, 6:30 PM ET — the bot found, the exit strategy verified live

**Where the trading actually comes from.** Not a cloud routine and not the old VPS
`modeb-bot` (74.208.194.214 is unreachable — deleted). It is
`C:\AI_trading_claude_Cowork\auto-trade-watchlist\auto_trade.py`, fired **every minute by the
Windows Task Scheduler task `AutoTradeWatchlist`** (hidden via `run_hidden.vbs`; last run 6:18
PM, exit 0). All signal logic is local Python on Yahoo 1-min bars; only order placement crosses
to `claude -p` with the Robinhood MCP — which is why every fill shows `placed_agent=agentic`.
Proof it is the live bot: **all 27 order IDs in today's `log.csv` match the 27 fills in the
account one-for-one** (e.g. QCOM `6aa29b9d…` 7:59 AM, SOXL `6aa2bdd0…` 10:25 AM, MRK EOD
`6aa30c02…` 3:58 PM). Health check 8:55 AM `HEALTHY`, morning report 9:45 AM, EOD sweep 3:58 PM
— all ran. Nothing in `manual_orders.json` today (no unrouted orders).

**The exit strategy already exists — deployed 8:01 AM today** from session "Robinhood Agentic
Trading (fork)", and today's sells were it firing, not capitulation:

| Rule (in `auto_trade.py`) | Fired today |
|---|---|
| Wind-down **lev** (SOXL/TQQQ): sell +3% bounce off trough, or 7 d | SOXL 10:25 AM (trough 113.68 → 117.31) |
| Wind-down **deep** (<−10%): +4% bounce off trough, recovery to −5%, or 21 d | AFRM 10:25, PANW 11:38, UBER 12:47 |
| Wind-down **mid** (−5…−10%): recovery to −2%, or 21 d | none yet (12 names) |
| Wind-down **shallow** (0…−5%): recovery to −0.5%, or 21 d | QCOM, SMH, META, CRWD, NET, RBLX |
| New entries: **−3% stop · 4-day time-stop · $25 cap** + profit ladder | VLO/MPC/COP/SNDK/MRK — 6 take-profits, 0 stops |
| 3:58 PM sweep: sell anything in profit | MRK |

State: 53 tracked (12 marked `sold`), 5 post-overhaul (COP, MPC, MRK, SNDK, VLO), 22 shallow,
12 mid, 12 deep, 2 lev. Reconciles exactly with the 41 live positions.

**Two defects found:**

1. **Pre-market sells fill blind at the open.** At **7:59:01 AM** the wind-down evaluated QCOM and
   SMH on the *previous close* (Yahoo pre-market = stale 176.40 / 574.29), judged them
   "recovered", and placed market sells. Robinhood queued them to 9:30:00 — QCOM filled 172.11
   (−2.4%), SMH 561.44 (−2.2%). Bot estimated +$0.09 / −$0.24; actual **−$1.08 / −$1.69**. The
   code comment (line 166) assumes Robinhood *rejects* pre-market market orders — it queues them.
   `MARKET_OPEN` (9:30) exists at line 263 but only gates alerts. **Fix: gate every order
   placement to 9:30:00–15:59 ET.** Small dollars today; the same path would hand a stop-loss or
   deep-tier sell to the opening print unpriced.
2. **Robinhood "Watch" list ≠ bot universe.** Bot `WATCHLIST` = MU TSM DELL AMD NVDA SNDK MPC VLO
   COP **MRK** (PLTR removed 8:01 AM, MRK added from the replacement screen). The Robinhood list
   was synced today to the README's 09-09 version, which still had **PLTR** instead of MRK —
   **corrected 6:35 PM ET**: Robinhood "Watch" now = the bot's `WATCHLIST.md` exactly (MRK in, PLTR out).

Earlier health-check items now re-read: "no stop-loss / time-stop / size cap" was true until
8:01 AM today and is no longer — items 1, 2 and 7 (leveraged-ETF exposure) are handled by the
overhaul; items 3 and 6 fixed 6:30 PM (see Fixes below); still open: AMD dust (5).
Watchlist on Robinhood (custom list "Watch") was cut from 17 names to the 10 at 6:15 PM.

### Fixes applied, 6:27–6:35 PM ET (all live, all verified)

| Fix | Where | Verified |
|---|---|---|
| **Order-hours gate** — live orders only placed **09:31:00–15:59:59 ET**; outside that `place_order()` returns `deferred` (no Claude call, no `manual_orders.json` entry, no alert, no state change); the trigger simply re-fires at 9:31 on a live quote | `auto_trade.py` — `ORDER_HOURS_GATE/START/END`, `_orders_allowed()`, `_now_et()`, deferred branches in `_exit_position`, `_check_entry`, `_do_add` | 9 boundary cases + pre-market sell → deferred with zero Claude calls |
| **Daily loss limit** — `DAILY_LOSS_LIMIT=10`: once today's realized (bot estimate, `state["day_realized"]`, summed in `_record_sell` and the EOD sweep, reset with the day) ≤ −$10, **no new buys or $10 adds** until the next session; exits never blocked | same file | accumulation test + buy blocked at −$18.40, allowed at −$9.99 |
| Stale doc pointers → `trading-suite-repo\README.md` (§5 + this section), archive path for the 09-09 tables | `auto_trade.py` comments, `WATCHLIST.md`, `STRATEGY_SPEC.md` (§1, §3, §10 rows added) | grep |
| Stale MSFT alerts $478 / $480 | Robinhood — **deleted** (account now has zero alerts) | `delete_alert` × 2 |
| Wrong comment "Robinhood rejects pre-market market orders" → "queues them to the open" | `auto_trade.py` schedule block | — |

Method: backup `auto_trade.py.bak_20260910_1827`, atomic replace (scheduler fires every
minute), `py_compile`, 19-check harness importing the live module with state/log redirected
to temp (all pass), then watched the next scheduled cycle — 6:28:28 PM, exit 0, `runner.log`
still empty, log rows normal. Env knobs: `ORDER_HOURS_GATE=0` disables the gate,
`ORDER_HOURS_START/END` (HH:MM), `DAILY_LOSS_LIMIT=0` disables the limit.

Tomorrow's first observable: between 4:00 and 9:30 AM any wind-down trigger logs
`DEFERRED SELL - pre-market …` instead of placing; the first real order can't appear before
9:31:00. Still open after tonight: AMD dust ($1.86 — will clear via shallow time-stop by
10-01), and the `_readme_backup_20260910\robinhood-orders\README.md` tables are the only copy
of the 09-09 derivation detail.


*Not investment advice. Paper-trade a full session before going live.*

---

## 2026-09-16: LEAPS long-call options suite (new, dry-run)

New project under `C:\AI_trading_claude_Cowork\auto-trade-watchlist\leaps\`, a sibling of
the existing `auto_trade.py` watchlist bot in that same folder.

**What was built.** `fetch_daily.py` (Yahoo daily-bar fetch with a live-partial-bar guard),
`bs_pricer.py` (Black-Scholes option pricer driven by a realized-volatility proxy, with a
delta-targeted strike solver), `leaps_signals.py` (entry/exit signal logic: breakout,
momentum and pullback-resume entry modes; premium- and DTE-keyed exit thresholds),
`leaps_backtest.py` (grid backtester across entry mode/delta/take-profit/stop/exit-DTE,
writes `leaps_config.json` and `backtest_results\`), `leaps_config.json` (the winning
config, regenerated on every backtest run), `leaps_trade.py` (the live/dry-run daily trade
driver, reads the config and calls a bridge to place orders through the Robinhood MCP),
`run_leaps.bat` (task entry point, carries the `LEAPS_LIVE` environment flag),
`register_leaps_task.ps1` (Windows Task Scheduler registration script for task
`LeapsOptionsDaily`, not yet run), `run_leaps_hidden.vbs` (hidden-window wrapper), and
`backtest_results\` (SUMMARY.md, grid_summary.csv, best_trades.csv and related output).

**Strategy.** Long calls only, on the same 10-name watchlist as the intraday bot (MU TSM
DELL AMD NVDA SNDK MPC VLO COP MRK). Monthly expiry closest to 365 days out (8 to 14 month
window). Strike at 0.70 delta. Entry on a breakout: a fresh 63-bar closing high above the
200-bar SMA. Take profit at +50 percent of premium. No stop-loss. Unconditional sell at 90
days to expiry if the position has not already closed. Max 3 open positions, one new entry
per day. Entry selection is affordability-gated: same-day candidates are ranked by momentum
and tried in order, the bridge buys the first whose contract fits the budget, at most one
order per day (an ordered fallback chain, not a single best-guess pick).

**Backtest result.** REAL scenario ($1,328.31 budget, the Agentic account's actual buying
power): 88.4 percent win rate on 43 closed trades, total simulated pnl $13,160. Out-of-sample
split (train through 2022-12-31, test after): 86.1 percent on the train side, 100 percent on
7 test trades. Clears the 80 percent gate. FUNDED scenario ($15,000 budget) only reached 75.4
percent and FAILED the 80 percent gate, so adding funds to trade bigger or more names is not
supported by this evidence, the REAL-scenario edge appears to partly reflect the small budget
selecting only the cheapest contracts.

**Caveats.** Option prices are Black-Scholes approximations from a realized-volatility proxy,
not real option quotes, no historical option data exists for this universe. The 2016-2026
sample is mostly a bull market. Overlapping trades (up to 3 at once) are not independent
samples. Results overstate live performance. At delta 0.70 and current prices, nothing in the
universe is affordable on the $1,328.31 budget, the cheapest modeled contract is about $2,662
(COP). The last backtest entry was 2024-01-25, so live trade frequency is expected to be near
zero until funding or prices change.

**Status.** Verified PASS after 2 verification rounds. Everything is currently in DRY-RUN
(`LEAPS_LIVE=0`); the scheduled task `LeapsOptionsDaily` is NOT registered. To go live: run
`leaps\register_leaps_task.ps1` in PowerShell and set `LEAPS_LIVE=1` in the task's
environment (`run_leaps.bat`).

**Pipeline artifacts.**
`C:\AI_trading_claude_Cowork\auto-trade-watchlist\.pipeline\20260916-1928-leaps\`

## 2026-09-17: LEAPS suite went LIVE + state-corruption hardening

- Went live: `LeapsOptionsDaily` task registered 09-16 evening (every 30 min, weekdays
  09:30-16:00, hidden via `run_leaps_hidden.vbs`); `set "LEAPS_LIVE=1"` added to
  `leaps\run_leaps.bat` on 09-17 (a `set` typed in a PowerShell window does NOT reach the
  task; the flag must live in the .bat). First live cycle: 09-17 ~10:00 ET.
- The "leaps_trade.py raised an exception ... could not convert string to float:
  'not-a-number'" crash email received 09-16 evening was NOT a live failure: it was the
  round-1 verifier's deliberate corrupted-state probe (recorded in the pipeline's
  verification.md) running the pre-fix file; the crash-alert email path fired as designed.
- Hardened anyway: `leaps_trade.py` now coerces `option_buying_power` from state with
  try/float; on None or junk it reseeds from `leaps_config.json` and logs a
  `state_repair` warning instead of crashing. Reproduced the exact probe against the fix:
  exit 0, value reset to 1328.31, state saved as a float.
- Same test confirmed live behavior for today: MPC and VLO breakout signals firing,
  both correctly headed for affordability rejection (about $8,500 modeled contracts vs
  the $1,328.31 budget), so expect a logged no-buy cycle, not an order.

## 2026-09-17 (later): expiry window widened to 2-12 months, config unchanged in effect

- What changed: the expiry window at entry is now 2 to 12 months (was a fixed 8 to 14
  month window). Target expiry length joined the backtest grid as its own axis, run
  across 63, 91, 126, 182, 273 and 365 days, alongside the existing entry mode, delta,
  take profit, stop and exit-DTE axes. `leaps_trade.py` reads `target_expiry_days`,
  `expiry_months_min` and `expiry_months_max` straight from `leaps_config.json`, with
  defensive fallbacks (365 / 2 / 12) if a key is missing or junk, and now clamps an
  out-of-window target into the resolved month window before it reaches the option
  bridge, converting months to days at 365/12 days per month. A normal (365, 2, 12)
  config passes through unclamped and logs at info; anything out of window logs a warn
  row naming the original and clamped value. Nothing is rejected and nothing can crash.
- Outcome of the 1008-simulation grid (504 configs x 2 funding scenarios): win rate
  rises monotonically with tenor, from about 63 percent at 63 days up to about 90
  percent at 365 days, so the winner is still the 365-day breakout config. The naive
  top pick by win rate alone (exit DTE 21, 90.5 percent on 42 closed trades) beat the
  incumbent exit DTE 90 (88.4 percent on 43 closed trades) by exactly one trade, which
  is statistical noise and behaviorally worse: it holds losing positions through the
  steepest part of the theta curve, right where the Black-Scholes proxy pricing is
  least reliable. The backtester's winner selection now carries a deterministic
  two-stage band rule (documented in `leaps_config.json`'s companion
  `backtest_results\SUMMARY.md`, Winning config section): rank by win rate and total
  pnl, then within the band of configs sharing entry mode, delta and tenor whose loss
  count is within one loss of the top, prefer the largest exit DTE. This adopted delta
  0.70, take profit 50 percent, no stop, exit DTE 90, 365-day tenor, at 88.4 percent on
  43 closed trades, the same config as before the grid was widened. Re-running the
  backtest a second time reproduces the identical config byte for byte, so it is a
  verified fixed point, not a one-time edit.
- The blunt practical outcome: affordability did not improve. At delta 0.70, even the
  63-day contracts on these ten names exceed the $1,328.31 budget; none of the ten
  fit at any tenor in that delta column (cheapest modeled contract today is COP at
  about $2,793 at 365 days). The best config restricted to cells where at least one
  name is affordable today scored only 70.9 percent (pullback_resume, delta 0.55,
  182 days, exit DTE 21, COP only), below the 80 percent adoption gate, so it was not
  adopted. The bot remains live and will keep logging no-buy cycles. Open decision for
  the owner: accept a cheaper universe, raise the budget, or accept the bot idling.
- Caveats unchanged from the prior LEAPS entries: Black-Scholes proxy pricing with no
  real option quotes, a mostly-bull 2016-2026 sample, overlapping correlated trades,
  and results that overstate live performance.
- Pipeline artifacts:
  `C:\AI_trading_claude_Cowork\auto-trade-watchlist\.pipeline\20260917-1034-expiry\`

## 2026-09-18: LEAPS bot switched to ensure-open affordable mode; FIRST OPTION ORDER PLACED

Owner directive: keep at least one option position open on the 10 tracked names, never
buying a contract with under 30 days to expiry. Changes in leaps_trade.py (constants
ENSURE_MIN_OPEN=1, MIN_ENTRY_DTE=30, MIN_ENTRY_DELTA=0.20):
- Contract selection: the bridge now buys the HIGHEST-delta call whose ask x100 fits the
  $1,328.31 budget across all qualifying monthly expirations (window 2-12 months AND
  >= 30 days), delta floor 0.20, instead of demanding delta 0.70 and rejecting all.
- Ensure-open fallback: when no position is open, non-firing positive-momentum names are
  appended to the candidate chain (downtrending names never force-bought).
- Proportional time exit: positions store exit_dte_eff = min(config exit_dte,
  max(7, entry_DTE/3)) so short contracts do not get insta-sold by the 90-DTE rule.
First order placed 2026-09-18 15:12 ET: BUY 1 MPC 2026-11-20 $510 CALL, limit $11.50
(order 6aad8d11-59e7-4708-8dcf-3da1b7af45e2, delta 0.238, 63 DTE, exit_dte_eff 21).
Caveat recorded: this mode is OUTSIDE the 88.4 percent backtested config (that applied
to 0.70-delta 365-day entries); low-delta short-dated calls are more speculative. The
88.4 percent figure does not apply to trades made in this mode.

## 2026-09-24: option entries STOPPED; open option closes only in profit

Owner directives after reviewing the book (MPC 2026-11-20 $510C filled 09-18 at $11.50,
marked ~$5.60 on 09-23, about -51 percent):
- `ENTRIES_ENABLED=0` in leaps_trade.py: no new option buys at all. The daily cycle now
  does exit management only (skips the 10-name scan entirely). Flip to 1 to re-enable.
- `OPTION_NO_LOSS_CLOSE=1`: an option is only ever sold in profit. The unconditional
  21-DTE time exit is converted at runtime into "sell only at or above breakeven plus 1
  percent" (for MPC: >= $11.62 once inside 21 DTE, >= $17.25 take-profit before that);
  downside triggers are stripped. Accepted consequence, stated to and confirmed by the
  owner: if the contract never trades above cost it rides to the 2026-11-20 expiry and
  can expire worthless (full $1,150 premium loss).
Both behaviors verified by dry runs (seeded 16-DTE losing position converts to
conditional breakeven sell; entries log "entries disabled"). Stock bot unaffected.

## 2026-10-07: stock bot per-entry cap raised $25 -> $100

Owner request. Implemented via `set "MAX_TRADE_DOLLARS=100"` in run_auto_trade.bat (the
env var auto_trade.py:109 reads; default stays 25 in code). Effective from the next
minute cycle. Sizing is still `min(CASH/10, cap)`, so the full $100 clip only applies
when free cash is >= $1,000; below that, CASH/10 binds (e.g. $400 cash -> $40 clips).
Risk scales with it: the -3 percent stop on a $100 clip is about $3 vs $0.75 before.

## 2026-10-08: stock stop-loss REMOVED, back to never-sell-at-a-loss (owner directive)

Trigger: SNDK bought 10-07 at $1,731.96 ($100 clip) gapped overnight through the -3
percent stop and sold 09:31 at $1,658.60 (-$4.24, -4.24 percent). Owner chose to revert
new-trade stock exits to pure never-sell-at-a-loss:
- `STOP_LOSS_PCT` default changed 0.03 -> 0 in auto_trade.py (0 = disabled; the exit
  ladder now guards `STOP_LOSS_PCT > 0`). Re-enable any time via the env var in
  run_auto_trade.bat.
- The 4-day time-stop is now PROFIT-GATED: a stale position exits on age only while
  green; a red one is held until it recovers, indefinitely.
- Unchanged: +0.5-1 percent take-profit band, +2 percent trailing arm with its
  never-below-entry guard, 15:58 profit-only sweep, legacy wind-down (still allowed to
  exit residuals near breakeven), options no-loss rule of 09-24.
Accepted consequence, stated to the owner: with $100 clips and no stop, a gapping loser
freezes $100 of capital for as long as recovery takes; this is the regime that built the
old 48-position residual bag, now at 4x the clip size. The 10-08 SNDK sale itself stands
(already executed). Verified: py_compile clean, per-minute task unaffected.

### 2026-10-08 (later): MPC call closed by owner at +$150; state reconciled

Owner manually sold the MPC 2026-11-20 $510C at 10:05 ET, limit $13.00 ($1,300 credit vs
$1,150 paid: +$150, +13 percent, the option book's first realized winner; it was marked
$16.85 an hour later). leaps_state.json reconciled: MPC position removed, close recorded
in history, option_buying_power 178.31 -> 1478.31. Option book now EMPTY; entries remain
disabled (ENTRIES_ENABLED=0), so the bot is exit-management-only with nothing to manage.
A candidate next trade was given to the owner to place manually: COP 2026-12-18 $125C
(~$12.55 mid, delta 0.76), GTC sell +50 percent at $18.85, re-place at breakeven from
Nov 27 (21 DTE), out by Dec 11. Not placed as of this note.

### 2026-10-08 (evening): option entries RE-ENABLED with better fills; bot bought MPC Dec $580C; bot will NEVER sell options

- Owner re-enabled automated option buys (`ENTRIES_ENABLED=1`). Entry prompt improved:
  limit = the quote's high_fill_rate_buy_price (never above ask, never above budget),
  plus at most ONE cancel-and-replace at the ask if unfilled by end of the bridge task.
- Forced cycle 15:04 ET: momentum ranking put MPC first (mom63 0.56); every 2027
  expiration failed the budget/delta floor; bot bought 1 MPC 2026-12-18 $580C at $11.60
  (high-fill price, ask was $12.00), filled instantly at 15:08 ET, order 6ac7ea25.
  $1,160 spent, option bp counter now $318.31, exit_dte_eff 23.
- Owner directive: `MANAGE_OPTION_EXITS=0` -- the bot never places option SELL orders;
  it logs exit levels daily as information only. The owner closes all options manually.
  Suggested manual plan for this contract: GTC sell $17.40 (+50 percent); from Nov 25
  (23 DTE, the logged level) take breakeven-or-better; be out by Dec 11; MPC must beat
  $591.60 by Dec 18 for expiry breakeven; delta 0.21 so this is the speculative profile.

## 2026-10-13 - Stock bot: averaging-down adds (buys no longer blocked by red positions)

Owner noticed zero trades on Oct 12-13 and asked why; diagnosis: all 10 watchlist names
held open positions (9 of 10 red after the Oct 10 dip), and process_symbol() was a strict
either/or - a held name only ran exit management, never buys. Under never-sell-at-a-loss
that froze the bot completely. Owner directive: "even though under water or in -ve you can
still make buy orders".

Change in auto_trade.py:
- New constants (replace the dead STEP1_PCT/STEP2_PCT/STEP_ADD_DOLLARS $10 step-add
  constants): DIP_ADD_PCT=0.03, MAX_DIP_ADDS=2 (both env-overridable; MAX_DIP_ADDS=0
  disables adds).
- _manage_position() now calls _dip_add() before the exit ladder when the position is
  at or below -3% x (adds_done+1) vs the blended average and adds_done < 2.
- _dip_add() (rewrite of the never-called _do_add): buys a normal clip
  (min(CASH/10, MAX_TRADE_DOLLARS)) via the bridge, then blends the position -
  entry_price becomes the weighted average, quantity accumulates, adds_done increments,
  peak_price resets to the new average unless trailing is active. Never-sell-at-a-loss
  then waits on the LOWER blended breakeven, so recovery sells come sooner.
- Guards shared with normal entries: daily loss limit, per-symbol cooldown, order-hours
  gate, MIN_BUYING_POWER floor; errors alert + record to manual_orders.json.

Expected immediate effect at deploy time (cash $1,274): MU -13%, SNDK -9.3%, AMD -6.5%
get both adds; NVDA -5.9%, TSM -4.9% get one; roughly $700-800 of cash deploys into the
deepest dips over the following minutes, clip size shrinking with CASH/10 as cash is
spent. py_compile clean; task picks the file up next minute-cycle (fresh process per run).

## 2026-10-13 (later) - LEAPS bot: ALL option orders stopped (owner directive)

Owner: "Do not do any sell or buy on option trades any more". ENTRIES_ENABLED 1 -> 0 in
leaps_trade.py (sells were already off via MANAGE_OPTION_EXITS=0 since 10-08). The bot
is now fully read-only on options: the LeapsOptionsDaily task keeps running and logs
entry scans + exit_check levels (informational) for the open MPC 12-18 $580C, but no
order instruction of any kind reaches the bridge. Owner manages the MPC position and
any future option trades manually in the app (a manual GTC sell for the MPC call is
already resting at the broker). Stock-bot dip adds from the earlier 2026-10-13 section
are unaffected (stocks, not options). py_compile clean.

## 2026-10-14 - Owner option round-trip + new manual COP position

Morning: owner's manual sell closed the bot-bought MPC 12-18 $580C at $12.22
($1,222, filled 11:59 ET) for +$62 (+5.3%) on $1,160 paid. Account then $3,062
total, $1,776.50 cash, no options.

Afternoon: new manual buy per advisory scan (bot is read-only on options since
10-13; owner places everything). Scan: DELL disqualified (-10% day), MRK calls
pumped +37-42% intraday (chasing), VLO/MU/TSM unaffordable or wrong profile
(MU ATM $8.8k, IV 50%; TSM $480C only 0.32 delta 2 days before Oct-16 earnings).
Recommended COP Jan-15-2027 $135C (delta 0.68) or ATM $140C (delta 0.60); owner
chose the $135C: BUY 1 filled 13:26 ET at $13.10 ($1,310, limit $13.65, order
6acfbb2f, placed_agent=user). Breakeven at expiry $148.10 (COP $141.74 at entry,
+4.5%), 93 DTE.

Owner sell plan (manual): GTC $19.65 (+50%); if unfilled by Dec 16 (30 DTE)
switch to breakeven $13.25; hard out by Jan 4; COP earnings ~Nov 5 - consider
taking +20%+ before the print. Cash after buy ~$466 -> stock-bot clips ~$46
until stock sells replenish.

## 2026-10-15 - First diagonal: short COP Nov-6 $148C against the Jan $135C

Owner wanted a high-IV short call against the long COP Jan-15-2027 $135C (PMCC).
Advisory scan: COP earnings Nov 5 am (verified) pumps the Nov-6 expiry to ~36% IV
vs 29.6% on the long. Recommended Nov-6 $150C @ $2.35 (only strike with real OI;
$148 flagged for its $1.55-wide empty book and fake 40% IV, and strike below the
$148.10 long breakeven). First attempt blocked: account was option_level_2 (short
call demanded 100 shares). Owner upgraded to Level 3 via
applink.robinhood.com/upgrade_options (limited-margin account, eligible) - approved
same hour. Owner then SOLD 1 COP Nov-6 $148C anyway, limit $2.70, FILLED AT $2.80
(price improvement; $279.96 credit after fee, order 6ad1013e, 16:37 UTC).

Resulting diagonal: long Jan $135C ($13.10) + short Nov-6 $148C (+$2.80). Effective
basis $1,030. Management: short expires the day after earnings; if COP<=148 keep all
$280 (21% of basis) and re-arm GTC $19.65 on the long AFTER the short is gone (never
both at once); if COP>148 pair is still profitable but capped (~+$520-570 max at
Nov-6) - close both legs together rather than legging out; buy back the short on
Nov-5 IV crush if it is quoting pennies. Also stopped owner buying an Oct-16 $160C
at a ghost $2.13 ask (bid $0.00, worth a penny, delta 0.005).

## 2026-10-15 — Bot folder moved to `C:\AI_trading_claude_Cowork`

`auto_trade.py`, the LEAPS suite and both scheduled tasks (AutoTradeWatchlist, LeapsOptionsDaily) now run from
`C:\AI_trading_claude_Cowork\auto-trade-watchlist` (SSD) instead of E:, which became a USB exFAT volume on
2026-10-15. First run from C: 23:51:51 ET, result 0. Full procedure and verification: `workstation\README.md`,
section "2026-10-15 — Drive swap DONE". Old copy parked at `E:\AI_trading_claude_Cowork_moved-to-C_20261015`.

## 2026-10-16 — Operational status check (user asked "is this still operational?")

- **jump-bot (modeb-bot)**: NOT operational — host VPS 74.208.194.214 deleted 2026-09-08
  (Azure backup `nitinjakka/vpsserver-backup`, see `VPSServer-backup/RESTORE.md`). SSH
  confirmed timing out today. Code intact in `jump-bot/` here and on GitHub master.
  Redeploy = new host + venv + `.env` + one Robinhood device approval.
- **Agentic bot (auto-trade-watchlist, Windows)**: OPERATIONAL — task `AutoTradeWatchlist`
  Ready, `state.json`/`log.csv` written 08:05 ET today; LeapsOptionsDaily also Ready.

## 2026-10-16 (later) — modeb-bot redeployed locally, ON-DEMAND mode

- New home: `C:\AI_trading_claude_Cowork\modeb-bot` (venv, watchlist, env, logs,
  trades.csv all local). **No daemon, no scheduled tasks**: `run_bot.bat` trades one
  session and exits after 16:05 ET; no run = no trading.
- v3 changes: startup position reconcile vs account; satellite rotation auto-runs at
  session start when >7 days stale; verified logins; ONE auth retry then exit (no
  force_fresh loops per the 2026-08-18 429 lesson); `SWEEP_SCOPE=tracked` default so
  the 15:58 sweep can no longer sell manually-bought holdings (set `all` to restore
  spec behavior). Code pushed to GitHub master (jump-bot/).
- BLOCKED on first login: Robinhood rejects the password copied from
  `E:\Tradeing\robinhood\.env` ("Login failed. Check credentials" / 'token_type') —
  password evidently rotated since 2026-08-12. User must update RH_PASSWORD in
  `C:\AI_trading_claude_Cowork\modeb-bot\modeb_bot.env`, run `run_bot.bat`, approve
  the phone prompt. LIVE=0 (paper) until the user flips LIVE=1.
- 2026-10-16 08:45 ET: Agentic bot confirmed on account 408835270 via claude.ai MCP connector (no RH creds on disk anywhere); modeb-bot separation = account 5SE32399 + own folder/state. Login still blocked pending user's current RH password in modeb_bot.env.
- 2026-10-16 ~09:05 ET: user ordered no orders + candidate purge. Bot session killed, STOP file set, candidates.txt emptied (rotation now selects nothing), watchlist stripped back to core-70. LIVE=0 throughout; no orders were placed at any point today (paper mode).
