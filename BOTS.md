# Bot Performance Tracker

> Live tracking of all autonomous bots. Updated each session.
> **Last Updated:** June 2026

---

## Bot 1 — Flash Arb Bot

**GitHub:** `myshariff123/flash-arb-bot`
**EC2 Container:** `flash-arb-bot`
**Start Date:** May 2026
**Strategy:** Flash loan DEX arbitrage (Uniswap V3 ↔ QuickSwap ↔ SushiSwap) + Aave V3 liquidations

### Current Status: RUNNING — Zero Revenue

| Metric | Value |
|--------|-------|
| Uptime | Running continuously |
| Total Profit | $0 |
| Scans Completed | > 10,000 |
| Opportunities Found | Multiple (rejected by profitability check) |
| Chains Active | Polygon + Arbitrum |
| Wallet Balance | Check: `0xc76Ac0889e8Cc7449e862C8671BcE6E2579088d6` |

### Why No Profit Yet
- Polygon: Extremely competitive. MEV bots with 400ms latency detect same opportunities first
- Arbitrum: Same issue — L1 finality + sequencer priority means faster bots win
- 60s polling misses most arb windows (arb opportunities close in seconds, not minutes)
- Gas costs on both chains eat thin spreads

### Config Changes History
| Date | Change | Reason |
|------|--------|--------|
| Jun 2026 | Polling 2s → 60s | Alchemy free tier 50% consumed mid-month |
| Jun 2026 | BCT checksum fixed | EIP-55 error causing scan errors on every cycle |

### Open Issues
- [ ] TheGraph bootstrap fails on startup (cosmetic — uses live event scanning instead)
- [ ] Watchtower container restarting (unrelated but noisy)
- [ ] Zero profit on both chains — competition too high

### Next Step Options
1. **Base Chain** — newer L2, less MEV competition, lower gas costs (recommended)
2. **Boost polling to 5s** — needs Alchemy paid tier ($49/month)
3. **WebSocket subscriptions** — replace polling entirely; react to swap events in real-time
4. **Sandwich MEV** — monitor mempool, front-run large DEX swaps (higher risk/complexity)

---

## Bot 2 — Freight Broker Bot

**GitHub:** `myshariff123/freight-broker-bot` (this repo)
**EC2 Container:** `freight-broker-bot`
**Start Date:** May 2026
**Strategy:** Automate LTL/FTL carrier quotes from Freightera.com

### Current Status: RUNNING — Needs Quote Fix Verification

| Metric | Value |
|--------|-------|
| Uptime | Running continuously |
| Total Profit | $0 — not yet generating quotes successfully |
| Quote Runs | Multiple failed attempts |
| Last Known Issue | `Raw quote cards found: 0` |
| Fix Status | Applied but unverified on live run |

### Bug Fix History
| Date | Bug | Fix Applied |
|------|-----|------------|
| Jun 2026 | `triple_click()` AttributeError | `click(click_count=3)` throughout |
| Jun 2026 | Weight field not found | JS DOM traversal — sibling "LB" badge |
| Jun 2026 | Zero quote cards extracted | `wait_for_function` for 'CAD' in body |
| Jun 2026 | SELECT button not clicked | Lowercase match — `.toLowerCase().includes('select')` |

### Architecture Problem
This bot solves the **supply side** (carrier rates) but has no **demand side** (actual shipments to quote). It needs:
- A way to receive customer shipment requests (load board integration, or customers submitting via form)
- Loadlink integration (estimated $200/month — deferred)
- DAT or Freightera broker account that provides incoming loads

### Open Issues
- [ ] Verify live quote extraction works after latest fix
- [ ] No load board integration (can get rates but nothing to rate)
- [ ] Quote dashboard at `:8080` not yet validated

### Next Step
SSH in and check latest freight-broker-bot logs. Then decide if load board integration is worth pursuing.

---

## Bot 3 — Immigration Alert Bot

**GitHub:** `myshariff123/freight-broker-bot` (this repo — `immigration/` module)
**EC2 Container:** `imm-alert-bot`
**Start Date:** Jun 2026
**Strategy:** Monitor 27 Canadian government immigration sites → AI analysis → Telegram + email alerts

### Current Status: RUNNING — No Subscribers Yet

| Metric | Value |
|--------|-------|
| Uptime | Running continuously |
| Paying Subscribers | 0 |
| Sources Monitored | 27 government URLs |
| Monitoring Interval | Every 15 minutes |
| AI Analyser | Claude Haiku (fast + cheap) |
| Alert Channels | Telegram + Gmail SMTP |

### Sources Coverage
| Type | Count | Includes |
|------|-------|---------|
| Federal | 10 | IRCC, Express Entry, TFWP, IMP, processing times |
| Provincial PNP | 12 | ON, BC, AB, SK, MB, NS, NB, PE, NL, NT, YT, QC |
| Special Programs | 5 | Atlantic, Rural & Northern, Agri-Food, Start-Up Visa, Caregivers |

### Business Model Problem
Government immigration policy changes infrequently (weeks between meaningful alerts). Target users (immigration consultants / RCICs) would need:
1. A reason to trust this bot over free government email alerts
2. Sufficient signal volume to justify subscribing
3. A way to discover and pay for the service

**Decision (Jun 2026):** Bot is built and deployed but business model unviable without active customer acquisition. Left running — low resource cost.

### Open Issues
- [ ] No revenue model activated
- [ ] No Telegram subscribers
- [ ] Consider: pivot to real-time regulatory data (OSFI, OSC, FINTRAC) for fintech compliance

---

## Planned Bots

### Bot 4 — Flash Loan Arb on Base Chain

**Status:** PLANNED
**Estimated Investment:** $20-50 (gas for contract deployment)
**Strategy:** Same as Flash Arb Bot but on Base (Coinbase's L2)

**Why Base:**
- Launched March 2023 — newer, less MEV bot saturation
- OP Stack architecture — low gas, fast finality
- Aerodrome Finance (dominant DEX), BaseSwap, UniswapV3 all on Base
- More arbitrage opportunities between newer pools

**Implementation Plan:**
1. Clone flash-arb-bot repo
2. Update `config/settings.py` with Base RPC (Alchemy supports Base)
3. Add Aerodrome and BaseSwap ABIs
4. Deploy FlashLiquidation.sol to Base mainnet
5. Update token pairs and pool addresses
6. Add Base to docker-compose.yml

**Estimated Time:** 1-2 sessions

---

### Bot 5 — Sports Surebetting Bot

**Status:** PLANNED
**Estimated Investment:** $100-500 (bankroll split across bookmakers)
**Strategy:** Monitor odds across multiple sportsbooks simultaneously. When sum of (1/odds) across all outcomes < 1.0 — guaranteed profit regardless of result.

**Math Example:**
- Outcome A: Odds 2.10 → implied prob = 47.6%
- Outcome B: Odds 2.10 → implied prob = 47.6%
- Total implied: 95.2% < 100% → guaranteed profit on every $100 bet = $4.80

**Bookmaker Sources to Watch:**
- Bet365, Pinnacle, SportsInteraction, BetVictor, William Hill
- Betway Canada, Sports Interaction

**Implementation:**
- Scrape/API odds from 5+ bookmakers every 30-60 seconds
- Calculate arbitrage margin for all outcome combinations
- Alert (Telegram) when margin > 1.5% to cover account friction
- Track bookmaker accounts — arb bettors get limited quickly

**Risks:**
- Bookmakers limit/ban identified arb accounts (mitigation: spread across many)
- Odds withdrawal after bet placed ("hedging" detection)
- Requires multiple funded bookmaker accounts

---

### Bot 6 — Prediction Market Cross-Platform Arb (Polymarket vs Kalshi)

**Status:** PLANNED
**Estimated Investment:** $200-500
**Strategy:** Same event priced differently on Polymarket and Kalshi. Buy YES on one, buy NO on the other. Guaranteed profit from the spread.

**Example:**
- "Will Canada call election before Dec 2026?"
- Polymarket: YES at 0.62 (= 62%), NO at 0.38
- Kalshi: YES at 0.58, NO at 0.42
- Buy NO on Polymarket (0.38) + YES on Kalshi (0.58) → total cost: 0.96, guaranteed payout: 1.00 → 4.2% profit

**APIs:**
- Polymarket: CLOB API (public)
- Kalshi: REST API (requires account + KYC)

**Implementation:**
- Python client for both APIs
- Real-time order book comparison for matching markets
- Auto-place limit orders when spread > 2% (covers fees)
- Track position inventory

**Blocker:** Kalshi requires US residency for full access. Polymarket geo-restricts Canada.

---

### Bot 7 — Crypto Funding Rate Delta-Neutral

**Status:** PLANNED
**Estimated Investment:** $200-1000
**Strategy:** Long spot on one exchange + short perpetual future on another. Earn funding rate from short position. Zero price exposure.

**How It Works:**
- Buy 1 ETH on Coinbase spot
- Short 1 ETH perpetual on Bybit
- When perpetual funding rate is positive (longs pay shorts), you RECEIVE funding
- ETH price movement = neutral (long + short cancel out)

**Expected Returns:**
- Typical funding rate: 0.01-0.03% per 8 hours = 1.09-3.28% APR
- Spikes during bull markets: 0.1%+/8h = 10%+ APR
- Risk: funding can turn negative (you pay instead of receive)

**Exchanges to Use:**
- Spot: Coinbase, Kraken (regulated, accessible in Canada)
- Perps: Bybit, OKX (check Canada accessibility)

---

## Infrastructure Costs

| Resource | Cost | Notes |
|----------|------|-------|
| AWS EC2 (t2.medium or similar) | ~$30-40/month | Runs all containers |
| Alchemy free tier | $0/month | 300M compute units, now sufficient at 60s polling |
| Anthropic API (Claude Haiku) | ~$1-5/month | Immigration bot only |
| Freightera subscription | ~$100 (one-time?) | For quote access |
| Domain + SSL | $0 | Certbot auto-renews |
| **Total** | ~$35-45/month | — |

---

## Session Log

| Date | Work Done | Outcome |
|------|-----------|---------|
| May 2026 | Flash Arb Bot deployed on Polygon + Arbitrum | Running, zero profit |
| Jun 2026 | Fixed Freightera Playwright bugs (4 fixes) | Bot runs, quotes unverified |
| Jun 2026 | Built Immigration Alert Bot (12 files) | Running, no subscribers |
| Jun 2026 | Fixed Alchemy quota: 2s → 60s polling | Alchemy usage now safe |
| Jun 2026 | Fixed BCT token EIP-55 checksum | Scan errors resolved |
| Jun 2026 | Created GitHub tracking repo (this repo) | Portfolio visible on GitHub |
