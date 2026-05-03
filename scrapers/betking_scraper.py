"""
SureNaira — BetKing Scraper
============================
BetKing Nigeria (m.betking.com) has a REST JSON API accessible
from their mobile site. Endpoints discovered via DevTools:

  GET https://www.betking.com/api/sports/prematch/events
      ?sport=soccer&marketTypes=1,5,12,16,21
      &page=1&pageSize=100

  GET https://www.betking.com/api/sports/live/events
      ?sport=soccer

Response structure:
  {
    "events": [
      {
        "id": "BK_12345",
        "home": "Arsenal",
        "away": "Chelsea",
        "competition": "Premier League",
        "startTime": "2025-05-02T14:00:00Z",
        "markets": [
          {
            "type": "1X2",
            "selections": [
              { "name": "Home", "price": 2.10 },
              { "name": "Draw", "price": 3.40 },
              { "name": "Away", "price": 3.20 }
            ]
          },
          {
            "type": "OverUnder",
            "line": 2.5,
            "selections": [
              { "name": "Over", "price": 1.90 },
              { "name": "Under", "price": 2.00 }
            ]
          }
        ]
      }
    ]
  }
"""

import time
import logging
from datetime import datetime
from typing import Optional

from scrapers.base_scraper import BaseScraper
from engine.models import OddsLeg, ScrapeResult

logger = logging.getLogger("scraper.betking")

BETKING_MARKET_MAP = {
    "1X2":             "1x2",
    "MATCH_WINNER":    "1x2",
    "OVERUNDER":       "over_under",
    "OVER_UNDER":      "over_under",
    "TOTALS":          "over_under",
    "BTTS":            "btts",
    "BOTH_TO_SCORE":   "btts",
    "ASIAN_HANDICAP":  "asian_handicap",
    "AH":              "asian_handicap",
    "HANDICAP":        "european_handicap",
    "DNB":             "dnb",
    "DRAW_NO_BET":     "dnb",
    "DOUBLE_CHANCE":   "double_chance",
    "DC":              "double_chance",
}


class BetKingScraper(BaseScraper):

    def __init__(self):
        super().__init__("betking")

    def _parse_events(self, data: dict, is_live: bool) -> list[OddsLeg]:
        legs: list[OddsLeg] = []

        events = data.get("events", []) or data.get("data", {}).get("events", [])

        for event in events:
            try:
                home_name = event.get("home", "") or event.get("homeTeam", "")
                away_name = event.get("away", "") or event.get("awayTeam", "")
                league    = event.get("competition", "") or event.get("league", "")
                event_id  = event.get("id", "")
                start_str = event.get("startTime", "")

                if not home_name or not away_name:
                    continue

                kick_off: Optional[datetime] = None
                try:
                    if start_str:
                        kick_off = datetime.fromisoformat(
                            start_str.replace("Z", "+00:00")
                        )
                except (ValueError, AttributeError):
                    pass

                event_url = f"https://m.betking.com/sport/event/{event_id}"

                markets = event.get("markets", [])
                for market in markets:
                    raw_type = (market.get("type") or market.get("marketType", "")).upper()
                    mkt_type = BETKING_MARKET_MAP.get(raw_type)
                    if not mkt_type:
                        continue

                    line: Optional[float] = None
                    try:
                        line = float(market.get("line") or market.get("handicap") or 0) or None
                    except (ValueError, TypeError):
                        pass

                    hdp_label: Optional[str] = None
                    if mkt_type == "european_handicap" and line is not None:
                        hdp_label = f"{int(line):+d}:0" if line == int(line) else f"{line}:0"

                    selections = market.get("selections", []) or market.get("outcomes", [])
                    for sel in selections:
                        name  = sel.get("name", "") or sel.get("outcome", "")
                        price = sel.get("price") or sel.get("odds") or 0

                        try:
                            odds = float(price)
                        except (ValueError, TypeError):
                            continue

                        if odds < 1.01:
                            continue

                        # Skip draw in 1X2
                        if name.strip().upper() in ("X", "DRAW", "D"):
                            continue

                        leg = self.build_leg(
                            home_team=home_name,
                            away_team=away_name,
                            league=league,
                            market_type=mkt_type,
                            raw_outcome=name,
                            odds=odds,
                            line=line,
                            handicap_label=hdp_label,
                            event_url=event_url,
                            is_live=is_live,
                            kick_off=kick_off,
                        )
                        leg.__dict__["_home_team"] = home_name
                        leg.__dict__["_away_team"] = away_name
                        leg.__dict__["_league"]    = league
                        leg.__dict__["_kick_off"]  = kick_off
                        legs.append(leg)

            except Exception as e:
                logger.debug(f"BetKing: error parsing event: {e}")
                continue

        return legs

    async def fetch_prematch_odds(self) -> ScrapeResult:
        start = time.time()
        url = f"{self.api_base}/sports/prematch/events"
        params = {
            "sport":       "soccer",
            "marketTypes": "1X2,OVERUNDER,BTTS,ASIAN_HANDICAP,HANDICAP,DNB,DOUBLE_CHANCE",
            "page":        1,
            "pageSize":    200,
        }

        logger.info("BetKing: fetching pre-match odds...")
        data = await self._get(url, params=params)

        if data is None:
            return ScrapeResult(
                bookmaker_id=self.bookmaker_id,
                success=False,
                error="No data from BetKing API",
                duration_ms=int((time.time() - start) * 1000),
            )

        legs = self._parse_events(data, is_live=False)
        logger.info(f"BetKing: parsed {len(legs)} pre-match legs")

        return ScrapeResult(
            bookmaker_id=self.bookmaker_id,
            success=True,
            legs=legs,
            duration_ms=int((time.time() - start) * 1000),
        )

    async def fetch_live_odds(self) -> ScrapeResult:
        start = time.time()
        url = f"{self.api_base}/sports/live/events"
        params = {"sport": "soccer"}

        logger.info("BetKing: fetching live odds...")
        data = await self._get(url, params=params)

        if data is None:
            return ScrapeResult(
                bookmaker_id=self.bookmaker_id,
                success=False,
                error="No data from BetKing live API",
                duration_ms=int((time.time() - start) * 1000),
            )

        legs = self._parse_events(data, is_live=True)
        logger.info(f"BetKing: parsed {len(legs)} live legs")

        return ScrapeResult(
            bookmaker_id=self.bookmaker_id,
            success=True,
            legs=legs,
            duration_ms=int((time.time() - start) * 1000),
        )
