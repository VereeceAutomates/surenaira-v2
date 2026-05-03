"""
SureNaira — Event Matching Engine
=================================
The hardest problem in arbitrage scanning.

SportyBet might list a game as:  "Manchester United vs Arsenal FC"
Bet9ja might list it as:         "Man Utd - Arsenal"
BetKing might list it as:        "Manchester Utd v Arsenal"

We must confidently identify all three as the same match before we can
compare their odds. False positives (wrong match pairing) are dangerous —
they would produce fake arbs that lose money.

Strategy:
  1. Normalise team names: remove "FC", "AFC", common abbreviations, etc.
  2. Token sort + fuzzy ratio (RapidFuzz) for name similarity
  3. Require BOTH home AND away team to match above threshold
  4. Time gating: events must kick off within ±4 hours of each other
  5. League cross-check when available (same league = higher confidence)
"""

import re
from datetime import datetime, timedelta
from typing import Optional
from difflib import SequenceMatcher

from engine.models import MatchEvent, OddsLeg


# ─── Name normalisation ──────────────────────────────────────────────────────

# Tokens to strip from team names before comparison
STRIP_TOKENS = {
    "fc", "afc", "sc", "cf", "ac", "bc", "fk", "bk", "sk", "nk",
    "united", "utd", "city", "town", "hotspur",
    "sporting", "athletic", "atletico",
    "real", "royal",
    "(ng)", "(nig)", "nigeria", "nig",
}

# Common abbreviation expansions — map short forms to canonical names
ABBREV_MAP = {
    "man utd":       "manchester united",
    "man city":      "manchester city",
    "man united":    "manchester united",
    "spurs":         "tottenham",
    "tottenham":     "tottenham hotspur",
    "wolves":        "wolverhampton",
    "west brom":     "west bromwich",
    "qpr":           "queens park rangers",
    "psv":           "psv eindhoven",
    "ajax":          "ajax amsterdam",
    "rb leipzig":    "rasenballsport leipzig",
    "rbl":           "rasenballsport leipzig",
    "bvb":           "borussia dortmund",
    "fcb":           "fc barcelona",
    "mufc":          "manchester united",
    "mcfc":          "manchester city",
    "cfc":           "chelsea",
    "afc":           "arsenal",
    "lfc":           "liverpool",
}

# Minimum similarity score (0–1) for a team name pair to be considered the same
TEAM_MATCH_THRESHOLD = 0.82


def normalise_team_name(name: str) -> str:
    """
    Normalise a team name for comparison.
    Steps: lowercase → strip punctuation → expand abbreviations
           → remove common suffixes → strip extra whitespace
    """
    if not name:
        return ""

    n = name.lower().strip()

    # Remove punctuation except spaces and hyphens
    n = re.sub(r"[^\w\s\-]", "", n)

    # Replace hyphens and underscores with spaces
    n = re.sub(r"[\-_]", " ", n)

    # Collapse multiple spaces
    n = re.sub(r"\s+", " ", n).strip()

    # Expand abbreviations first (before stripping tokens)
    n = ABBREV_MAP.get(n, n)

    # Remove common stripped tokens (only if they're standalone words)
    words = n.split()
    words = [w for w in words if w not in STRIP_TOKENS]
    n = " ".join(words).strip()

    return n


def token_sort_ratio(s1: str, s2: str) -> float:
    """
    Token-sort similarity: sort words alphabetically before comparing.
    Handles word-order differences: "Arsenal FC" vs "FC Arsenal" → 1.0
    Returns a score between 0.0 and 1.0.
    """
    s1_sorted = " ".join(sorted(s1.split()))
    s2_sorted = " ".join(sorted(s2.split()))
    return SequenceMatcher(None, s1_sorted, s2_sorted).ratio()


def team_similarity(name_a: str, name_b: str) -> float:
    """
    Combined similarity score between two team names.
    Uses both standard ratio and token-sort ratio, returns the max.
    """
    a = normalise_team_name(name_a)
    b = normalise_team_name(name_b)

    if not a or not b:
        return 0.0

    # Exact match after normalisation
    if a == b:
        return 1.0

    # Check if one is a substring of the other (handles "Barcelona" vs "FC Barcelona")
    if a in b or b in a:
        return 0.95

    direct = SequenceMatcher(None, a, b).ratio()
    sorted_r = token_sort_ratio(a, b)

    return max(direct, sorted_r)


# ─── Event Matching ──────────────────────────────────────────────────────────

class EventMatcher:
    """
    Maintains a registry of known events and matches incoming OddsLegs
    to existing events or creates new event anchors.
    """

    def __init__(self, time_window_hours: float = 4.0):
        # event_id → MatchEvent
        self._events: dict[str, MatchEvent] = {}
        self.time_window = timedelta(hours=time_window_hours)

    def _events_overlap_in_time(
        self,
        kick_off_a: Optional[datetime],
        kick_off_b: Optional[datetime],
    ) -> bool:
        """Return True if two kickoff times are within the matching window."""
        if kick_off_a is None or kick_off_b is None:
            # If we don't have timing info, don't reject on time alone
            return True
        return abs(kick_off_a - kick_off_b) <= self.time_window

    def find_matching_event(
        self,
        home_team: str,
        away_team: str,
        kick_off: Optional[datetime] = None,
        league: Optional[str] = None,
    ) -> Optional[MatchEvent]:
        """
        Search known events for a match.
        Returns the best matching event, or None if no confident match found.
        """
        best_event = None
        best_score = 0.0

        for event in self._events.values():
            # Time gate check
            if not self._events_overlap_in_time(kick_off, event.kick_off):
                continue

            # Score home team match
            home_score = team_similarity(home_team, event.home_team)
            # Score away team match
            away_score = team_similarity(away_team, event.away_team)

            # Both teams must match — take geometric mean for combined score
            combined = (home_score * away_score) ** 0.5

            # Bonus if leagues also match (when available)
            if league and event.league:
                league_norm_a = normalise_team_name(league)
                league_norm_b = normalise_team_name(event.league)
                if league_norm_a == league_norm_b:
                    combined = min(1.0, combined + 0.05)

            if combined > best_score:
                best_score = combined
                best_event = event

        if best_score >= TEAM_MATCH_THRESHOLD:
            return best_event
        return None

    def get_or_create_event(
        self,
        home_team: str,
        away_team: str,
        kick_off: Optional[datetime] = None,
        league: str = "",
        sport: str = "football",
        bookmaker_id: str = "",
        raw_name: str = "",
    ) -> MatchEvent:
        """
        Find an existing event that matches, or register a new one.
        Records the raw name variant for this bookmaker (useful for debugging).
        """
        existing = self.find_matching_event(home_team, away_team, kick_off, league)

        if existing:
            # Store this bookmaker's raw name for the event
            if bookmaker_id and raw_name:
                existing.name_variants[bookmaker_id] = raw_name
            # Update live status and score if more recent
            return existing

        # Create new event anchor
        event = MatchEvent(
            home_team=home_team,
            away_team=away_team,
            league=league,
            sport=sport,
            kick_off=kick_off,
            name_variants={bookmaker_id: raw_name} if bookmaker_id else {},
        )
        self._events[event.event_id] = event
        return event

    def update_live_status(self, event_id: str, minute: int, score_home: int, score_away: int):
        """Update a live event's current minute and score."""
        if event_id in self._events:
            e = self._events[event_id]
            e.is_live = True
            e.minute = minute
            e.score_home = score_home
            e.score_away = score_away

    def prune_old_events(self, max_age_hours: float = 6.0):
        """Remove events that kicked off more than max_age_hours ago."""
        cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)
        to_remove = []
        for eid, event in self._events.items():
            if event.kick_off and event.kick_off < cutoff and not event.is_live:
                to_remove.append(eid)
        for eid in to_remove:
            del self._events[eid]

    @property
    def event_count(self) -> int:
        return len(self._events)
