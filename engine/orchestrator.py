"""
SureNaira — Scraping Orchestrator
====================================
Coordinates all bookmaker scrapers running in parallel,
feeds results through event matching, then into the arb engine.
Acts as the central nervous system of the backend.

Flow:
  1. Scheduler triggers all active scrapers (async, concurrent)
  2. Each scraper returns ScrapeResult with list[OddsLeg]
  3. EventMatcher assigns each OddsLeg to a MatchEvent
  4. ArbEngine scans each event's legs for opportunities
  5. Results stored in ArbStore (in-memory, Redis-backed in production)
  6. FastAPI serves the store to the frontend via REST
"""

import asyncio
import logging
import time
from collections import defaultdict
from datetime import datetime
from typing import Optional

from engine.models import OddsLeg, MatchEvent, ArbOpportunity, ScrapeResult
from engine.matcher import EventMatcher
from engine.arb_engine import ArbEngine
from config.settings import SCRAPE_CONFIG, BOOKMAKERS

logger = logging.getLogger("orchestrator")


# ─── Scraper Registry ────────────────────────────────────────────────────────
# Import all scrapers. Add new bookmakers here.

def _load_scrapers() -> dict:
    """
    Dynamically load all active scraper instances.
    Returns dict: bookmaker_id → scraper instance.
    """
    scrapers = {}

    # Only import scrapers for active bookmakers
    if BOOKMAKERS.get("sportybet", {}).get("active"):
        from scrapers.sportybet_scraper import SportyBetScraper
        scrapers["sportybet"] = SportyBetScraper()

    if BOOKMAKERS.get("betking", {}).get("active"):
        from scrapers.betking_scraper import BetKingScraper
        scrapers["betking"] = BetKingScraper()

    # Future scrapers — stub classes ready to be implemented
    # if BOOKMAKERS.get("bet9ja", {}).get("active"):
    #     from scrapers.bet9ja_scraper import Bet9jaScraper
    #     scrapers["bet9ja"] = Bet9jaScraper()
    #
    # if BOOKMAKERS.get("bangbet", {}).get("active"):
    #     from scrapers.bangbet_scraper import BangBetScraper
    #     scrapers["bangbet"] = BangBetScraper()
    #
    # if BOOKMAKERS.get("betano", {}).get("active"):
    #     from scrapers.betano_scraper import BetanoScraper
    #     scrapers["betano"] = BetanoScraper()
    #
    # if BOOKMAKERS.get("msport", {}).get("active"):
    #     from scrapers.msport_scraper import MsportScraper
    #     scrapers["msport"] = MsportScraper()
    #
    # if BOOKMAKERS.get("livescorebet", {}).get("active"):
    #     from scrapers.livescorebet_scraper import LiveScoreBetScraper
    #     scrapers["livescorebet"] = LiveScoreBetScraper()
    #
    # if BOOKMAKERS.get("1win", {}).get("active"):
    #     from scrapers.onewin_scraper import OneWinScraper
    #     scrapers["1win"] = OneWinScraper()
    #
    # if BOOKMAKERS.get("ilotbet", {}).get("active"):
    #     from scrapers.ilotbet_scraper import IlotBetScraper
    #     scrapers["ilotbet"] = IlotBetScraper()
    #
    # if BOOKMAKERS.get("footballng", {}).get("active"):
    #     from scrapers.footballng_scraper import FootballNGScraper
    #     scrapers["footballng"] = FootballNGScraper()

    return scrapers


# ─── In-Memory Arb Store ─────────────────────────────────────────────────────

class ArbStore:
    """
    Thread-safe in-memory store for current arb opportunities.
    In production this would be backed by Redis for multi-process support.
    """

    def __init__(self):
        self._arbs: dict[str, ArbOpportunity] = {}  # arb_id → ArbOpportunity
        self._lock = asyncio.Lock()
        self.last_scan_at: Optional[datetime] = None
        self.scan_count: int = 0
        self.bookmaker_status: dict[str, dict] = {}

    async def update(self, new_arbs: list[ArbOpportunity]):
        async with self._lock:
            self._arbs = {a.arb_id: a for a in new_arbs}
            self.last_scan_at = datetime.utcnow()
            self.scan_count += 1

    async def get_all(
        self,
        market_type: Optional[str] = None,      # "direct" or "cross"
        is_live: Optional[bool] = None,
        min_profit_pct: float = 0.0,
        bookmaker_ids: Optional[list[str]] = None,
        sport: Optional[str] = None,
    ) -> list[dict]:
        """
        Return filtered + serialised arb opportunities.
        All filtering happens in-memory — fast enough for thousands of arbs.
        """
        async with self._lock:
            results = []
            for arb in self._arbs.values():
                # Profit filter
                if arb.profit_pct < min_profit_pct:
                    continue
                # Market type filter
                if market_type and arb.market_type != market_type:
                    continue
                # Live/prematch filter
                if is_live is not None and arb.is_live != is_live:
                    continue
                # Bookmaker filter
                if bookmaker_ids:
                    if (arb.leg_a.bookmaker_id not in bookmaker_ids and
                            arb.leg_b.bookmaker_id not in bookmaker_ids):
                        continue
                # Sport filter
                if sport and arb.event.sport != sport:
                    continue
                results.append(arb.to_dict())

            # Sort by profit desc
            results.sort(key=lambda x: x["arb"]["profit_pct"], reverse=True)
            return results

    async def get_stats(self) -> dict:
        async with self._lock:
            arbs = list(self._arbs.values())
            if not arbs:
                return {
                    "total_arbs": 0,
                    "avg_profit_pct": 0.0,
                    "best_profit_pct": 0.0,
                    "live_arbs": 0,
                    "prematch_arbs": 0,
                    "last_scan_at": None,
                    "scan_count": self.scan_count,
                    "bookmaker_status": self.bookmaker_status,
                }

            profits = [a.profit_pct for a in arbs]
            return {
                "total_arbs":       len(arbs),
                "avg_profit_pct":   round(sum(profits) / len(profits), 3),
                "best_profit_pct":  round(max(profits), 3),
                "live_arbs":        sum(1 for a in arbs if a.is_live),
                "prematch_arbs":    sum(1 for a in arbs if not a.is_live),
                "last_scan_at":     self.last_scan_at.isoformat() if self.last_scan_at else None,
                "scan_count":       self.scan_count,
                "bookmaker_status": self.bookmaker_status,
            }


# ─── Orchestrator ────────────────────────────────────────────────────────────

class Orchestrator:
    """
    Central controller. Runs the full scrape → match → detect → store pipeline.
    """

    def __init__(self):
        self.scrapers  = _load_scrapers()
        self.matcher   = EventMatcher(time_window_hours=4.0)
        self.arb_engine = ArbEngine()
        self.store     = ArbStore()
        self._running  = False
        self._semaphore = asyncio.Semaphore(SCRAPE_CONFIG["max_concurrent_scrapers"])

    async def _run_scraper(
        self,
        scraper_id: str,
        is_live: bool,
    ) -> ScrapeResult:
        """Run one scraper inside the concurrency semaphore."""
        scraper = self.scrapers[scraper_id]
        async with self._semaphore:
            try:
                if is_live:
                    return await scraper.fetch_live_odds()
                else:
                    return await scraper.fetch_prematch_odds()
            except Exception as e:
                logger.error(f"Scraper {scraper_id} crashed: {e}", exc_info=True)
                return ScrapeResult(
                    bookmaker_id=scraper_id,
                    success=False,
                    error=str(e),
                )

    async def _scrape_all(self, is_live: bool) -> list[ScrapeResult]:
        """Run all scrapers concurrently and collect results."""
        tasks = [
            self._run_scraper(sid, is_live)
            for sid in self.scrapers
        ]
        return await asyncio.gather(*tasks, return_exceptions=False)

    def _assign_legs_to_events(
        self, results: list[ScrapeResult]
    ) -> dict[str, tuple[MatchEvent, list[OddsLeg]]]:
        """
        For each OddsLeg in all scrape results, find or create its MatchEvent.
        Returns: { event_id → (MatchEvent, [OddsLeg, ...]) }
        """
        event_legs: dict[str, tuple[MatchEvent, list[OddsLeg]]] = {}

        total_legs = 0
        for result in results:
            if not result.success:
                continue
            for leg in result.legs:
                # Extract raw team info stored by the scraper
                home = leg.__dict__.get("_home_team", "")
                away = leg.__dict__.get("_away_team", "")
                league = leg.__dict__.get("_league", "")
                kick_off = leg.__dict__.get("_kick_off")

                if not home or not away:
                    continue

                event = self.matcher.get_or_create_event(
                    home_team=home,
                    away_team=away,
                    kick_off=kick_off,
                    league=league,
                    sport="football",
                    bookmaker_id=leg.bookmaker_id,
                    raw_name=f"{home} v {away}",
                )

                if event.event_id not in event_legs:
                    event_legs[event.event_id] = (event, [])
                event_legs[event.event_id][1].append(leg)
                total_legs += 1

        logger.info(
            f"Assigned {total_legs} legs across {len(event_legs)} events "
            f"({self.matcher.event_count} total known events)"
        )
        return event_legs

    async def run_cycle(self, is_live: bool = False):
        """
        One full scrape-match-detect cycle.
        Called by the scheduler on a timer.
        """
        cycle_type = "LIVE" if is_live else "PRE-MATCH"
        logger.info(f"=== Starting {cycle_type} cycle ===")
        t0 = time.time()

        # 1. Scrape all bookmakers
        results = await self._scrape_all(is_live)

        # Update bookmaker status in store
        for r in results:
            self.store.bookmaker_status[r.bookmaker_id] = {
                "success":      r.success,
                "legs_scraped": len(r.legs),
                "error":        r.error,
                "scraped_at":   r.scraped_at.isoformat(),
                "duration_ms":  r.duration_ms,
            }

        # 2. Match events across bookmakers
        event_legs = self._assign_legs_to_events(results)

        # 3. Scan for arbs
        all_arbs = self.arb_engine.scan_all_events(event_legs)

        # 4. Store results
        await self.store.update(all_arbs)

        # 5. Prune old events periodically
        self.matcher.prune_old_events(max_age_hours=6.0)

        elapsed = time.time() - t0
        logger.info(
            f"=== {cycle_type} cycle done: {len(all_arbs)} arbs found "
            f"in {elapsed:.2f}s ==="
        )

    async def start_loop(self):
        """
        Main scheduling loop. Runs pre-match and live cycles on separate intervals.
        """
        self._running = True
        prematch_interval = SCRAPE_CONFIG["prematch_interval_seconds"]
        live_interval     = SCRAPE_CONFIG["live_interval_seconds"]

        logger.info(
            f"Orchestrator started. "
            f"Pre-match every {prematch_interval}s, Live every {live_interval}s. "
            f"Scrapers: {list(self.scrapers.keys())}"
        )

        # Track when we last ran each type
        last_prematch = 0.0
        last_live     = 0.0

        while self._running:
            now = time.time()
            tasks = []

            if now - last_prematch >= prematch_interval:
                tasks.append(self.run_cycle(is_live=False))
                last_prematch = now

            if now - last_live >= live_interval:
                tasks.append(self.run_cycle(is_live=True))
                last_live = now

            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

            await asyncio.sleep(1)  # Tick every second

    def stop(self):
        self._running = False
        logger.info("Orchestrator stopped.")
