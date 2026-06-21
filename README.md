# Autonomous Bot Portfolio — myshariff123

> **Server:** AWS EC2 `35.183.103.197` (Canada) · **Stack:** Docker Compose · **Managed by:** Portainer (`http://35.183.103.197:9000`)

---

## Live Bot Status

| Bot | Container | Status | Chain / Platform | Purpose |
|-----|-----------|--------|-----------------|---------|
| [Flash Arb Bot](#1-flash-arb-bot) | `flash-arb-bot` | ✅ Running | Polygon + Arbitrum | Flash loan DEX arbitrage + Aave V3 liquidations |
| [Freight Broker Bot](#2-freight-broker-bot) | `freight-broker-bot` | ✅ Running | Freightera.com | LTL/FTL carrier quote automation |
| [Freight Dashboard](#2-freight-broker-bot) | `freight-dashboard` | ✅ Running | Web (port 8080) | Real-time freight quote monitoring |
| [Immigration Alert Bot](#3-immigration-alert-bot) | `imm-alert-bot` | ✅ Running | Telegram + Gmail | Canadian immigration policy change alerts |
| [Mortgage Site](#4-mortgage-site) | `mortgage-site` | ⚠️ Unhealthy | Web | Mortgage lead capture (needs fix) |
| Postgres DB | `freight-postgres` | ✅ Healthy | Internal | Shared database for freight + immigration bots |
| Nginx | `arb-nginx` | ✅ Running | Port 80/443 | Reverse proxy for arb bot dashboard |
| Certbot | `certbot` | ✅ Running | SSL | Auto-renew SSL certificates |
| Portainer | `portainer` | ✅ Running | Port 9000 | Container management UI |
| Watchtower | `watchtower` | ❌ Restarting | — | Auto-update containers (failing — needs fix) |

---

## Repository Map

```
autonomous-bots/
│
├── freightera/              # Freightera quote scraper (Playwright)
│   ├── quote_bot.py         # Main bot — fills LTL/FTL form, extracts carrier quotes
│   └── quote_handler.py     # Quote processing logic
│
├── immigration/             # Canadian immigration policy monitor
│   ├── sources.py           # 27 monitored government URLs
│   ├── scraper.py           # httpx + BeautifulSoup scraper
│   ├── analyzer.py          # Claude Haiku AI change analysis
│   ├── notifier.py          # Telegram + Gmail SMTP delivery
│   ├── commands.py          # Telegram command handlers
│   ├── scheduler.py         # APScheduler 15-min monitoring cycle
│   ├── models.py            # SQLAlchemy DB models
│   └── database.py          # Postgres connection (reuses freight DB)
│
├── scraper/                 # Load board scrapers (inactive)
│   ├── freightera_scraper.py
│   ├── dat_scraper.py
│   ├── loadlink_scraper.py
│   └── loadboard_123_scraper.py
│
├── engine/                  # Rate engine
│   ├── lane_rates.py        # Lane rate calculations
│   └── opportunity_scorer.py # Opportunity scoring
│
├── carriers/                # Carrier database
│   ├── carrier_builder.py
│   └── seed_ab_carriers.py
│
├── dashboard/               # Web dashboard (port 8080)
│   └── app.py
│
├── alerts/                  # Telegram alerts
│   └── telegram_bot.py
│
├── tracker/                 # Database models for freight tracking
│   ├── database.py
│   └── models.py
│
├── immigration_main.py      # Immigration bot entry point
├── main.py                  # Freight bot entry point
├── docker-compose.yml       # All services definition
├── Dockerfile               # Freight bot image
├── Dockerfile.immigration   # Immigration bot image
├── Dockerfile.dashboard     # Dashboard image
└── BOTS.md                  # Detailed bot tracking & performance log
```

---

## 1. Flash Arb Bot

**Repo:** [`myshariff123/flash-arb-bot`](https://github.com/myshariff123/flash-arb-bot)
**Path on EC2:** `/opt/flash-arb-bot/`
**Container:** `flash-arb-bot`

### What It Does
Monitors Uniswap V3, QuickSwap, and SushiSwap pools on Polygon and Arbitrum simultaneously. When the same token pair is priced differently across two DEX pools, the bot:
1. Takes a flash loan (zero-capital borrow)
2. Buys on the cheaper DEX
3. Sells on the expensive DEX
4. Repays the flash loan
5. Keeps the spread — all in a single atomic transaction

If the math doesn't work out, the transaction reverts automatically. **You cannot lose principal.**

Also runs an Aave V3 liquidation scanner — monitors borrower health factors and liquidates undercollateralised positions for a 5-8% bonus.

### Key Files
| File | Purpose |
|------|---------|
| `bot/scanner.py` | DEX price scanner — polls every **60s** (changed from 2s to save Alchemy quota) |
| `bot/liquidation_scanner.py` | Aave V3 health factor monitor — polls every **60s** |
| `bot/executor.py` | Transaction builder and submitter |
| `bot/main.py` | Entry point — runs scanner + executor concurrently |
| `config/settings.py` | Chain configs, DEX addresses, token pairs |
| `contracts/FlashLiquidation.sol` | On-chain Solidity contract |

### Deployed Contracts
| Chain | Contract Address |
|-------|-----------------|
| Polygon | `0x4847ae41E563FdA8945A197312544FF51561094C` |
| Arbitrum | `0x4847ae41E563FdA8945A197312544FF51561094C` |

### Wallet
`0xc76Ac0889e8Cc7449e862C8671BcE6E2579088d6`

### Current Config Changes Applied
- Polling interval: 2s → 60s (saves Alchemy API compute units)
- BCT token checksum fixed: `0x2F800Db0fdb5223b3C3f354886d907A671414A7F`
- Running on Polygon + Arbitrum simultaneously

### Known Issues
- Alchemy free tier: 50% consumed mid-month due to previous 2s polling. Fixed.
- TheGraph subgraph bootstrap fails on startup (OK — uses live event scanning instead)
- Watchtower container restarting (unrelated to arb bot)

### Management Commands
```bash
# SSH into EC2
ssh -i ~/Downloads/"ECOM Keypair.pem" ubuntu@35.183.103.197

# View live logs
docker logs -f flash-arb-bot

# Restart
docker restart flash-arb-bot

# Check scanner interval
docker exec flash-arb-bot grep -n "sleep" /app/bot/scanner.py
```

---

## 2. Freight Broker Bot

**Repo:** This repository
**Path on EC2:** `/opt/freight-broker-bot/`
**Container:** `freight-broker-bot`

### What It Does
Automates carrier quote collection from Freightera.com using Playwright browser automation. The bot:
1. Logs into Freightera with stored credentials
2. Fills the LTL/FTL shipment form (origin, destination, weight, dimensions)
3. Waits for carrier bids to load
4. Extracts all carrier quotes (price, transit days, rate name)
5. Stores quotes in Postgres
6. Sends Telegram alerts for profitable margins

### Key Files
| File | Purpose |
|------|---------|
| `freightera/quote_bot.py` | Main Playwright automation — login, form fill, quote extraction |
| `freightera/quote_handler.py` | Quote processing and margin calculation |
| `main.py` | Entry point with scheduling |
| `dashboard/app.py` | Web dashboard — view quotes at port 8080 |
| `alerts/telegram_bot.py` | Telegram alert delivery |

### Critical Fixes Applied
- `triple_click()` → `click(click_count=3)` (ElementHandle vs Locator API)
- Weight field: JS DOM traversal finds input by sibling "LB" badge (not placeholder)
- Quote extraction: waits for "CAD" in body text, uses case-insensitive "select" button match
- Login: dismisses cookie banner first, uses `button:has-text("LOG IN")` specifically

### Dashboard
Access at: `http://35.183.103.197:8080`

### Known Issues
- Quote extraction fix deployed but not yet confirmed on live run (raw quote cards = 0 was last known log state)
- No demand-side (load board) integration — bot gets supply (carrier rates) only

### Management Commands
```bash
docker logs -f freight-broker-bot
docker logs -f freight-dashboard

# Update code without rebuilding
docker cp freightera/quote_bot.py freight-broker-bot:/app/freightera/quote_bot.py
docker restart freight-broker-bot
```

---

## 3. Immigration Alert Bot

**Container:** `imm-alert-bot`
**Path on EC2:** `/opt/freight-broker-bot/` (shares codebase)
**Telegram:** `IMM_TELEGRAM_BOT_TOKEN` in `.env`

### What It Does
Monitors 27 Canadian immigration government websites every 15 minutes:
- 10 Federal sources (IRCC notices, Express Entry, processing times, TFWP, IMP, etc.)
- 12 Provincial PNP programs (ON, BC, AB, SK, MB, NS, NB, PE, NL, NT, YT, QC)
- 5 Special programs (Atlantic, Rural & Northern, Agri-Food, Start-Up Visa, Caregivers)

When content changes, Claude Haiku analyses the change and sends a structured Telegram + email alert with:
- Impact level (CRITICAL / HIGH / MEDIUM / LOW)
- Affected case types (19 possible categories)
- Immediate RCIC actions required
- Deadline sensitivity flag

### Sources Monitored (27 total)
All defined in `immigration/sources.py`. Government sites scraped with httpx + BeautifulSoup targeting `.wb-cont` (Government of Canada Wet Boew theme).

### Telegram Commands
| Command | Action |
|---------|--------|
| `/start` | Subscribe to alerts |
| `/email your@email.com` | Add email delivery |
| `/provinces ON BC AB` | Filter by province |
| `/level HIGH` | Set minimum alert level |
| `/summary` | Last 24 hours of changes |
| `/history 7` | Last N days |
| `/status` | Current settings |
| `/pause` / `/resume` / `/stop` | Manage subscription |

### Management Commands
```bash
docker logs -f imm-alert-bot

# Check monitoring cycle
docker logs imm-alert-bot 2>&1 | grep -E "BASELINE|CHANGED|ALERT|cycle"
```

---

## 4. Mortgage Site

**Container:** `mortgage-site`
**Status:** ⚠️ Unhealthy

Currently unhealthy — needs investigation.

```bash
docker logs mortgage-site | tail -30
```

---

## Server Management

### SSH Access
```bash
ssh -i ~/Downloads/"ECOM Keypair.pem" ubuntu@35.183.103.197
```

### View All Containers
```bash
docker ps -a --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
```

### Restart All Services
```bash
cd /opt/freight-broker-bot && docker compose restart
cd /opt/flash-arb-bot && docker compose restart
```

### View Logs (all containers simultaneously)
```bash
docker compose -f /opt/freight-broker-bot/docker-compose.yml logs -f --tail=50
```

### Alchemy API Usage
Monitor at: `dashboard.alchemy.com`
Current rate: 60s polling on Polygon + Arbitrum (saves ~93% vs previous 2s)

---

## Environment Variables

### Freight Bot (`/opt/freight-broker-bot/.env`)
| Variable | Purpose |
|----------|---------|
| `FREIGHTERA_EMAIL` | Freightera login |
| `FREIGHTERA_PASSWORD` | Freightera login |
| `TELEGRAM_BOT_TOKEN` | Freight bot Telegram |
| `TELEGRAM_CHAT_ID` | Alert recipient |
| `POSTGRES_PASSWORD` | Database password |
| `DATABASE_URL` | Full Postgres connection string |
| `IMM_TELEGRAM_BOT_TOKEN` | Immigration bot Telegram |
| `GMAIL_ADDRESS` | Gmail for email alerts |
| `GMAIL_APP_PASSWORD` | Gmail App Password (not regular password) |
| `ANTHROPIC_API_KEY` | Claude Haiku for immigration analysis |

### Flash Arb Bot (`/opt/flash-arb-bot/.env`)
| Variable | Purpose |
|----------|---------|
| `WALLET_ADDRESS` | Executing wallet |
| `PRIVATE_KEY` | Wallet private key |
| `POLYGON_WS_URL` | Alchemy Polygon WebSocket |
| `POLYGON_HTTP_URL` | Alchemy Polygon HTTP |
| `ARBITRUM_WS_URL` | Alchemy Arbitrum WebSocket |
| `ARBITRUM_HTTP_URL` | Alchemy Arbitrum HTTP |
| `CONTRACT_ADDRESS_POLYGON` | Deployed arb contract |
| `CONTRACT_ADDRESS_ARBITRUM` | Deployed arb contract |
| `TELEGRAM_BOT_TOKEN` | Alert bot token |
| `TELEGRAM_CHAT_ID` | Alert recipient |

---

## Next Planned Bots

See [`BOTS.md`](./BOTS.md) for detailed planning and performance tracking.

| Priority | Bot | Status | Est. Start |
|----------|-----|--------|-----------|
| 1 | Flash Loan Arb on Base Chain | Planned | Next session |
| 2 | Sports Surebetting Bot | Planned | TBD |
| 3 | Prediction Market Arb (Polymarket vs Kalshi) | Planned | TBD |
| 4 | Crypto Funding Rate Delta-Neutral | Planned | TBD |

---

*Last updated: June 2026 · EC2: `35.183.103.197` (ca-central-1)*
