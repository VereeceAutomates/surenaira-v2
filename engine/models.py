"""
SureNaira — Data Models
Typed dataclasses for every object that flows through the system.
"""

from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime
import uuid


# ─── Raw Odds from a single bookmaker ───────────────────────────────────────

@dataclass
class OddsLeg:
    """
    A single outcome with its price from one bookmaker.
    e.g. "Home Win DNB @ 2.10 on SportyBet"
    """
    bookmaker_id: str          # e.g. "sportybet"
    bookmaker_name: str        # e.g. "SportyBet"
    market_type: str           # e.g. "asian_handicap", "1x2", "over_under", "btts"
    outcome_label: str         # e.g. "Home -0.5 AH", "Over 2.5", "BTTS Yes"
    outcome_key: str           # e.g. "home_ah", "over", "btts_yes"
    odds: float                # Decimal odds e.g. 2.10
    line: Optional[float]      # For AH/OU: the line value e.g. 2.5, -0.5
    handicap_label: Optional[str] = None  # For EH: e.g. "-1:0", "0:-1"
    event_url: str = ""        # Direct deep link to this market on the bookie site
    scraped_at: datetime = field(default_factory=datetime.utcnow)
    is_live: bool = False


# ─── A sporting event (normalised across bookmakers) ────────────────────────

@dataclass
class MatchEvent:
    """
    A single match after event-matching / normalisation.
    This is the anchor that legs from different bookmakers hang off.
    """
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    home_team: str = ""
    away_team: str = ""
    league: str = ""
    sport: str = "football"
    kick_off: Optional[datetime] = None
    is_live: bool = False
    minute: Optional[int] = None    # If live: current match minute
    score_home: Optional[int] = None
    score_away: Optional[int] = None
    # Raw name variants seen per bookmaker (used for fuzzy matching)
    name_variants: dict = field(default_factory=dict)

    @property
    def display_name(self) -> str:
        return f"{self.home_team} vs {self.away_team}"

    @property
    def canonical_name(self) -> str:
        """Lowercase normalised name for matching."""
        return f"{self.home_team.lower().strip()} v {self.away_team.lower().strip()}"


# ─── An arbitrage opportunity ────────────────────────────────────────────────

@dataclass
class ArbOpportunity:
    """
    A confirmed 2-outcome arbitrage opportunity.
    Contains both legs, the profit calculation, and stake split.
    """
    arb_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    event: MatchEvent = field(default_factory=MatchEvent)

    leg_a: Optional[OddsLeg] = None
    leg_b: Optional[OddsLeg] = None

    # Derived fields (computed by the arb engine)
    implied_prob_sum: float = 0.0   # < 1.0 = arb exists
    profit_pct: float = 0.0         # e.g. 3.5 means 3.5% guaranteed profit
    market_type: str = ""           # "direct" or "cross"
    market_label: str = ""          # e.g. "Over/Under", "Home (-1:0) HDP × Away Win"

    detected_at: datetime = field(default_factory=datetime.utcnow)
    is_live: bool = False

    # Age in seconds (updated in real-time)
    @property
    def age_seconds(self) -> float:
        return (datetime.utcnow() - self.detected_at).total_seconds()

    def stakes_for_budget(self, budget: float) -> dict:
        """
        Given a total NGN budget, calculate optimal stake split.
        Returns stake_a, stake_b, guaranteed_return, guaranteed_profit.
        """
        if not self.leg_a or not self.leg_b:
            return {}
        implied = (1 / self.leg_a.odds) + (1 / self.leg_b.odds)
        if implied >= 1.0:
            return {}
        stake_a = budget * (1 / self.leg_a.odds) / implied
        stake_b = budget * (1 / self.leg_b.odds) / implied
        guaranteed_return = stake_a * self.leg_a.odds
        return {
            "budget":            round(budget, 2),
            "stake_a":           round(stake_a, 2),
            "stake_b":           round(stake_b, 2),
            "guaranteed_return": round(guaranteed_return, 2),
            "guaranteed_profit": round(guaranteed_return - budget, 2),
            "profit_pct":        round(self.profit_pct, 4),
        }

    def to_dict(self) -> dict:
        """Serialise to JSON-safe dict for the API."""
        return {
            "arb_id":        self.arb_id,
            "event": {
                "event_id":    self.event.event_id,
                "home_team":   self.event.home_team,
                "away_team":   self.event.away_team,
                "league":      self.event.league,
                "sport":       self.event.sport,
                "kick_off":    self.event.kick_off.isoformat() if self.event.kick_off else None,
                "is_live":     self.event.is_live,
                "minute":      self.event.minute,
                "score":       f"{self.event.score_home}-{self.event.score_away}" if self.event.is_live else None,
            },
            "leg_a": {
                "bookmaker":       self.leg_a.bookmaker_name,
                "bookmaker_id":    self.leg_a.bookmaker_id,
                "market":          self.leg_a.market_type,
                "outcome":         self.leg_a.outcome_label,
                "odds":            self.leg_a.odds,
                "line":            self.leg_a.line,
                "handicap":        self.leg_a.handicap_label,
                "url":             self.leg_a.event_url,
            },
            "leg_b": {
                "bookmaker":       self.leg_b.bookmaker_name,
                "bookmaker_id":    self.leg_b.bookmaker_id,
                "market":          self.leg_b.market_type,
                "outcome":         self.leg_b.outcome_label,
                "odds":            self.leg_b.odds,
                "line":            self.leg_b.line,
                "handicap":        self.leg_b.handicap_label,
                "url":             self.leg_b.event_url,
            },
            "arb": {
                "profit_pct":       round(self.profit_pct, 4),
                "implied_prob_sum": round(self.implied_prob_sum, 6),
                "market_type":      self.market_type,
                "market_label":     self.market_label,
                "is_live":          self.is_live,
                "age_seconds":      round(self.age_seconds, 1),
                "detected_at":      self.detected_at.isoformat(),
            },
        }


# ─── Scraper result wrapper ──────────────────────────────────────────────────

@dataclass
class ScrapeResult:
    """Returned by every scraper — success or failure."""
    bookmaker_id: str
    success: bool
    legs: list[OddsLeg] = field(default_factory=list)
    error: Optional[str] = None
    scraped_at: datetime = field(default_factory=datetime.utcnow)
    duration_ms: int = 0
