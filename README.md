# SureNaira — Nigerian Arbitrage Betting Scanner

Real-time surebet scanner for 10 Nigerian bookmakers.
Detects guaranteed-profit 2-outcome arbs across direct and cross markets.

---

## Architecture

```
surenaira/
├── main.py                        # Entry point (uvicorn target)
├── requirements.txt
├── config/
│   └── settings.py                # All bookmakers, markets, scrape config
├── engine/
│   ├── models.py                  # OddsLeg, MatchEvent, ArbOpportunity
│   ├── matcher.py                 # Fuzzy event matching across bookmakers
│   ├── arb_engine.py              # Arb detection — direct + cross markets
│   └── orchestrator.py            # Scheduler, pipeline, ArbStore
├── scrapers/
│   ├── base_scraper.py            # Abstract base + outcome normalisation
│   ├── sportybet_scraper.py       # SportyBet (Sportradar API)
│   ├── betking_scraper.py         # BetKing (REST API)
│   └── all_scrapers.py            # Bet9ja, BangBet, Betano, Msport,
│                                  # LiveScoreBet, 1Win, IlotBet, Football.ng
├── api/
│   └── server.py                  # FastAPI + WebSocket server
└── logs/
    └── surenaira.log
```

---

## How It Works

### 1. Scraping (every 60s pre-match, every 15s live)
Each bookmaker scraper hits that bookie's internal API endpoint
(discovered via browser DevTools) and returns normalised `OddsLeg` objects.

### 2. Event Matching
The `EventMatcher` uses fuzzy string matching (token-sort ratio) to link
legs from different bookmakers to the same real-world match.
Threshold: 82% similarity on BOTH home and away team names.

### 3. Arb Detection
The `ArbEngine` scans each event's legs for 2-outcome arbs:

**Direct arbs** — same market type, same line, different bookmakers:
- Over 2.5 @ 2.10 (SportyBet) vs Under 2.5 @ 2.05 (Bet9ja)

**Cross-market arbs** — different market types, exhaustive coverage:
- Home (-1:0) EH @ 1.90 (SportyBet) vs Away Win 1X2 @ 2.30 (BetKing)
  → EH covers Home Win + Draw, 1X2 covers Away Win = 100% coverage ✓

**Arb formula:**
```
implied_sum = (1/oddsA) + (1/oddsB)
profit_pct  = (1 - implied_sum) / implied_sum × 100
```

**Optimal stake split:**
```
stake_A = budget × (1/oddsA) / implied_sum
stake_B = budget × (1/oddsB) / implied_sum
```
Both legs return exactly the same amount — profit is guaranteed regardless.

### 4. API
FastAPI serves results via REST + WebSocket.

---

## API Reference

```
GET  /api/arbs              List arbs (filterable)
GET  /api/arbs/{id}         Single arb + stakes table
GET  /api/stats             Dashboard counts
GET  /api/bookmakers        Bookmaker status
POST /api/calculate         Stake calculator
WS   /ws/arbs               Real-time push stream (15s interval)
```

**Filter params for /api/arbs:**
```
market_type=direct|cross
is_live=true|false
min_profit_pct=2.0
bookmaker=sportybet,bet9ja
sport=football
limit=50
```

---

## Installation & Running

```bash
# 1. Clone and enter project
cd surenaira

# 2. Install dependencies
pip install -r requirements.txt

# 3. Install Playwright browser (for JS-heavy bookmakers)
playwright install chromium

# 4. Create log directory
mkdir -p logs

# 5. Run the server
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Server starts at: http://localhost:8000
# API docs at:      http://localhost:8000/docs
```

---

## Supported Markets

| Market | Leg A | Leg B | Exhaustive? |
|--------|-------|-------|-------------|
| Home/Away (DNB) | Home Win | Away Win | ✓ (no draw) |
| Over/Under | Over X | Under X | ✓ |
| Asian Handicap | Home -X | Away +X | ✓ (same line) |
| BTTS | Yes | No | ✓ |
| **Home (-1:0) EH × Away Win** | Home EH | Away 1X2 | ✓ cross |
| **Away (-1:0) EH × Home Win** | Away EH | Home 1X2 | ✓ cross |
| **Home AH -0.5 × X2** | Home AH | Draw or Away | ✓ cross |

---

## Bookmakers

| Bookmaker | Method | Markets | Status |
|-----------|--------|---------|--------|
| SportyBet | Sportradar API | All | ✅ Active |
| Bet9ja | Kambi API | All | ✅ Active |
| BetKing | REST API | All | ✅ Active |
| BangBet | REST API | All | 🔧 Needs DevTools verification |
| Betano.ng | REST API | All | 🔧 Needs DevTools verification |
| Msport | REST API | All | 🔧 Needs DevTools verification |
| LiveScoreBet | REST API | All | 🔧 Needs DevTools verification |
| 1Win.ng | REST API | All | 🔧 Needs DevTools verification |
| IlotBet | Playwright | All | 🔧 Needs DevTools verification |
| Football.ng | REST API | All | 🔧 Needs DevTools verification |

---

## Completing the Remaining Scrapers

For each bookmaker marked "Needs DevTools verification":
1. Open site in Chrome → F12 → Network tab → XHR filter
2. Navigate to football section
3. Find the JSON response with odds data
4. Copy the URL and response structure
5. Update the `_parse_events()` method in `all_scrapers.py`

---

## Next Steps

- [ ] Deploy to VPS (Ubuntu 22.04 recommended)
- [ ] Add Nginx reverse proxy + SSL
- [ ] Wire frontend to `/api/arbs` and `/ws/arbs`
- [ ] Add rotating proxy pool for anti-bot protection
- [ ] Add Playwright scrapers for JS-heavy bookmakers
- [ ] Add user accounts + email/push alerts
- [ ] Add arb history database (PostgreSQL)
