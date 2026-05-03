"""
SureNaira — Base Scraper
========================
Every bookmaker scraper inherits from BaseScraper.
Provides shared: HTTP session, retry logic, rate limiting, user-agent rotation,
outcome key mapping, and a standard interface.

Each bookmaker subclass only needs to implement:
  - fetch_prematch_odds() → list[OddsLeg]
  - fetch_live_odds()     → list[OddsLeg]
  - parse_event_data()    → (home_team, away_team, kick_off, league)
  - parse_leg_data()      → OddsLeg
"""

import asyncio
import logging
import time
import random
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

import aiohttp

from engine.models import OddsLeg, ScrapeResult
from config.settings import SCRAPE_CONFIG, BOOKMAKERS

logger = logging.getLogger("scraper")

# ─── User-agent pool for rotation ───────────────────────────────────────────

USER_AGENTS = [
    # Chrome on Android (most common Nigerian mobile browser)
    "Mozilla/5.0 (Linux; Android 12; Pixel 6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; Samsung Galaxy S23) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 11; Tecno Camon 19) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 12; Infinix Note 30) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    # Chrome on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    # Firefox
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0",
]


# ─── Outcome key normalisation ───────────────────────────────────────────────
# Each bookmaker uses different strings for outcomes.
# We normalise everything to our internal outcome_key system.

def normalise_outcome_key(
    raw_outcome: str,
    market_type: str,
    line: Optional[float] = None,
    handicap: Optional[str] = None,
) -> str:
    """
    Convert a bookmaker's raw outcome string to our internal outcome_key.

    Examples:
      "1" in 1X2          → "home_1x2"
      "2" in 1X2          → "away_1x2"
      "Over" in OU 2.5    → "over_2_5"
      "Under" in OU 2.5   → "under_2_5"
      "1" in AH -0.5      → "home_ah_minus0_5"
      "W1" in EH -1:0     → "home_eh_minus1_0"
      "Yes" in BTTS       → "btts_yes"
    """
    raw = raw_outcome.strip().lower()
    mtype = market_type.lower()

    # ─ 1X2 / Home-Away ─────────────────────────────────────────────────────
    if mtype in ("1x2", "match_result", "home_away", "moneyline"):
        if raw in ("1", "home", "w1", "home win", "h"):
            return "home_1x2"
        if raw in ("2", "away", "w2", "away win", "a"):
            return "away_1x2"
        if raw in ("x", "draw", "d", "tie"):
            return "draw_1x2"  # We don't use draws but we register them

    # ─ Draw No Bet ──────────────────────────────────────────────────────────
    if mtype in ("dnb", "draw_no_bet"):
        if raw in ("1", "home", "home win"):
            return "home_dnb"
        if raw in ("2", "away", "away win"):
            return "away_dnb"

    # ─ Over/Under ───────────────────────────────────────────────────────────
    if mtype in ("over_under", "totals", "goals", "ou"):
        line_str = str(line).replace(".", "_").replace("-", "minus") if line is not None else "x"
        if raw in ("over", "o", "+"):
            return f"over_{line_str}"
        if raw in ("under", "u", "-"):
            return f"under_{line_str}"

    # ─ Asian Handicap ───────────────────────────────────────────────────────
    if mtype in ("asian_handicap", "ah"):
        line_str = ""
        if line is not None:
            abs_line = abs(line)
            sign = "minus" if line < 0 else "plus" if line > 0 else ""
            line_str = f"_{sign}{str(abs_line).replace('.', '_')}" if sign else "_0"
        if raw in ("1", "home", "h"):
            return f"home_ah{line_str}"
        if raw in ("2", "away", "a"):
            return f"away_ah{line_str}"

    # ─ European Handicap ────────────────────────────────────────────────────
    if mtype in ("european_handicap", "eh", "handicap"):
        # handicap string like "-1:0" or "0:-1"
        hdp = (handicap or "").replace(":", "_").replace("-", "minus").replace("+", "plus")
        if raw in ("1", "home", "w1"):
            return f"home_eh_{hdp}"
        if raw in ("2", "away", "w2"):
            return f"away_eh_{hdp}"
        if raw in ("x", "draw"):
            return f"draw_eh_{hdp}"

    # ─ BTTS ─────────────────────────────────────────────────────────────────
    if mtype in ("btts", "both_teams_to_score", "gg_ng"):
        if raw in ("yes", "gg", "1", "both"):
            return "btts_yes"
        if raw in ("no", "ng", "0"):
            return "btts_no"

    # ─ Double Chance ────────────────────────────────────────────────────────
    if mtype in ("double_chance", "dc"):
        if raw in ("1x", "home or draw"):
            return "double_chance_1x"
        if raw in ("x2", "draw or away"):
            return "double_chance_x2"
        if raw in ("12", "home or away"):
            return "double_chance_12"

    # Unknown — return raw slugified
    return raw.replace(" ", "_").replace("/", "_")


# ─── Base Scraper ────────────────────────────────────────────────────────────

class BaseScraper(ABC):
    """
    Abstract base class for all bookmaker scrapers.
    """

    def __init__(self, bookmaker_id: str):
        self.bookmaker_id = bookmaker_id
        cfg = BOOKMAKERS.get(bookmaker_id, {})
        self.bookmaker_name = cfg.get("name", bookmaker_id)
        self.api_base       = cfg.get("api_base", "")
        self.endpoints      = cfg.get("endpoints", {})
        self.base_headers   = cfg.get("headers", {})
        self.timeout        = SCRAPE_CONFIG["request_timeout_seconds"]
        self.retry_attempts = SCRAPE_CONFIG["retry_attempts"]
        self.retry_delay    = SCRAPE_CONFIG["retry_delay_seconds"]
        self._session: Optional[aiohttp.ClientSession] = None

    def _get_headers(self) -> dict:
        """Return headers, optionally rotating the User-Agent."""
        headers = dict(self.base_headers)
        if SCRAPE_CONFIG.get("rotate_user_agents"):
            headers["User-Agent"] = random.choice(USER_AGENTS)
        return headers

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.timeout)
            self._session = aiohttp.ClientSession(
                headers=self._get_headers(),
                timeout=timeout,
            )
        return self._session

    async def _get(self, url: str, params: dict = None) -> Optional[dict]:
        """
        Make a GET request with retry logic.
        Returns parsed JSON on success, None on failure.
        """
        session = await self._get_session()
        for attempt in range(1, self.retry_attempts + 1):
            try:
                async with session.get(url, params=params) as resp:
                    if resp.status == 200:
                        try:
                            return await resp.json(content_type=None)
                        except Exception:
                            text = await resp.text()
                            logger.warning(
                                f"{self.bookmaker_name}: non-JSON response "
                                f"({len(text)} chars)"
                            )
                            return None
                    elif resp.status == 429:
                        wait = self.retry_delay * attempt
                        logger.warning(
                            f"{self.bookmaker_name}: rate limited (429), "
                            f"waiting {wait}s"
                        )
                        await asyncio.sleep(wait)
                    elif resp.status in (403, 401):
                        logger.error(
                            f"{self.bookmaker_name}: access denied ({resp.status}). "
                            f"May need updated cookies/headers."
                        )
                        return None
                    else:
                        logger.warning(
                            f"{self.bookmaker_name}: HTTP {resp.status} for {url}"
                        )
                        await asyncio.sleep(self.retry_delay)
            except aiohttp.ClientConnectorError as e:
                logger.error(f"{self.bookmaker_name}: connection error: {e}")
                await asyncio.sleep(self.retry_delay * attempt)
            except asyncio.TimeoutError:
                logger.warning(
                    f"{self.bookmaker_name}: timeout on attempt {attempt}/{self.retry_attempts}"
                )
                await asyncio.sleep(self.retry_delay)

        return None

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    # ─── Interface that subclasses must implement ────────────────────────────

    @abstractmethod
    async def fetch_prematch_odds(self) -> ScrapeResult:
        """
        Fetch all pre-match odds from this bookmaker.
        Must return a ScrapeResult with a list of OddsLeg objects.
        """
        ...

    @abstractmethod
    async def fetch_live_odds(self) -> ScrapeResult:
        """
        Fetch all live (in-play) odds from this bookmaker.
        Must return a ScrapeResult with a list of OddsLeg objects.
        """
        ...

    # ─── Helper: build an OddsLeg ────────────────────────────────────────────

    def build_leg(
        self,
        home_team: str,
        away_team: str,
        league: str,
        market_type: str,
        raw_outcome: str,
        odds: float,
        line: Optional[float] = None,
        handicap_label: Optional[str] = None,
        event_url: str = "",
        is_live: bool = False,
        kick_off: Optional[datetime] = None,
    ) -> OddsLeg:
        """
        Convenience method to construct a normalised OddsLeg.
        Subclasses should call this rather than constructing OddsLeg directly.
        """
        outcome_key = normalise_outcome_key(
            raw_outcome, market_type, line, handicap_label
        )

        # Human-readable outcome label
        if line is not None:
            outcome_label = f"{raw_outcome.title()} {line}"
        elif handicap_label:
            outcome_label = f"{raw_outcome.title()} ({handicap_label})"
        else:
            outcome_label = raw_outcome.title()

        return OddsLeg(
            bookmaker_id=self.bookmaker_id,
            bookmaker_name=self.bookmaker_name,
            market_type=market_type,
            outcome_label=outcome_label,
            outcome_key=outcome_key,
            odds=odds,
            line=line,
            handicap_label=handicap_label,
            event_url=event_url,
            is_live=is_live,
            scraped_at=datetime.utcnow(),
        )
