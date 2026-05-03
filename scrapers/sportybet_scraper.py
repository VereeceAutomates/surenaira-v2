"""
SureNaira — SportyBet Scraper
==============================
SportyBet Nigeria uses Sportradar as their data backbone.
Their internal API endpoints are accessible via the mobile web version.

Discovered endpoints (via browser DevTools → Network → XHR):
  GET /api/ng/factsCenter/sportEvents
      ?sportId=sr:sport:1
      &marketId=1,18,29,68      (1=1X2, 18=OU2.5, 29=BTTS, 68=AH)
      &_t={timestamp}

  GET /api/ng/factsCenter/liveEvents
      ?sportId=sr:sport:1
      &_t={timestamp}

Response structure (simplified):
  {
    "data": {
      "sportEvents": [
        {
          "eventId": "sr:match:12345678",
          "homeTeam": { "name": "Arsenal" },
          "awayTeam": { "name": "Chelsea" },
          "tournament": { "name": "Premier League" },
          "startTime": 1700000000,
          "markets": [
            {
              "id": 1,
              "name": "1X2",
              "outcomes": [
                { "id": "1", "name": "1", "odds": "2.10" },
                { "id": "2", "name": "X", "odds": "3.40" },
                { "id": "3", "name": "2", "odds": "3.20" }
              ]
            },
            {
              "id": 18,
              "name": "Total Goals Over/Under",
              "line": "2.5",
              "outcomes": [
                { "id": "12", "name": "Over", "odds": "1.90" },
                { "id": "13", "name": "Under", "odds": "2.00" }
              ]
            }
          ]
        }
      ]
    }
  }
"""

import time
import logging
from datetime import datetime, timezone
from typing import Optional

from scrapers.base_scraper import BaseScraper
from engine.models import OddsLeg, ScrapeResult

logger = logging.getLogger("scraper.sportybet")

# SportyBet market IDs → our internal market_type
SPORTYBET_MARKET_MAP = {
    1:   "1x2",              # Match Winner (1X2)
    18:  "over_under",       # Over/Under (goals)
    29:  "btts",             # Both Teams to Score
    68:  "asian_handicap",   # Asian Handicap
    165: "european_handicap",# European Handicap
    8:   "dnb",              # Draw No Bet
    211: "double_chance",    # Double Chance
}

# Which market IDs to request (comma-separated in API call)
TARGET_MARKET_IDS = ",".join(str(k) for k in SPORTYBET_MARKET_MAP.keys())


class SportyBetScraper(BaseScraper):

    def __init__(self):
        super().__init__("sportybet")
        self.sport_id = "sr:sport:1"  # Football

    def _ts(self) -> int:
        """Current Unix timestamp (SportyBet uses this as a cache-buster)."""
        return int(time.time())

    def _parse_events(self, data: dict, is_live: bool) -> list[OddsLeg]:
        """Parse SportyBet API response into OddsLeg objects."""
        legs: list[OddsLeg] = []

        try:
            events = data.get("data", {}).get("sportEvents", [])
            if not events:
                # Also try live-specific path
                events = data.get("data", {}).get("liveEvents", [])
        except (AttributeError, KeyError):
            logger.warning("SportyBet: unexpected response structure")
            return legs

        for event in events:
            try:
                home_name = event.get("homeTeam", {}).get("name", "")
                away_name = event.get("awayTeam", {}).get("name", "")
                league    = event.get("tournament", {}).get("name", "")
                start_ts  = event.get("startTime", 0)
                event_id  = event.get("eventId", "")

                if not home_name or not away_name:
                    continue

                kick_off = None
                if start_ts:
                    kick_off = datetime.fromtimestamp(start_ts, tz=timezone.utc)

                # Deep link to this specific match on SportyBet
                event_url = (
                    f"https://www.sportybet.com/ng/sport/football"
                    f"/{event_id}"
                )

                markets = event.get("markets", [])
                for market in markets:
                    mkt_id   = market.get("id")
                    mkt_type = SPORTYBET_MARKET_MAP.get(mkt_id)
                    if not mkt_type:
                        continue

                    # For OU and AH, extract the line
                    line_str = market.get("line") or market.get("handicap")
                    line: Optional[float] = None
                    try:
                        line = float(line_str) if line_str else None
                    except (ValueError, TypeError):
                        pass

                    # For European Handicap, extract the handicap label
                    hdp_label: Optional[str] = None
                    if mkt_type == "european_handicap":
                        hdp_label = market.get("handicap") or market.get("name", "")

                    outcomes = market.get("outcomes", [])
                    for outcome in outcomes:
                        outcome_name = outcome.get("name", "")
                        odds_str     = outcome.get("odds", "0")

                        try:
                            odds = float(odds_str)
                        except (ValueError, TypeError):
                            continue

                        if odds < 1.01:
                            continue

                        # Skip the draw outcome — we only do 2-way arbs
                        # (draws are handled via cross-market pairs like EH)
                        if outcome_name.upper() == "X":
                            continue

                        leg = self.build_leg(
                            home_team=home_name,
                            away_team=away_name,
                            league=league,
                            market_type=mkt_type,
                            raw_outcome=outcome_name,
                            odds=odds,
                            line=line,
                            handicap_label=hdp_label,
                            event_url=event_url,
                            is_live=is_live,
                            kick_off=kick_off,
                        )
                        # Attach the raw team names for event matching
                        leg.__dict__["_home_team"]  = home_name
                        leg.__dict__["_away_team"]  = away_name
                        leg.__dict__["_league"]     = league
                        leg.__dict__["_kick_off"]   = kick_off
                        legs.append(leg)

            except Exception as e:
                logger.debug(f"SportyBet: error parsing event: {e}")
                continue

        return legs

    async def fetch_prematch_odds(self) -> ScrapeResult:
        start = time.time()
        url = f"{self.api_base}/factsCenter/sportEvents"
        params = {
            "sportId":   self.sport_id,
            "marketId":  TARGET_MARKET_IDS,
            "_t":        self._ts(),
        }

        logger.info(f"SportyBet: fetching pre-match odds...")
        data = await self._get(url, params=params)

        if data is None:
            return ScrapeResult(
                bookmaker_id=self.bookmaker_id,
                success=False,
                error="No data returned from SportyBet API",
                duration_ms=int((time.time() - start) * 1000),
            )

        legs = self._parse_events(data, is_live=False)
        logger.info(f"SportyBet: parsed {len(legs)} pre-match legs")

        return ScrapeResult(
            bookmaker_id=self.bookmaker_id,
            success=True,
            legs=legs,
            duration_ms=int((time.time() - start) * 1000),
        )

    async def fetch_live_odds(self) -> ScrapeResult:
        start = time.time()
        url = f"{self.api_base}/factsCenter/liveEvents"
        params = {
            "sportId": self.sport_id,
            "_t":      self._ts(),
        }

        logger.info(f"SportyBet: fetching live odds...")
        data = await self._get(url, params=params)

        if data is None:
            return ScrapeResult(
                bookmaker_id=self.bookmaker_id,
                success=False,
                error="No data returned from SportyBet live API",
                duration_ms=int((time.time() - start) * 1000),
            )

        legs = self._parse_events(data, is_live=True)
        logger.info(f"SportyBet: parsed {len(legs)} live legs")

        return ScrapeResult(
            bookmaker_id=self.bookmaker_id,
            success=True,
            legs=legs,
            duration_ms=int((time.time() - start) * 1000),
        )
