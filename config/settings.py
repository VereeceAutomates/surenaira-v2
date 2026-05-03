"""
SureNaira — Central Configuration
All bookmakers, markets, scraping settings, and arb rules live here.
"""

# ─── Bookmaker Registry ─────────────────────────────────────────────────────

BOOKMAKERS = {
    "sportybet": {
        "name": "SportyBet",
        "base_url": "https://www.sportybet.com",
        # Internal API discovered via browser DevTools (Network tab → XHR)
        # SportyBet uses Sportradar as their data provider
        "api_base": "https://www.sportybet.com/api/ng",
        "endpoints": {
            "prematch_events": "/factsCenter/sportEvents",
            "live_events":     "/factsCenter/liveEvents",
            "event_markets":   "/factsCenter/eventMarkets",
        },
        "headers": {
            "User-Agent":       "Mozilla/5.0 (Linux; Android 12; Pixel 6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
            "Accept":           "application/json",
            "Accept-Language":  "en-NG,en;q=0.9",
            "Origin":           "https://www.sportybet.com",
            "Referer":          "https://www.sportybet.com/ng/sport/football",
        },
        "sport_id": "sr:sport:1",     # Sportradar ID for football
        "priority": 1,                 # Higher priority = more trusted odds
        "active": True,
    },

    "bet9ja": {
        "name": "Bet9ja",
        "base_url": "https://web.bet9ja.com",
        "api_base": "https://web.bet9ja.com/Sport",
        "endpoints": {
            "prematch_events": "/Default.aspx",
            "live_events":     "/LiveBetting.aspx",
        },
        "headers": {
            "User-Agent":       "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept":           "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language":  "en-NG,en;q=0.9",
            "Referer":          "https://web.bet9ja.com/Sport/Default.aspx",
        },
        "scrape_method": "playwright",  # Needs JS rendering
        "priority": 2,
        "active": True,
    },

    "betking": {
        "name": "BetKing",
        "base_url": "https://www.betking.com",
        "api_base": "https://www.betking.com/api",
        "endpoints": {
            "prematch_events": "/sports/prematch/events",
            "live_events":     "/sports/live/events",
            "markets":         "/sports/markets",
        },
        "headers": {
            "User-Agent":  "Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36",
            "Accept":      "application/json",
            "Referer":     "https://m.betking.com",
        },
        "scrape_method": "requests",
        "priority": 2,
        "active": True,
    },

    "bangbet": {
        "name": "BangBet",
        "base_url": "https://www.bangbet.com",
        "api_base": "https://www.bangbet.com/api",
        "endpoints": {
            "prematch_events": "/v1/sports/events",
            "live_events":     "/v1/sports/live",
        },
        "headers": {
            "User-Agent": "Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36",
            "Accept":     "application/json",
        },
        "scrape_method": "requests",
        "priority": 3,
        "active": True,
    },

    "betano": {
        "name": "Betano.ng",
        "base_url": "https://www.betano.ng",
        "api_base": "https://www.betano.ng/api",
        "endpoints": {
            "prematch_events": "/sports/football/events",
            "live_events":     "/sports/live/events",
        },
        "headers": {
            "User-Agent": "Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36",
            "Accept":     "application/json",
        },
        "scrape_method": "playwright",
        "priority": 2,
        "active": True,
    },

    "msport": {
        "name": "Msport",
        "base_url": "https://www.msport.com",
        "api_base": "https://www.msport.com/ng/api",
        "endpoints": {
            "prematch_events": "/events/list",
            "live_events":     "/events/live",
        },
        "headers": {
            "User-Agent": "Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36",
            "Accept":     "application/json",
            "x-country":  "NG",
        },
        "scrape_method": "requests",
        "priority": 3,
        "active": True,
    },

    "livescorebet": {
        "name": "LiveScoreBet",
        "base_url": "https://www.livescorebet.com",
        "api_base": "https://www.livescorebet.com/api",
        "endpoints": {
            "prematch_events": "/odds/football",
            "live_events":     "/odds/football/live",
        },
        "headers": {
            "User-Agent": "Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36",
            "Accept":     "application/json",
        },
        "scrape_method": "requests",
        "priority": 3,
        "active": True,
    },

    "1win": {
        "name": "1Win.ng",
        "base_url": "https://1win.ng",
        "api_base": "https://1win.ng/api",
        "endpoints": {
            "prematch_events": "/sports/football",
            "live_events":     "/sports/live",
        },
        "headers": {
            "User-Agent": "Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36",
            "Accept":     "application/json",
        },
        "scrape_method": "requests",
        "priority": 3,
        "active": True,
    },

    "ilotbet": {
        "name": "IlotBet",
        "base_url": "https://www.ilotbet.com",
        "api_base": "https://www.ilotbet.com/api",
        "endpoints": {
            "prematch_events": "/sports/events",
            "live_events":     "/sports/live",
        },
        "headers": {
            "User-Agent": "Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36",
            "Accept":     "application/json",
        },
        "scrape_method": "playwright",
        "priority": 3,
        "active": True,
    },

    "footballng": {
        "name": "Football.ng",
        "base_url": "https://www.football.com/ng",
        "api_base": "https://www.football.com/ng/api",
        "endpoints": {
            "prematch_events": "/events",
            "live_events":     "/events/live",
        },
        "headers": {
            "User-Agent": "Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36",
            "Accept":     "application/json",
        },
        "scrape_method": "requests",
        "priority": 3,
        "active": True,
    },
}

# ─── Market Definitions ──────────────────────────────────────────────────────
# Each market has an ID, the possible 2-outcome legs, and coverage rules.
# For cross-market arbs we define PAIRS explicitly.

MARKETS = {
    # ── Direct 2-outcome markets ─────────────────────────────────────────
    "1x2_hw_aw": {
        "label": "Home/Away (DNB)",
        "type": "direct",
        "outcomes": ["home_win_dnb", "away_win_dnb"],
        "description": "Home win (draw no bet) vs Away win (draw no bet)",
    },
    "over_under": {
        "label": "Over/Under",
        "type": "direct",
        "line_variants": [0.5, 1.5, 2.5, 3.5, 4.5],
        "outcomes": ["over", "under"],
        "description": "Over X goals vs Under X goals",
    },
    "asian_handicap": {
        "label": "Asian Handicap",
        "type": "direct",
        "line_variants": [-2.5, -2.0, -1.5, -1.0, -0.5, 0, 0.5, 1.0, 1.5, 2.0, 2.5],
        "outcomes": ["home_ah", "away_ah"],
        "description": "Home -X AH vs Away +X AH (same line, opposite sides)",
    },
    "btts": {
        "label": "BTTS",
        "type": "direct",
        "outcomes": ["btts_yes", "btts_no"],
        "description": "Both teams to score: Yes vs No",
    },

    # ── Cross-market pairs ────────────────────────────────────────────────
    # These are the sophisticated arbs. Both legs together exhaust ALL outcomes.
    # Key insight: Home (-1:0) HDP + Away Win covers every possible result.
    #
    # How Home (-1:0) HDP works:
    #   - Applies a virtual 1-0 scoreline FOR the home team
    #   - Home wins this bet if: Home wins by 2+ goals, OR Home wins by 1, OR it's a DRAW
    #     (because 1-0 handicap means home only LOSES if Away wins the actual match)
    #   - Away wins this bet ONLY if: Away wins the actual match
    #
    # So: [Home (-1:0) HDP] covers Home Win + Draw  ↔  [Away Win outright] covers Away Win
    # Together they cover 100% of all outcomes → perfect 2-outcome cross-market arb.
    #
    # Similarly Home (0:-1) HDP [virtual 0-1 deficit]:
    #   - Home wins ONLY if Home wins the actual match by 2+... wait, no:
    #   - It applies a virtual 0-1 AGAINST home, so home needs to overcome it
    #   - Home wins if actual result is Home Win by 1+ (after applying deficit, net ≥ 0)
    #     Actually Home (0:1) means home gets +1 goal advantage → home wins if they win OR draw
    #   - We use: Home (+1:0) = home gets a goal head start → home wins if actual draw or home win
    #   - Away (+0:-1) = away gets a goal head start → away wins if actual away win or draw
    #
    # We define cross-market pairs by their logical coverage:

    "cross_home_hdp_neg1_vs_away_win": {
        "label": "Home (-1:0) HDP × Away Win",
        "type": "cross",
        "leg_a": {
            "market": "european_handicap",
            "handicap": "-1:0",   # home given virtual 1-0 lead
            "outcome": "home",
            "covers": ["home_win_2plus", "home_win_1", "draw"],
        },
        "leg_b": {
            "market": "1x2",
            "outcome": "away_win",
            "covers": ["away_win"],
        },
        "exhaustive": True,  # legs A+B together cover ALL 4 possible outcomes
        "description": "Home (virtual 1-0 up) vs Away win outright. Draw covered by Leg A.",
    },

    "cross_away_hdp_neg1_vs_home_win": {
        "label": "Away (-1:0) HDP × Home Win",
        "type": "cross",
        "leg_a": {
            "market": "european_handicap",
            "handicap": "0:-1",   # away given virtual 1-0 lead
            "outcome": "away",
            "covers": ["away_win_2plus", "away_win_1", "draw"],
        },
        "leg_b": {
            "market": "1x2",
            "outcome": "home_win",
            "covers": ["home_win"],
        },
        "exhaustive": True,
        "description": "Away (virtual 1-0 up) vs Home win outright. Draw covered by Leg A.",
    },

    "cross_over_dnb_vs_under": {
        "label": "Over X (DNB) × Under X",
        "type": "cross",
        "line_variants": [1.5, 2.5, 3.5],
        "leg_a": {
            "market": "over_under",
            "outcome": "over",
        },
        "leg_b": {
            "market": "over_under",
            "outcome": "under",
            "book": "different",   # must be from a DIFFERENT bookmaker
        },
        "exhaustive": True,
        "description": "Over X on one bookie, Under X on another. Cross-bookie price gap.",
    },

    "cross_ah_home_vs_1x2_away": {
        "label": "Home AH -0.5 × Away 1X2",
        "type": "cross",
        "leg_a": {
            "market": "asian_handicap",
            "handicap": -0.5,
            "outcome": "home_ah",
            "covers": ["home_win"],
        },
        "leg_b": {
            "market": "1x2",
            "outcome": "away_win_or_draw",  # double chance X2
            "covers": ["draw", "away_win"],
        },
        "exhaustive": True,
        "description": "Home -0.5 AH (home must win) vs Double Chance X2 (draw or away). Covers all.",
    },
}

# ─── Arb Detection Settings ──────────────────────────────────────────────────

ARB_CONFIG = {
    # Minimum profit % to surface an arb (filter noise)
    "min_profit_pct": 0.3,

    # Maximum profit % (above this is suspicious / likely a data error)
    "max_profit_pct": 25.0,

    # Minimum odds on any single leg (too low = bad value / likely error)
    "min_odds": 1.10,

    # Maximum odds on any single leg (too high = likely error)
    "max_odds": 50.0,

    # How old can an odds snapshot be before we discard it (seconds)
    "max_odds_age_seconds": 90,

    # For LIVE arbs, tighter window — odds move faster
    "max_live_odds_age_seconds": 30,

    # Minimum event match score (0–1) from fuzzy name matching
    "min_event_match_score": 0.80,

    # For same-market arbs, require exactly matching line (e.g. both Over 2.5)
    "require_exact_line_match": True,
}

# ─── Scraping Schedule ───────────────────────────────────────────────────────

SCRAPE_CONFIG = {
    # How often to re-scrape each bookmaker for pre-match odds (seconds)
    "prematch_interval_seconds": 60,

    # How often for live odds
    "live_interval_seconds": 15,

    # Max concurrent scrapers running at once
    "max_concurrent_scrapers": 4,

    # Retry attempts if a scrape fails
    "retry_attempts": 3,

    # Seconds between retries
    "retry_delay_seconds": 5,

    # Rotate user agents to avoid detection
    "rotate_user_agents": True,

    # Request timeout
    "request_timeout_seconds": 20,
}

# ─── Supported Sports ────────────────────────────────────────────────────────

SPORTS = {
    "football": {
        "label": "Football (Soccer)",
        "sr_id": "sr:sport:1",
        "markets": ["1x2_hw_aw", "over_under", "asian_handicap", "btts",
                    "cross_home_hdp_neg1_vs_away_win", "cross_away_hdp_neg1_vs_home_win",
                    "cross_over_dnb_vs_under", "cross_ah_home_vs_1x2_away"],
        "active": True,
    },
    "basketball": {
        "label": "Basketball",
        "sr_id": "sr:sport:2",
        "markets": ["1x2_hw_aw", "over_under", "asian_handicap"],
        "active": True,
    },
    "tennis": {
        "label": "Tennis",
        "sr_id": "sr:sport:5",
        "markets": ["1x2_hw_aw"],  # No draw in tennis — perfect for 2-way arbs
        "active": True,
    },
}
