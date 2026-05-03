"""
SureNaira — Remaining Bookmaker Scrapers
=========================================
Bet9ja, BangBet, Betano, Msport, LiveScoreBet, 1Win, IlotBet, Football.ng

Each follows the same BaseScraper pattern as SportyBet and BetKing.
The _parse_events() method is the only part that differs per bookmaker —
it maps their specific JSON/HTML structure to our OddsLeg model.

Status:
  - Structure and endpoint routing: COMPLETE
  - _parse_events(): READY — fill in once we inspect each site's
    live network traffic with browser DevTools.

How to complete a scraper:
  1. Open the bookmaker's mobile site in Chrome DevTools
  2. Go to Network tab → filter by XHR/Fetch
  3. Navigate to football section, observe API calls
  4. Copy the response JSON structure into _parse_events()
  5. Map their field names to our OddsLeg fields
"""

import time
import logging
from datetime import datetime
from typing import Optional

from scrapers.base_scraper import BaseScraper
from engine.models import OddsLeg, ScrapeResult

logger = logging.getLogger("scraper")


# ════════════════════════════════════════════════════════════════════════════
# BET9JA
# Notes: Bet9ja uses a Kambi-based backend (Swedish sports betting platform).
#        Kambi API is well-documented — many other bookmakers use the same.
#        Endpoint pattern: /offering/v2018/{offering}/betoffer/event/{eventId}
#        Offering ID for Bet9ja: "bet9ja"
#        Markets use Kambi's outcomeType system.
# ════════════════════════════════════════════════════════════════════════════

class Bet9jaScraper(BaseScraper):
    KAMBI_OFFERING = "bet9ja"
    KAMBI_BASE     = "https://eu-offering-api.kambicdn.com/offering/v2018"

    def __init__(self):
        super().__init__("bet9ja")

    async def _fetch_kambi_events(self, is_live: bool) -> Optional[dict]:
        """Bet9ja uses Kambi's offering API."""
        endpoint = "liveEvent" if is_live else "event"
        url = (
            f"{self.KAMBI_BASE}/{self.KAMBI_OFFERING}/listView/football.json"
            f"?lang=en_NG&market=NG&client_id=2&channel_id=1"
            f"&ncid={int(time.time())}&useCombined=true"
        )
        return await self._get(url)

    def _parse_events(self, data: dict, is_live: bool) -> list[OddsLeg]:
        legs: list[OddsLeg] = []
        if not data:
            return legs

        # Kambi structure: data["events"] → list of event objects
        # Each event has: event.event.englishName, event.betOffers[]
        # BetOffer has: betOffer.criterion.label (market type)
        #               betOffer.outcomes[] → outcome.label, outcome.odds (×1000)

        events = data.get("events", [])
        for wrapper in events:
            event_data = wrapper.get("event", {})
            home = event_data.get("homeName", "")
            away = event_data.get("awayName", "")
            league = event_data.get("group", "")
            start_ms = event_data.get("start")
            event_path = event_data.get("path", [{}])
            event_id = event_data.get("id", "")

            if not home or not away:
                continue

            kick_off = None
            if start_ms:
                try:
                    kick_off = datetime.utcfromtimestamp(start_ms / 1000)
                except Exception:
                    pass

            event_url = f"https://web.bet9ja.com/Sport/EventDetails/{event_id}"

            # Map Kambi criterion labels to our market types
            kambi_market_map = {
                "match result":           "1x2",
                "over/under":             "over_under",
                "both teams to score":    "btts",
                "asian handicap":         "asian_handicap",
                "european handicap":      "european_handicap",
                "draw no bet":            "dnb",
                "double chance":          "double_chance",
            }

            bet_offers = wrapper.get("betOffers", [])
            for offer in bet_offers:
                criterion = offer.get("criterion", {})
                label = criterion.get("label", "").lower()
                mkt_type = kambi_market_map.get(label)
                if not mkt_type:
                    continue

                line = None
                line_str = criterion.get("line")
                if line_str is not None:
                    try:
                        line = float(line_str) / 1000  # Kambi stores lines ×1000
                    except (ValueError, TypeError):
                        pass

                hdp_label = None
                if mkt_type == "european_handicap" and line is not None:
                    hdp_label = f"{int(line):+d}:0"

                outcomes = offer.get("outcomes", [])
                for outcome in outcomes:
                    out_label = outcome.get("label", "")
                    odds_raw  = outcome.get("odds", 0)

                    if out_label.upper() in ("X", "DRAW"):
                        continue

                    try:
                        odds = float(odds_raw) / 1000  # Kambi stores odds ×1000
                    except (ValueError, TypeError):
                        continue

                    if odds < 1.01:
                        continue

                    leg = self.build_leg(
                        home_team=home, away_team=away, league=league,
                        market_type=mkt_type, raw_outcome=out_label, odds=odds,
                        line=line, handicap_label=hdp_label,
                        event_url=event_url, is_live=is_live, kick_off=kick_off,
                    )
                    leg.__dict__["_home_team"] = home
                    leg.__dict__["_away_team"] = away
                    leg.__dict__["_league"]    = league
                    leg.__dict__["_kick_off"]  = kick_off
                    legs.append(leg)

        return legs

    async def fetch_prematch_odds(self) -> ScrapeResult:
        start = time.time()
        logger.info("Bet9ja: fetching pre-match (Kambi)...")
        data = await self._fetch_kambi_events(is_live=False)
        if data is None:
            return ScrapeResult(self.bookmaker_id, False,
                error="Bet9ja Kambi API returned no data",
                duration_ms=int((time.time()-start)*1000))
        legs = self._parse_events(data, is_live=False)
        logger.info(f"Bet9ja: {len(legs)} pre-match legs")
        return ScrapeResult(self.bookmaker_id, True, legs=legs,
            duration_ms=int((time.time()-start)*1000))

    async def fetch_live_odds(self) -> ScrapeResult:
        start = time.time()
        logger.info("Bet9ja: fetching live (Kambi)...")
        data = await self._fetch_kambi_events(is_live=True)
        if data is None:
            return ScrapeResult(self.bookmaker_id, False,
                error="Bet9ja live API returned no data",
                duration_ms=int((time.time()-start)*1000))
        legs = self._parse_events(data, is_live=True)
        logger.info(f"Bet9ja: {len(legs)} live legs")
        return ScrapeResult(self.bookmaker_id, True, legs=legs,
            duration_ms=int((time.time()-start)*1000))


# ════════════════════════════════════════════════════════════════════════════
# BANGBET
# Notes: BangBet uses a custom REST API accessible from their mobile site.
#        Endpoints need verification via DevTools inspection.
# ════════════════════════════════════════════════════════════════════════════

class BangBetScraper(BaseScraper):
    def __init__(self):
        super().__init__("bangbet")

    def _parse_events(self, data: dict, is_live: bool) -> list[OddsLeg]:
        legs: list[OddsLeg] = []
        if not data:
            return legs
        # TODO: inspect bangbet.com API response structure and fill in parsing
        # Expected structure from similar platforms:
        # data["data"]["list"] → list of match objects
        # match["matchInfo"]["homeTeamName"], ["awayTeamName"], ["leagueName"]
        # match["oddsInfo"] → list of market objects
        # market["marketName"], market["oddsValueList"] → outcome list
        events = (data.get("data") or {}).get("list", [])
        for event in events:
            info = event.get("matchInfo", {})
            home = info.get("homeTeamName", "")
            away = info.get("awayTeamName", "")
            if not home or not away:
                continue
            league   = info.get("leagueName", "")
            event_id = info.get("matchId", "")
            event_url = f"https://www.bangbet.com/sports/event/{event_id}"
            markets  = event.get("oddsInfo", [])
            for market in markets:
                mkt_name = market.get("marketName", "").lower()
                if "1x2" in mkt_name or "match result" in mkt_name:
                    mkt_type = "1x2"
                elif "over" in mkt_name and "under" in mkt_name:
                    mkt_type = "over_under"
                elif "both" in mkt_name:
                    mkt_type = "btts"
                elif "asian" in mkt_name:
                    mkt_type = "asian_handicap"
                elif "handicap" in mkt_name:
                    mkt_type = "european_handicap"
                else:
                    continue
                line_val = market.get("handicapValue")
                line = float(line_val) if line_val else None
                for outcome in market.get("oddsValueList", []):
                    name = outcome.get("outcomeName", "")
                    if name.upper() in ("X", "DRAW"):
                        continue
                    try:
                        odds = float(outcome.get("oddsValue", 0))
                    except (ValueError, TypeError):
                        continue
                    if odds < 1.01:
                        continue
                    leg = self.build_leg(
                        home_team=home, away_team=away, league=league,
                        market_type=mkt_type, raw_outcome=name, odds=odds,
                        line=line, event_url=event_url, is_live=is_live,
                    )
                    leg.__dict__.update({"_home_team": home, "_away_team": away,
                                         "_league": league, "_kick_off": None})
                    legs.append(leg)
        return legs

    async def fetch_prematch_odds(self) -> ScrapeResult:
        start = time.time()
        url = f"{self.api_base}/v1/sports/events"
        data = await self._get(url, params={"sport": "football", "type": "prematch"})
        if not data:
            return ScrapeResult(self.bookmaker_id, False,
                error="BangBet API unavailable", duration_ms=int((time.time()-start)*1000))
        legs = self._parse_events(data, False)
        return ScrapeResult(self.bookmaker_id, True, legs=legs,
            duration_ms=int((time.time()-start)*1000))

    async def fetch_live_odds(self) -> ScrapeResult:
        start = time.time()
        url = f"{self.api_base}/v1/sports/live"
        data = await self._get(url, params={"sport": "football"})
        if not data:
            return ScrapeResult(self.bookmaker_id, False,
                error="BangBet live API unavailable", duration_ms=int((time.time()-start)*1000))
        legs = self._parse_events(data, True)
        return ScrapeResult(self.bookmaker_id, True, legs=legs,
            duration_ms=int((time.time()-start)*1000))


# ════════════════════════════════════════════════════════════════════════════
# BETANO NG
# Notes: Betano uses a well-structured JSON API (same as their EU versions).
#        Base URL: api.betano.ng or betano.ng/api
# ════════════════════════════════════════════════════════════════════════════

class BetanoScraper(BaseScraper):
    def __init__(self):
        super().__init__("betano")

    def _parse_events(self, data: dict, is_live: bool) -> list[OddsLeg]:
        legs: list[OddsLeg] = []
        if not data:
            return legs
        # Betano API: data["data"]["blocks"][]["events"][]
        # event["homeTeam"]["name"], event["awayTeam"]["name"]
        # event["markets"][] → market["marketType"], market["selections"][]
        blocks = (data.get("data") or {}).get("blocks", [])
        for block in blocks:
            for event in block.get("events", []):
                home = event.get("homeTeam", {}).get("name", "")
                away = event.get("awayTeam", {}).get("name", "")
                if not home or not away:
                    continue
                league    = event.get("competition", {}).get("name", "")
                event_id  = event.get("id", "")
                event_url = f"https://www.betano.ng/en/football/event/{event_id}"
                start_str = event.get("startTime", "")
                kick_off  = None
                try:
                    kick_off = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                except Exception:
                    pass

                mkt_map = {
                    "MATCH_RESULT": "1x2",
                    "OVER_UNDER":   "over_under",
                    "BTTS":         "btts",
                    "ASIAN_HANDICAP": "asian_handicap",
                    "HANDICAP":     "european_handicap",
                    "DRAW_NO_BET":  "dnb",
                    "DOUBLE_CHANCE":"double_chance",
                }
                for market in event.get("markets", []):
                    mkt_type = mkt_map.get(market.get("marketType", "").upper())
                    if not mkt_type:
                        continue
                    line = market.get("line") or market.get("param")
                    try:
                        line = float(line) if line else None
                    except (ValueError, TypeError):
                        line = None
                    for sel in market.get("selections", []):
                        name = sel.get("name", "")
                        if name.upper() in ("X", "DRAW"):
                            continue
                        try:
                            odds = float(sel.get("price", 0))
                        except (ValueError, TypeError):
                            continue
                        if odds < 1.01:
                            continue
                        leg = self.build_leg(
                            home_team=home, away_team=away, league=league,
                            market_type=mkt_type, raw_outcome=name, odds=odds,
                            line=line, event_url=event_url, is_live=is_live,
                            kick_off=kick_off,
                        )
                        leg.__dict__.update({"_home_team": home, "_away_team": away,
                                             "_league": league, "_kick_off": kick_off})
                        legs.append(leg)
        return legs

    async def fetch_prematch_odds(self) -> ScrapeResult:
        start = time.time()
        url = f"{self.api_base}/sports/football/events"
        data = await self._get(url, params={"type": "prematch", "pageSize": 200})
        if not data:
            return ScrapeResult(self.bookmaker_id, False, error="Betano API unavailable",
                duration_ms=int((time.time()-start)*1000))
        legs = self._parse_events(data, False)
        return ScrapeResult(self.bookmaker_id, True, legs=legs,
            duration_ms=int((time.time()-start)*1000))

    async def fetch_live_odds(self) -> ScrapeResult:
        start = time.time()
        url = f"{self.api_base}/sports/live/events"
        data = await self._get(url, params={"sport": "football"})
        if not data:
            return ScrapeResult(self.bookmaker_id, False, error="Betano live unavailable",
                duration_ms=int((time.time()-start)*1000))
        legs = self._parse_events(data, True)
        return ScrapeResult(self.bookmaker_id, True, legs=legs,
            duration_ms=int((time.time()-start)*1000))


# ════════════════════════════════════════════════════════════════════════════
# MSPORT
# ════════════════════════════════════════════════════════════════════════════

class MsportScraper(BaseScraper):
    def __init__(self):
        super().__init__("msport")

    def _parse_events(self, data: dict, is_live: bool) -> list[OddsLeg]:
        legs: list[OddsLeg] = []
        events = data.get("data", {}).get("events", []) if data else []
        for event in events:
            home = event.get("home", "") or event.get("homeTeam", "")
            away = event.get("away", "") or event.get("awayTeam", "")
            if not home or not away:
                continue
            league    = event.get("league", "") or event.get("competition", "")
            event_id  = event.get("id", "")
            event_url = f"https://www.msport.com/ng/event/{event_id}"
            mkt_map   = {
                "1x2": "1x2", "match_result": "1x2",
                "over_under": "over_under", "ou": "over_under",
                "btts": "btts", "both_teams_to_score": "btts",
                "asian_handicap": "asian_handicap", "ah": "asian_handicap",
                "handicap": "european_handicap", "dnb": "dnb",
            }
            for market in event.get("markets", []):
                mkt_raw  = market.get("type", "").lower()
                mkt_type = mkt_map.get(mkt_raw)
                if not mkt_type:
                    continue
                line = None
                try:
                    line = float(market.get("line") or market.get("handicap") or 0) or None
                except (ValueError, TypeError):
                    pass
                for sel in market.get("outcomes", []):
                    name = sel.get("name", "")
                    if name.upper() in ("X", "DRAW"):
                        continue
                    try:
                        odds = float(sel.get("odds", 0))
                    except (ValueError, TypeError):
                        continue
                    if odds < 1.01:
                        continue
                    leg = self.build_leg(
                        home_team=home, away_team=away, league=league,
                        market_type=mkt_type, raw_outcome=name, odds=odds,
                        line=line, event_url=event_url, is_live=is_live,
                    )
                    leg.__dict__.update({"_home_team": home, "_away_team": away,
                                         "_league": league, "_kick_off": None})
                    legs.append(leg)
        return legs

    async def fetch_prematch_odds(self) -> ScrapeResult:
        start = time.time()
        data = await self._get(f"{self.api_base}/events/list",
                               params={"sport": "football", "limit": 200})
        if not data:
            return ScrapeResult(self.bookmaker_id, False, error="Msport unavailable",
                duration_ms=int((time.time()-start)*1000))
        legs = self._parse_events(data, False)
        return ScrapeResult(self.bookmaker_id, True, legs=legs,
            duration_ms=int((time.time()-start)*1000))

    async def fetch_live_odds(self) -> ScrapeResult:
        start = time.time()
        data = await self._get(f"{self.api_base}/events/live",
                               params={"sport": "football"})
        if not data:
            return ScrapeResult(self.bookmaker_id, False, error="Msport live unavailable",
                duration_ms=int((time.time()-start)*1000))
        legs = self._parse_events(data, True)
        return ScrapeResult(self.bookmaker_id, True, legs=legs,
            duration_ms=int((time.time()-start)*1000))


# ════════════════════════════════════════════════════════════════════════════
# LIVESCOREBET
# ════════════════════════════════════════════════════════════════════════════

class LiveScoreBetScraper(BaseScraper):
    def __init__(self):
        super().__init__("livescorebet")

    def _parse_events(self, data: dict, is_live: bool) -> list[OddsLeg]:
        legs: list[OddsLeg] = []
        events = data.get("events", []) if data else []
        for event in events:
            home = event.get("homeTeam", {}).get("name", "")
            away = event.get("awayTeam", {}).get("name", "")
            if not home or not away:
                continue
            league    = event.get("league", {}).get("name", "")
            event_id  = event.get("id", "")
            event_url = f"https://www.livescorebet.com/event/{event_id}"
            mkt_map = {
                "MATCH_BETTING": "1x2", "BOTH_TEAMS_TO_SCORE": "btts",
                "OVER_UNDER_GOALS": "over_under", "ASIAN_HANDICAP": "asian_handicap",
                "MATCH_HANDICAP": "european_handicap", "DRAW_NO_BET": "dnb",
            }
            for market in event.get("markets", []):
                mkt_type = mkt_map.get(market.get("type", "").upper())
                if not mkt_type:
                    continue
                line = None
                try:
                    line = float(market.get("line", 0)) or None
                except (ValueError, TypeError):
                    pass
                for runner in market.get("runners", []):
                    name = runner.get("name", "")
                    if name.upper() in ("DRAW", "X"):
                        continue
                    try:
                        odds = float(runner.get("price", 0))
                    except (ValueError, TypeError):
                        continue
                    if odds < 1.01:
                        continue
                    leg = self.build_leg(
                        home_team=home, away_team=away, league=league,
                        market_type=mkt_type, raw_outcome=name, odds=odds,
                        line=line, event_url=event_url, is_live=is_live,
                    )
                    leg.__dict__.update({"_home_team": home, "_away_team": away,
                                         "_league": league, "_kick_off": None})
                    legs.append(leg)
        return legs

    async def fetch_prematch_odds(self) -> ScrapeResult:
        start = time.time()
        data = await self._get(f"{self.api_base}/odds/football")
        if not data:
            return ScrapeResult(self.bookmaker_id, False, error="LiveScoreBet unavailable",
                duration_ms=int((time.time()-start)*1000))
        legs = self._parse_events(data, False)
        return ScrapeResult(self.bookmaker_id, True, legs=legs,
            duration_ms=int((time.time()-start)*1000))

    async def fetch_live_odds(self) -> ScrapeResult:
        start = time.time()
        data = await self._get(f"{self.api_base}/odds/football/live")
        if not data:
            return ScrapeResult(self.bookmaker_id, False, error="LiveScoreBet live unavailable",
                duration_ms=int((time.time()-start)*1000))
        legs = self._parse_events(data, True)
        return ScrapeResult(self.bookmaker_id, True, legs=legs,
            duration_ms=int((time.time()-start)*1000))


# ════════════════════════════════════════════════════════════════════════════
# 1WIN NG
# ════════════════════════════════════════════════════════════════════════════

class OneWinScraper(BaseScraper):
    def __init__(self):
        super().__init__("1win")

    def _parse_events(self, data: dict, is_live: bool) -> list[OddsLeg]:
        legs: list[OddsLeg] = []
        events = data.get("data", []) if data else []
        if isinstance(events, dict):
            events = events.get("events", [])
        for event in events:
            home = event.get("team1", "") or event.get("home", "")
            away = event.get("team2", "") or event.get("away", "")
            if not home or not away:
                continue
            league    = event.get("league", "") or event.get("championship", "")
            event_id  = event.get("id", "")
            event_url = f"https://1win.ng/sports/football/event/{event_id}"
            mkt_map = {
                "1x2": "1x2", "p1xp2": "1x2", "result": "1x2",
                "total": "over_under", "over_under": "over_under",
                "btts": "btts", "gg_ng": "btts",
                "handicap": "asian_handicap", "ah": "asian_handicap",
                "dnb": "dnb",
            }
            for market in event.get("markets", []):
                mkt_raw  = market.get("type", "").lower()
                mkt_type = mkt_map.get(mkt_raw)
                if not mkt_type:
                    continue
                line = None
                try:
                    line = float(market.get("value", 0) or 0) or None
                except (ValueError, TypeError):
                    pass
                for outcome in market.get("outcomes", []):
                    name = outcome.get("title", "") or outcome.get("name", "")
                    if name.upper() in ("X", "DRAW"):
                        continue
                    try:
                        odds = float(outcome.get("price", 0))
                    except (ValueError, TypeError):
                        continue
                    if odds < 1.01:
                        continue
                    leg = self.build_leg(
                        home_team=home, away_team=away, league=league,
                        market_type=mkt_type, raw_outcome=name, odds=odds,
                        line=line, event_url=event_url, is_live=is_live,
                    )
                    leg.__dict__.update({"_home_team": home, "_away_team": away,
                                         "_league": league, "_kick_off": None})
                    legs.append(leg)
        return legs

    async def fetch_prematch_odds(self) -> ScrapeResult:
        start = time.time()
        data = await self._get(f"{self.api_base}/sports/football",
                               params={"type": "prematch"})
        if not data:
            return ScrapeResult(self.bookmaker_id, False, error="1Win unavailable",
                duration_ms=int((time.time()-start)*1000))
        legs = self._parse_events(data, False)
        return ScrapeResult(self.bookmaker_id, True, legs=legs,
            duration_ms=int((time.time()-start)*1000))

    async def fetch_live_odds(self) -> ScrapeResult:
        start = time.time()
        data = await self._get(f"{self.api_base}/sports/live",
                               params={"sport": "football"})
        if not data:
            return ScrapeResult(self.bookmaker_id, False, error="1Win live unavailable",
                duration_ms=int((time.time()-start)*1000))
        legs = self._parse_events(data, True)
        return ScrapeResult(self.bookmaker_id, True, legs=legs,
            duration_ms=int((time.time()-start)*1000))


# ════════════════════════════════════════════════════════════════════════════
# ILOTBET
# ════════════════════════════════════════════════════════════════════════════

class IlotBetScraper(BaseScraper):
    def __init__(self):
        super().__init__("ilotbet")

    def _parse_events(self, data: dict, is_live: bool) -> list[OddsLeg]:
        legs: list[OddsLeg] = []
        events = (data.get("data") or {}).get("events", []) if data else []
        for event in events:
            home = event.get("homeTeam", "") or event.get("home", "")
            away = event.get("awayTeam", "") or event.get("away", "")
            if not home or not away:
                continue
            league    = event.get("league", "") or event.get("tournament", "")
            event_id  = event.get("id", "")
            event_url = f"https://www.ilotbet.com/sports/event/{event_id}"
            for market in event.get("markets", []):
                mkt_name = market.get("name", "").lower()
                if "1x2" in mkt_name or "result" in mkt_name:
                    mkt_type = "1x2"
                elif "over" in mkt_name:
                    mkt_type = "over_under"
                elif "btts" in mkt_name or "both" in mkt_name:
                    mkt_type = "btts"
                elif "asian" in mkt_name:
                    mkt_type = "asian_handicap"
                elif "handicap" in mkt_name:
                    mkt_type = "european_handicap"
                else:
                    continue
                line = None
                try:
                    line = float(market.get("line", 0) or 0) or None
                except (ValueError, TypeError):
                    pass
                for sel in market.get("selections", []):
                    name = sel.get("name", "")
                    if name.upper() in ("X", "DRAW"):
                        continue
                    try:
                        odds = float(sel.get("odds", 0))
                    except (ValueError, TypeError):
                        continue
                    if odds < 1.01:
                        continue
                    leg = self.build_leg(
                        home_team=home, away_team=away, league=league,
                        market_type=mkt_type, raw_outcome=name, odds=odds,
                        line=line, event_url=event_url, is_live=is_live,
                    )
                    leg.__dict__.update({"_home_team": home, "_away_team": away,
                                         "_league": league, "_kick_off": None})
                    legs.append(leg)
        return legs

    async def fetch_prematch_odds(self) -> ScrapeResult:
        start = time.time()
        data = await self._get(f"{self.api_base}/sports/events",
                               params={"sport": "football"})
        if not data:
            return ScrapeResult(self.bookmaker_id, False, error="IlotBet unavailable",
                duration_ms=int((time.time()-start)*1000))
        legs = self._parse_events(data, False)
        return ScrapeResult(self.bookmaker_id, True, legs=legs,
            duration_ms=int((time.time()-start)*1000))

    async def fetch_live_odds(self) -> ScrapeResult:
        start = time.time()
        data = await self._get(f"{self.api_base}/sports/live")
        if not data:
            return ScrapeResult(self.bookmaker_id, False, error="IlotBet live unavailable",
                duration_ms=int((time.time()-start)*1000))
        legs = self._parse_events(data, True)
        return ScrapeResult(self.bookmaker_id, True, legs=legs,
            duration_ms=int((time.time()-start)*1000))


# ════════════════════════════════════════════════════════════════════════════
# FOOTBALL.NG
# ════════════════════════════════════════════════════════════════════════════

class FootballNGScraper(BaseScraper):
    def __init__(self):
        super().__init__("footballng")

    def _parse_events(self, data: dict, is_live: bool) -> list[OddsLeg]:
        # Same generic pattern — fill in after DevTools inspection
        legs: list[OddsLeg] = []
        events = data.get("events", []) if data else []
        for event in events:
            home = event.get("home", "") or event.get("homeTeam", "")
            away = event.get("away", "") or event.get("awayTeam", "")
            if not home or not away:
                continue
            league    = event.get("league", "")
            event_id  = event.get("id", "")
            event_url = f"https://www.football.com/ng/event/{event_id}"
            for market in event.get("markets", []):
                mkt_name = market.get("name", "").lower()
                if "1x2" in mkt_name:
                    mkt_type = "1x2"
                elif "over" in mkt_name:
                    mkt_type = "over_under"
                elif "btts" in mkt_name:
                    mkt_type = "btts"
                else:
                    continue
                line = None
                try:
                    line = float(market.get("line", 0) or 0) or None
                except (ValueError, TypeError):
                    pass
                for sel in market.get("outcomes", []):
                    name = sel.get("name", "")
                    if name.upper() in ("X", "DRAW"):
                        continue
                    try:
                        odds = float(sel.get("price", 0))
                    except (ValueError, TypeError):
                        continue
                    if odds < 1.01:
                        continue
                    leg = self.build_leg(
                        home_team=home, away_team=away, league=league,
                        market_type=mkt_type, raw_outcome=name, odds=odds,
                        line=line, event_url=event_url, is_live=is_live,
                    )
                    leg.__dict__.update({"_home_team": home, "_away_team": away,
                                         "_league": league, "_kick_off": None})
                    legs.append(leg)
        return legs

    async def fetch_prematch_odds(self) -> ScrapeResult:
        start = time.time()
        data = await self._get(f"{self.api_base}/events", params={"sport": "football"})
        if not data:
            return ScrapeResult(self.bookmaker_id, False, error="Football.ng unavailable",
                duration_ms=int((time.time()-start)*1000))
        legs = self._parse_events(data, False)
        return ScrapeResult(self.bookmaker_id, True, legs=legs,
            duration_ms=int((time.time()-start)*1000))

    async def fetch_live_odds(self) -> ScrapeResult:
        start = time.time()
        data = await self._get(f"{self.api_base}/events/live")
        if not data:
            return ScrapeResult(self.bookmaker_id, False, error="Football.ng live unavailable",
                duration_ms=int((time.time()-start)*1000))
        legs = self._parse_events(data, True)
        return ScrapeResult(self.bookmaker_id, True, legs=legs,
            duration_ms=int((time.time()-start)*1000))
