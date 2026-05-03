"""
SureNaira — Arb Detection Engine
==================================
The mathematical core of the system.

Given a set of OddsLegs all anchored to the same MatchEvent,
this engine finds all valid 2-outcome arbitrage opportunities.

It handles:
  1. Direct arbs — same market type, same line, different bookmakers
     e.g. Over 2.5 @ 2.10 (SportyBet) vs Under 2.5 @ 2.05 (Bet9ja)

  2. Cross-market arbs — different market types from any two bookmakers
     e.g. Home (-1:0) HDP @ 1.90 (SportyBet) vs Away Win @ 2.20 (BetKing)
     These are exhaustive: both legs together cover 100% of outcomes.

The arb formula:
  implied_sum = (1/oddsA) + (1/oddsB)
  If implied_sum < 1.0 → arb exists
  profit_pct  = (1 - implied_sum) / implied_sum * 100

Stake split (equal-return method):
  stake_a = budget × (1/oddsA) / implied_sum
  stake_b = budget × (1/oddsB) / implied_sum
  Both legs return the same amount regardless of which wins.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional
from itertools import combinations

from engine.models import OddsLeg, MatchEvent, ArbOpportunity
from config.settings import ARB_CONFIG, MARKETS

logger = logging.getLogger("arb_engine")


# ─── Cross-market pair registry ──────────────────────────────────────────────
# Maps (outcome_key_A, outcome_key_B) → market_label
# These are pairs where leg_A + leg_B together exhaust ALL possible outcomes.
# Order doesn't matter — we check both orderings.

EXHAUSTIVE_CROSS_PAIRS: list[tuple[str, str, str]] = [
    # (outcome_key_A, outcome_key_B, label)

    # Home (-1:0) European Handicap covers: Home wins by 2+, OR home wins by 1, OR draw
    # Away Win outright covers: Away wins
    # Together: all 4 outcomes covered ✓
    ("home_eh_minus1_0",  "away_1x2",       "Home (-1:0) HDP × Away Win"),
    ("home_eh_minus2_0",  "away_1x2",       "Home (-2:0) HDP × Away Win"),

    # Away (-1:0) European Handicap covers: Away wins by 2+, OR away wins by 1, OR draw
    # Home Win outright covers: Home wins
    # Together: all 4 outcomes covered ✓
    ("away_eh_minus1_0",  "home_1x2",       "Away (-1:0) HDP × Home Win"),
    ("away_eh_minus2_0",  "home_1x2",       "Away (-2:0) HDP × Home Win"),

    # Home (+1:0) EH covers: Home wins OR draws (home gets a virtual goal)
    # Away Win covers: Away wins
    ("home_eh_plus1_0",   "away_1x2",       "Home (+1:0) HDP × Away Win"),

    # Away (+1:0) EH covers: Away wins OR draws
    # Home Win covers: Home wins
    ("away_eh_plus1_0",   "home_1x2",       "Away (+1:0) HDP × Home Win"),

    # Home AH -0.5 covers: Home wins (must win, push impossible on -0.5)
    # Double Chance X2 covers: Draw or Away wins
    # Together: all outcomes ✓
    ("home_ah_minus0_5",  "double_chance_x2",  "Home AH -0.5 × Double Chance X2"),

    # Away AH -0.5 covers: Away wins
    # Double Chance 1X covers: Home wins or Draw
    ("away_ah_minus0_5",  "double_chance_1x",  "Away AH -0.5 × Double Chance 1X"),

    # BTTS Yes/No — direct pair but often priced across different bookmakers
    ("btts_yes",          "btts_no",           "BTTS Yes × No"),

    # Home DNB covers: Home wins (draw = refund, treated as no bet)
    # Away DNB covers: Away wins (draw = refund)
    # Note: this is NOT a true exhaustive pair because the draw refunds both.
    # We handle this as a separate "refund" market type — excluded here.

    # Over/Under across bookmakers (same line)
    ("over_0_5",   "under_0_5",   "Over/Under 0.5"),
    ("over_1_5",   "under_1_5",   "Over/Under 1.5"),
    ("over_2_5",   "under_2_5",   "Over/Under 2.5"),
    ("over_3_5",   "under_3_5",   "Over/Under 3.5"),
    ("over_4_5",   "under_4_5",   "Over/Under 4.5"),
]

# Build a lookup dict for O(1) access: frozenset({key_a, key_b}) → label
CROSS_PAIR_LOOKUP: dict[frozenset, str] = {}
for key_a, key_b, lbl in EXHAUSTIVE_CROSS_PAIRS:
    CROSS_PAIR_LOOKUP[frozenset({key_a, key_b})] = lbl


# ─── Direct market grouping keys ─────────────────────────────────────────────
# For direct arbs (same market, same line, different bookmakers),
# we need to group legs by (market_type, line) and then compare outcomes.

DIRECT_MARKET_OUTCOME_PAIRS: dict[str, tuple[str, str]] = {
    # market_type → (outcome_key_a, outcome_key_b)
    # These are the two sides that together cover 100% of outcomes
    "over_under":       ("over",      "under"),
    "asian_handicap":   ("home_ah",   "away_ah"),      # same line, opposite sides
    "btts":             ("btts_yes",  "btts_no"),
    "dnb":              ("home_dnb",  "away_dnb"),     # draw no bet
    "1x2_hw_aw":        ("home_1x2",  "away_1x2"),    # must be used with DNB/AH context
}


# ─── The Engine ──────────────────────────────────────────────────────────────

class ArbEngine:
    """
    Processes a collection of OddsLegs for a single MatchEvent and
    returns all detected ArbOpportunity objects.
    """

    def __init__(self):
        self.min_profit = ARB_CONFIG["min_profit_pct"]
        self.max_profit = ARB_CONFIG["max_profit_pct"]
        self.min_odds   = ARB_CONFIG["min_odds"]
        self.max_odds   = ARB_CONFIG["max_odds"]
        self.max_age_s  = ARB_CONFIG["max_odds_age_seconds"]
        self.max_live_s = ARB_CONFIG["max_live_odds_age_seconds"]

    def _is_leg_valid(self, leg: OddsLeg) -> bool:
        """Basic sanity checks on a single leg."""
        if not (self.min_odds <= leg.odds <= self.max_odds):
            return False
        # Reject stale odds
        age = (datetime.utcnow() - leg.scraped_at).total_seconds()
        limit = self.max_live_s if leg.is_live else self.max_age_s
        if age > limit:
            return False
        return True

    def _compute_arb(self, leg_a: OddsLeg, leg_b: OddsLeg) -> Optional[float]:
        """
        Returns profit_pct if an arb exists between two legs, else None.
        """
        implied = (1 / leg_a.odds) + (1 / leg_b.odds)
        if implied >= 1.0:
            return None
        profit_pct = ((1 - implied) / implied) * 100
        if not (self.min_profit <= profit_pct <= self.max_profit):
            return None
        return profit_pct

    def _make_arb(
        self,
        event: MatchEvent,
        leg_a: OddsLeg,
        leg_b: OddsLeg,
        market_type: str,
        market_label: str,
        profit_pct: float,
    ) -> ArbOpportunity:
        implied = (1 / leg_a.odds) + (1 / leg_b.odds)
        return ArbOpportunity(
            event=event,
            leg_a=leg_a,
            leg_b=leg_b,
            implied_prob_sum=implied,
            profit_pct=profit_pct,
            market_type=market_type,
            market_label=market_label,
            is_live=event.is_live,
        )

    # ── 1. Direct arb detection ──────────────────────────────────────────────

    def _find_direct_arbs(
        self,
        event: MatchEvent,
        legs: list[OddsLeg],
    ) -> list[ArbOpportunity]:
        """
        Find arbs within the same market type (e.g. Over 2.5 vs Under 2.5),
        where the two legs come from DIFFERENT bookmakers.

        Groups legs by (market_type, line), then checks all cross-bookmaker
        pairs of opposing outcomes.
        """
        found = []

        # Group by (market_type, line_key)
        groups: dict[tuple, list[OddsLeg]] = {}
        for leg in legs:
            line_key = str(leg.line) if leg.line is not None else "none"
            key = (leg.market_type, line_key)
            groups.setdefault(key, []).append(leg)

        for (market_type, _), group_legs in groups.items():
            if market_type not in DIRECT_MARKET_OUTCOME_PAIRS:
                continue

            outcome_a_key, outcome_b_key = DIRECT_MARKET_OUTCOME_PAIRS[market_type]
            market_def = next(
                (v for v in MARKETS.values() if v.get("type") == "direct"),
                {}
            )
            label = market_def.get("label", market_type.replace("_", " ").title())

            # Separate legs by outcome key
            legs_a = [l for l in group_legs if l.outcome_key == outcome_a_key]
            legs_b = [l for l in group_legs if l.outcome_key == outcome_b_key]

            # Check every leg_A × leg_B cross-bookmaker combination
            for la in legs_a:
                for lb in legs_b:
                    # Must be different bookmakers
                    if la.bookmaker_id == lb.bookmaker_id:
                        continue
                    if not self._is_leg_valid(la) or not self._is_leg_valid(lb):
                        continue

                    profit = self._compute_arb(la, lb)
                    if profit is not None:
                        found.append(self._make_arb(
                            event, la, lb, "direct", label, profit
                        ))
                        logger.debug(
                            f"Direct arb: {event.display_name} | {label} | "
                            f"{la.bookmaker_name} {la.odds} vs {lb.bookmaker_name} {lb.odds} | "
                            f"+{profit:.2f}%"
                        )

        return found

    # ── 2. Cross-market arb detection ────────────────────────────────────────

    def _find_cross_arbs(
        self,
        event: MatchEvent,
        legs: list[OddsLeg],
    ) -> list[ArbOpportunity]:
        """
        Find arbs ACROSS different market types.
        Uses the EXHAUSTIVE_CROSS_PAIRS registry to know which pairs are valid.

        e.g. Home (-1:0) EH from SportyBet × Away Win 1X2 from Bet9ja
        """
        found = []

        # Index legs by outcome_key for O(1) lookup
        by_outcome: dict[str, list[OddsLeg]] = {}
        for leg in legs:
            by_outcome.setdefault(leg.outcome_key, []).append(leg)

        # Check every registered cross pair
        for (key_a, key_b), label in CROSS_PAIR_LOOKUP.items():
            legs_a = by_outcome.get(key_a, [])
            legs_b = by_outcome.get(key_b, [])

            for la in legs_a:
                for lb in legs_b:
                    # Cross-market arbs can come from the SAME bookmaker
                    # (same bookie offering both markets with a pricing gap)
                    # but the most common and reliable arbs are cross-bookmaker.
                    if not self._is_leg_valid(la) or not self._is_leg_valid(lb):
                        continue

                    profit = self._compute_arb(la, lb)
                    if profit is not None:
                        found.append(self._make_arb(
                            event, la, lb, "cross", label, profit
                        ))
                        logger.debug(
                            f"Cross arb: {event.display_name} | {label} | "
                            f"{la.bookmaker_name}({la.outcome_key}) {la.odds} vs "
                            f"{lb.bookmaker_name}({lb.outcome_key}) {lb.odds} | "
                            f"+{profit:.2f}%"
                        )

        return found

    # ── 3. Main entry point ───────────────────────────────────────────────────

    def scan_event(
        self,
        event: MatchEvent,
        legs: list[OddsLeg],
    ) -> list[ArbOpportunity]:
        """
        Full scan of all legs for one event.
        Returns all valid arb opportunities sorted by profit % descending.
        """
        valid_legs = [l for l in legs if self._is_leg_valid(l)]

        if len(valid_legs) < 2:
            return []

        arbs = []
        arbs.extend(self._find_direct_arbs(event, valid_legs))
        arbs.extend(self._find_cross_arbs(event, valid_legs))

        # Sort by profit descending
        arbs.sort(key=lambda a: a.profit_pct, reverse=True)

        # Deduplicate: same bookmaker pair + same outcomes = keep highest profit
        seen = set()
        unique = []
        for arb in arbs:
            dedup_key = frozenset({
                (arb.leg_a.bookmaker_id, arb.leg_a.outcome_key),
                (arb.leg_b.bookmaker_id, arb.leg_b.outcome_key),
            })
            if dedup_key not in seen:
                seen.add(dedup_key)
                unique.append(arb)

        return unique

    def scan_all_events(
        self,
        event_legs_map: dict[str, tuple[MatchEvent, list[OddsLeg]]],
    ) -> list[ArbOpportunity]:
        """
        Scan multiple events at once.
        event_legs_map: { event_id → (MatchEvent, [OddsLeg, ...]) }
        Returns all arbs across all events, sorted by profit desc.
        """
        all_arbs = []
        for event_id, (event, legs) in event_legs_map.items():
            event_arbs = self.scan_event(event, legs)
            all_arbs.extend(event_arbs)

        all_arbs.sort(key=lambda a: a.profit_pct, reverse=True)
        return all_arbs
