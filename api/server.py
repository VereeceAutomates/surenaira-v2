"""
SureNaira — FastAPI REST Server
================================
Serves the arb store to the frontend via clean REST endpoints.
Also serves WebSocket for real-time push updates.

Endpoints:
  GET  /api/arbs              — all current arb opportunities (filterable)
  GET  /api/stats             — dashboard stats
  GET  /api/bookmakers        — bookmaker list + status
  GET  /api/arbs/{arb_id}     — single arb detail + stake calculator
  POST /api/calculate         — stake calculator
  WS   /ws/arbs               — WebSocket stream (new arbs pushed every 15s)
"""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from engine.orchestrator import Orchestrator
from config.settings import BOOKMAKERS

logger = logging.getLogger("api")

# ─── Global orchestrator instance ───────────────────────────────────────────

orchestrator: Optional[Orchestrator] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start orchestrator on startup, stop on shutdown."""
    global orchestrator
    orchestrator = Orchestrator()

    # Run first cycle immediately so the API has data right away
    await orchestrator.run_cycle(is_live=False)
    await orchestrator.run_cycle(is_live=True)

    # Then start the continuous loop in the background
    loop_task = asyncio.create_task(orchestrator.start_loop())

    yield  # App is running

    orchestrator.stop()
    loop_task.cancel()
    try:
        await loop_task
    except asyncio.CancelledError:
        pass


# ─── App setup ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="SureNaira API",
    description="Nigerian surebet scanner — real-time arbitrage opportunities",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # Restrict to your domain in production
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Request / Response models ───────────────────────────────────────────────

class StakeCalcRequest(BaseModel):
    odds_a: float
    odds_b: float
    budget: float  # NGN


class StakeCalcResponse(BaseModel):
    is_arb: bool
    implied_sum: Optional[float] = None
    profit_pct: Optional[float] = None
    stake_a: Optional[float] = None
    stake_b: Optional[float] = None
    guaranteed_return: Optional[float] = None
    guaranteed_profit: Optional[float] = None
    message: str = ""


# ─── Endpoints ───────────────────────────────────────────────────────────────

@app.get("/api/arbs")
async def get_arbs(
    market_type:    Optional[str]   = Query(None, description="'direct' or 'cross'"),
    is_live:        Optional[bool]  = Query(None, description="True = live only, False = prematch only"),
    min_profit_pct: float           = Query(0.0,  description="Minimum profit %"),
    bookmaker:      Optional[str]   = Query(None, description="Filter by bookmaker ID (comma-separated)"),
    sport:          Optional[str]   = Query(None, description="Sport key e.g. 'football'"),
    limit:          int             = Query(100,  description="Max results", le=500),
):
    """
    Return current arbitrage opportunities with optional filters.
    Results are sorted by profit % descending.
    """
    if orchestrator is None:
        return JSONResponse({"error": "Server not ready"}, status_code=503)

    bk_ids = [b.strip() for b in bookmaker.split(",")] if bookmaker else None

    arbs = await orchestrator.store.get_all(
        market_type=market_type,
        is_live=is_live,
        min_profit_pct=min_profit_pct,
        bookmaker_ids=bk_ids,
        sport=sport,
    )

    return {
        "count":  len(arbs[:limit]),
        "total":  len(arbs),
        "arbs":   arbs[:limit],
    }


@app.get("/api/stats")
async def get_stats():
    """Dashboard stats: counts, avg profit, best arb, bookmaker statuses."""
    if orchestrator is None:
        return JSONResponse({"error": "Server not ready"}, status_code=503)
    return await orchestrator.store.get_stats()


@app.get("/api/bookmakers")
async def get_bookmakers():
    """List all configured bookmakers with their current scraper status."""
    if orchestrator is None:
        return JSONResponse({"error": "Server not ready"}, status_code=503)

    status = orchestrator.store.bookmaker_status
    result = []
    for bk_id, cfg in BOOKMAKERS.items():
        bk_status = status.get(bk_id, {})
        result.append({
            "id":           bk_id,
            "name":         cfg["name"],
            "active":       cfg.get("active", False),
            "url":          cfg["base_url"],
            "scrape_method": cfg.get("scrape_method", "requests"),
            "priority":     cfg.get("priority", 3),
            "last_scrape":  bk_status.get("scraped_at"),
            "legs_scraped": bk_status.get("legs_scraped", 0),
            "success":      bk_status.get("success"),
            "error":        bk_status.get("error"),
            "duration_ms":  bk_status.get("duration_ms", 0),
        })
    return {"bookmakers": result}


@app.get("/api/arbs/{arb_id}")
async def get_arb_detail(arb_id: str):
    """
    Get a single arb by ID with full detail.
    Includes stake calculations for common budgets.
    """
    if orchestrator is None:
        return JSONResponse({"error": "Server not ready"}, status_code=503)

    all_arbs = await orchestrator.store.get_all()
    match = next((a for a in all_arbs if a["arb_id"] == arb_id), None)

    if not match:
        raise HTTPException(status_code=404, detail="Arb not found or expired")

    # Add pre-calculated stakes for common budget amounts
    odds_a = match["leg_a"]["odds"]
    odds_b = match["leg_b"]["odds"]
    stakes_table = {}
    for budget in [10_000, 25_000, 50_000, 100_000, 200_000, 500_000]:
        implied = (1 / odds_a) + (1 / odds_b)
        if implied < 1:
            sa = budget * (1 / odds_a) / implied
            sb = budget * (1 / odds_b) / implied
            ret = sa * odds_a
            stakes_table[str(budget)] = {
                "stake_a":           round(sa, 2),
                "stake_b":           round(sb, 2),
                "guaranteed_return": round(ret, 2),
                "guaranteed_profit": round(ret - budget, 2),
            }

    return {**match, "stakes_table": stakes_table}


@app.post("/api/calculate", response_model=StakeCalcResponse)
async def calculate_stakes(req: StakeCalcRequest):
    """
    Standalone stake calculator.
    Given two odds and a total budget, return the optimal stake split.
    """
    if req.odds_a < 1.01 or req.odds_b < 1.01:
        return StakeCalcResponse(
            is_arb=False,
            message="Odds must be at least 1.01"
        )

    if req.budget <= 0:
        return StakeCalcResponse(
            is_arb=False,
            message="Budget must be positive"
        )

    implied = (1 / req.odds_a) + (1 / req.odds_b)

    if implied >= 1.0:
        return StakeCalcResponse(
            is_arb=False,
            implied_sum=round(implied, 6),
            message=f"No arb — implied probability is {implied*100:.2f}% (must be < 100%)"
        )

    profit_pct = ((1 - implied) / implied) * 100
    stake_a = req.budget * (1 / req.odds_a) / implied
    stake_b = req.budget * (1 / req.odds_b) / implied
    guaranteed_return = stake_a * req.odds_a

    return StakeCalcResponse(
        is_arb=True,
        implied_sum=round(implied, 6),
        profit_pct=round(profit_pct, 4),
        stake_a=round(stake_a, 2),
        stake_b=round(stake_b, 2),
        guaranteed_return=round(guaranteed_return, 2),
        guaranteed_profit=round(guaranteed_return - req.budget, 2),
        message=f"Arb confirmed — {profit_pct:.2f}% guaranteed profit",
    )


@app.get("/api/health")
async def health():
    """Health check endpoint."""
    return {
        "status":    "ok",
        "version":   "1.0.0",
        "timestamp": asyncio.get_event_loop().time(),
    }


# ─── WebSocket — real-time arb stream ────────────────────────────────────────

class ConnectionManager:
    """Manages active WebSocket connections for push updates."""

    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)
        logger.info(f"WS client connected. Total: {len(self.active)}")

    def disconnect(self, ws: WebSocket):
        self.active.remove(ws)
        logger.info(f"WS client disconnected. Total: {len(self.active)}")

    async def broadcast(self, data: dict):
        disconnected = []
        for ws in self.active:
            try:
                await ws.send_json(data)
            except Exception:
                disconnected.append(ws)
        for ws in disconnected:
            self.active.remove(ws)


ws_manager = ConnectionManager()


@app.websocket("/ws/arbs")
async def websocket_arbs(websocket: WebSocket):
    """
    WebSocket endpoint — pushes updated arb list every 15 seconds.
    Also pushes immediately on connect.
    Client receives:
      { "type": "arbs_update", "arbs": [...], "stats": {...} }
    """
    await ws_manager.connect(websocket)
    try:
        # Send immediately on connect
        arbs  = await orchestrator.store.get_all()
        stats = await orchestrator.store.get_stats()
        await websocket.send_json({
            "type":  "arbs_update",
            "arbs":  arbs[:100],
            "stats": stats,
        })

        # Then push every 15 seconds
        while True:
            await asyncio.sleep(15)
            arbs  = await orchestrator.store.get_all()
            stats = await orchestrator.store.get_stats()
            await websocket.send_json({
                "type":  "arbs_update",
                "arbs":  arbs[:100],
                "stats": stats,
            })
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WS error: {e}")
        ws_manager.disconnect(websocket)
