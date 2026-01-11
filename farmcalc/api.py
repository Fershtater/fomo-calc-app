"""FastAPI entry point for farmcalc."""

import logging
import os
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel

from .clients.hyperliquid import HyperliquidClient
from .clients.telegram import TelegramClient
from .logging_config import setup_logging
from .models.domain import FundingKind, Plan, Trade, WatchConfig, WatchThresholds
from .services.calc import (
    calculate_fees,
    calculate_funding_pnl,
    calculate_volume,
    estimate_liquidation_move,
)
from .services.fill_model import FillModelService
from .services.pricing import suggested_limit_prices
from .services.scoring import evaluate_safe_entry
from .services.telegram_control import process_update
from .services.telegram_queue import TelegramUpdateQueue
from .services.watcher import WatcherService
from .settings import Settings
from .storage.state_store import StateStore, WatchStateStore

# Load .env file if it exists
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)

# Setup logging
log_format = os.getenv("LOG_FORMAT", "text")
log_level = os.getenv("LOG_LEVEL", "INFO")
setup_logging(log_format, log_level)

logger = logging.getLogger(__name__)

app = FastAPI(title="FarmCalc API", description="Perp farming calculator API")

# Initialize settings and dependencies
_settings = Settings.from_env()
_hl_client = HyperliquidClient(_settings)
_telegram_client = TelegramClient(_settings)
_state_store = StateStore(_settings.farm_state_path)
_watch_state_store = WatchStateStore(_settings.watch_state_path)
_fill_model = FillModelService()
_watcher_service = WatcherService(
    _hl_client, _telegram_client, _watch_state_store, _state_store, _settings, _fill_model
)

# Telegram update queue
_telegram_queue = TelegramUpdateQueue(maxsize=100)
_telegram_queue.set_processor(
    lambda update: process_update(
        update, _state_store, _watch_state_store, _telegram_client, _settings, _watcher_service
    )
)
_telegram_queue.start_worker()


# Pydantic models for API
class PlanModel(BaseModel):
    deposit: float = 1000.0
    default_margin: float = 100.0
    default_leverage: float = 10.0
    target_volume: float = 10000.0
    target_frozen: float = 0.0
    unfreeze_factor: float = 1.75
    level_factor: float = 0.25


class WatchConfigModel(BaseModel):
    enabled: bool = False
    poll_interval_sec: float = 5.0
    top_n: int = 25
    side: str = "either"
    open_offset_bps: float = 0.0
    close_offset_bps: float = 0.0
    funding_kind: str = "hourly"
    thresholds: Dict = {}
    cooldown_sec: float = 300.0
    sentiment_enabled: bool = False
    telegram_enabled: bool = True


@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "1.0.0",
    }


@app.get("/")
def api_root():
    """API root endpoint."""
    return {
        "name": "FarmCalc API",
        "version": "1.0.0",
        "description": "Perp farming calculator API",
        "warning": "High leverage trading is extremely risky. This tool is for calculation purposes only."
    }


@app.post("/init")
def api_init(plan: PlanModel):
    """Initialize or update the farming plan."""
    state = _state_store.load()
    state.plan = Plan(**plan.dict())
    _state_store.save(state)
    return {"status": "ok", "plan": asdict(state.plan)}


@app.get("/quote/{coin}")
def api_quote(coin: str):
    """Get quote for a coin (best bid/ask, mid, mark, funding)."""
    coin_data = _hl_client.get_coin_data(coin)
    if not coin_data:
        raise HTTPException(status_code=404, detail=f"Coin {coin} not found")
    
    l2_book = _hl_client.get_l2_book(coin)
    
    result = {
        "coin": coin,
        "mark": coin_data.get("markPx", 0),
        "mid": coin_data.get("midPx", 0),
        "oracle": coin_data.get("oraclePx", 0),
        "funding": coin_data.get("funding", 0),
    }
    
    if l2_book:
        result.update({
            "best_bid": l2_book["best_bid"],
            "best_ask": l2_book["best_ask"],
            "l2_mid": l2_book["mid"],
            "spread": l2_book["spread"],
            "spread_bps": l2_book["spread_bps"],
        })
    
    return result


@app.get("/assets")
def api_assets(sort_by: str = "funding", limit: int = 20):
    """List all available coins."""
    coins = _hl_client.get_all_coins()
    
    if sort_by == "funding":
        coins.sort(key=lambda x: x.get("funding", 0), reverse=True)
    elif sort_by == "volume":
        coins.sort(key=lambda x: x.get("dayNtlVlm", 0), reverse=True)
    elif sort_by == "oi":
        coins.sort(key=lambda x: x.get("openInterest", 0), reverse=True)
    
    return {"coins": coins[:limit]}


@app.post("/propose")
def api_propose(
    coin: str,
    side: str = "LONG",
    margin: Optional[float] = None,
    leverage: Optional[float] = None,
    hold_min: int = 60,
    fee_mode: str = "maker",
    taker_fee: float = 0.00045,
    maker_fee: float = 0.00015,
    funding_kind: str = "hourly",
    open_offset_bps: float = 0.0,
    close_offset_bps: float = 0.0,
    fill_prob: float = 1.0,
):
    """Propose a trade."""
    state = _state_store.load()
    margin = margin or state.plan.default_margin
    leverage = leverage or state.plan.default_leverage
    
    coin_data = _hl_client.get_coin_data(coin)
    if not coin_data:
        raise HTTPException(status_code=404, detail=f"Coin {coin} not found")
    
    l2_book = _hl_client.get_l2_book(coin)
    notional = margin * leverage
    
    # Calculate limit prices
    open_limit_px = None
    close_limit_px = None
    if l2_book:
        open_limit_px, close_limit_px = suggested_limit_prices(
            side, l2_book["best_bid"], l2_book["best_ask"],
            open_offset_bps, close_offset_bps
        )
    
    # Determine fee modes
    open_fee_mode = "maker" if fee_mode == "maker" or fee_mode == "both" else "taker"
    close_fee_mode = "maker" if fee_mode == "maker" else ("maker" if fee_mode == "both" else "taker")
    
    fees, fee_details = calculate_fees(
        notional, taker_fee, maker_fee, fee_mode, fill_prob,
        None, open_fee_mode, close_fee_mode
    )
    volume = calculate_volume(notional, fill_prob)
    
    funding_rate = coin_data.get("funding", 0)
    funding_kind_enum = FundingKind.HOURLY if funding_kind == "hourly" else FundingKind.EIGHT_HOUR
    funding_pnl = calculate_funding_pnl(side, notional, funding_rate, hold_min, funding_kind_enum)
    
    liquidation_move = estimate_liquidation_move(leverage, coin_data.get("marginMode"))
    
    result = {
        "coin": coin,
        "side": side,
        "margin": margin,
        "leverage": leverage,
        "notional": notional,
        "volume": volume,
        "fees": fees,
        "fee_details": fee_details,
        "funding_rate": funding_rate,
        "funding_pnl": funding_pnl,
        "net_pnl": funding_pnl - fees,
        "liquidation_move": liquidation_move,
        "fill_prob": fill_prob,
        "market_data": {
            "markPx": coin_data.get("markPx"),
            "midPx": coin_data.get("midPx"),
            "oraclePx": coin_data.get("oraclePx"),
        }
    }
    
    if l2_book:
        result["l2_book"] = l2_book
        result["open_limit_px"] = open_limit_px
        result["close_limit_px"] = close_limit_px
    
    return result


@app.post("/accept")
def api_accept(
    coin: str,
    side: str = "LONG",
    margin: Optional[float] = None,
    leverage: Optional[float] = None,
    hold_min: int = 60,
    fee_mode: str = "maker",
    taker_fee: float = 0.00045,
    maker_fee: float = 0.00015,
    funding_kind: str = "hourly",
    open_offset_bps: float = 0.0,
    close_offset_bps: float = 0.0,
    fill_prob: float = 1.0,
):
    """Accept and record a trade."""
    state = _state_store.load()
    margin = margin or state.plan.default_margin
    leverage = leverage or state.plan.default_leverage
    
    coin_data = _hl_client.get_coin_data(coin)
    if not coin_data:
        raise HTTPException(status_code=404, detail=f"Coin {coin} not found")
    
    l2_book = _hl_client.get_l2_book(coin)
    mid_px = coin_data.get("midPx", 0)
    open_price = mid_px
    
    # Calculate limit prices
    open_limit_px = None
    close_limit_px = None
    if l2_book:
        open_limit_px, close_limit_px = suggested_limit_prices(
            side, l2_book["best_bid"], l2_book["best_ask"],
            open_offset_bps, close_offset_bps
        )
        open_price = open_limit_px
    
    # Determine fee modes
    open_fee_mode = "maker" if fee_mode == "maker" or fee_mode == "both" else "taker"
    close_fee_mode = "maker" if fee_mode == "maker" else ("maker" if fee_mode == "both" else "taker")
    
    notional = margin * leverage
    fees, _ = calculate_fees(
        notional, taker_fee, maker_fee, fee_mode, fill_prob,
        None, open_fee_mode, close_fee_mode
    )
    funding_rate = coin_data.get("funding", 0)
    funding_kind_enum = FundingKind.HOURLY if funding_kind == "hourly" else FundingKind.EIGHT_HOUR
    funding_pnl = calculate_funding_pnl(side, notional, funding_rate, hold_min, funding_kind_enum)
    
    trade_id = f"{coin}_{side}_{int(datetime.now(timezone.utc).timestamp())}"
    trade = Trade(
        id=trade_id,
        coin=coin,
        side=side.upper(),
        leverage=leverage,
        margin=margin,
        notional=notional,
        open_timestamp=datetime.now(timezone.utc).isoformat(),
        planned_hold_min=hold_min,
        expected_fees=fees,
        expected_funding_pnl=funding_pnl,
        open_price=open_price,
        open_limit_px=open_limit_px,
        close_limit_px=close_limit_px,
        fill_prob=fill_prob,
        open_fee_mode=open_fee_mode,
        close_fee_mode=close_fee_mode,
    )
    
    state.trades.append(trade)
    _state_store.save(state)
    
    return {"status": "ok", "trade_id": trade_id, "trade": asdict(trade)}


@app.post("/close/{trade_id}")
def api_close(
    trade_id: str,
    close_price: Optional[float] = None,
    actual_funding_pnl: Optional[float] = None,
    actual_close_fee_mode: Optional[str] = None,
    actual_close_fee: Optional[float] = None,
):
    """Close a trade."""
    state = _state_store.load()
    
    trade = None
    for t in state.trades:
        if t.id == trade_id:
            trade = t
            break
    
    if not trade:
        raise HTTPException(status_code=404, detail=f"Trade {trade_id} not found")
    
    if trade.close_price is not None:
        raise HTTPException(status_code=400, detail=f"Trade {trade_id} already closed")
    
    if close_price is None:
        coin_data = _hl_client.get_coin_data(trade.coin)
        if not coin_data:
            raise HTTPException(status_code=404, detail=f"Could not fetch price for {trade.coin}")
        close_price = coin_data.get("midPx", 0)
    
    side_multiplier = 1.0 if trade.side == "LONG" else -1.0
    if trade.open_price and trade.open_price > 0:
        price_pnl = (close_price - trade.open_price) / trade.open_price * trade.notional * side_multiplier
    else:
        price_pnl = 0.0
    
    final_funding_pnl = actual_funding_pnl if actual_funding_pnl is not None else trade.expected_funding_pnl
    
    # Calculate actual fees
    if trade.open_fee_mode == "maker":
        open_fee_amount = trade.notional * _settings.default_maker_fee
    else:
        open_fee_amount = trade.notional * _settings.default_taker_fee
    
    if actual_close_fee is not None:
        actual_close_fee_amount = actual_close_fee
    else:
        if actual_close_fee_mode:
            close_fee_mode_actual = actual_close_fee_mode.lower()
        else:
            close_fee_mode_actual = trade.close_fee_mode
        
        if close_fee_mode_actual == "maker":
            actual_close_fee_amount = trade.notional * _settings.default_maker_fee
        else:
            actual_close_fee_amount = trade.notional * _settings.default_taker_fee
    
    total_actual_fees = open_fee_amount + actual_close_fee_amount
    realized_pnl = price_pnl + final_funding_pnl - total_actual_fees
    
    trade.close_price = close_price
    trade.close_timestamp = datetime.now(timezone.utc).isoformat()
    trade.realized_pnl = realized_pnl
    if actual_close_fee_mode:
        trade.actual_close_fee_mode = actual_close_fee_mode.lower()
    
    state.stats.total_volume_done += calculate_volume(trade.notional, trade.fill_prob)
    state.stats.total_fees += total_actual_fees
    state.stats.total_funding_pnl += final_funding_pnl
    
    _state_store.save(state)
    
    return {
        "status": "ok",
        "trade": asdict(trade),
        "realized_pnl": realized_pnl,
        "price_pnl": price_pnl,
        "funding_pnl": final_funding_pnl,
        "fees": total_actual_fees,
    }


@app.delete("/trades/{trade_id}")
def api_delete(trade_id: str):
    """Delete a trade."""
    state = _state_store.load()
    
    original_len = len(state.trades)
    state.trades = [t for t in state.trades if t.id != trade_id]
    
    if len(state.trades) == original_len:
        raise HTTPException(status_code=404, detail=f"Trade {trade_id} not found")
    
    _state_store.save(state)
    return {"status": "ok", "trade_id": trade_id}


@app.get("/status")
def api_status():
    """Get current farming status."""
    state = _state_store.load()
    
    active_trades = [asdict(t) for t in state.trades if t.close_price is None]
    
    remaining_volume = max(0, state.plan.target_volume - state.stats.total_volume_done)
    
    return {
        "plan": asdict(state.plan),
        "stats": asdict(state.stats),
        "remaining_volume": remaining_volume,
        "active_trades": active_trades,
        "all_trades": [asdict(t) for t in state.trades],
    }


# Watch API Endpoints
@app.get("/watch/status")
def api_watch_status():
    """Get watch status and configuration."""
    state = _watcher_service.get_state()
    return {
        "config": {
            **asdict(state.config),
            "thresholds": asdict(state.config.thresholds),
        },
        "is_running": state.is_running,
        "last_poll_time": state.last_poll_time,
        "last_alerts": state.last_alerts[-10:],
        "telegram_enabled": _telegram_client.enabled,
        "disclaimer": "⚠️ Paper-only alerts. No trading executed. High leverage trading is extremely risky."
    }


@app.post("/watch/start")
def api_watch_start():
    """Start the watch polling loop."""
    _watcher_service.start()
    return {"status": "started", "message": "Watch polling started"}


@app.post("/watch/stop")
def api_watch_stop():
    """Stop the watch polling loop."""
    _watcher_service.stop()
    return {"status": "stopped", "message": "Watch polling stopped"}


@app.post("/watch/config")
def api_watch_config(config_update: WatchConfigModel):
    """Update watch configuration."""
    config_dict = config_update.dict()
    thresholds = WatchThresholds(**config_dict.pop("thresholds", {}))
    config = WatchConfig(**config_dict, thresholds=thresholds)
    _watcher_service.update_config(config)
    return {
        "status": "updated",
        "config": {
            **asdict(config),
            "thresholds": asdict(config.thresholds),
        }
    }


@app.get("/watch/last")
def api_watch_last():
    """Get last computed safe entry snapshot for top coins."""
    snapshot = _watcher_service.get_last_snapshot()
    state = _watcher_service.get_state()
    
    return {
        "last_poll_time": state.last_poll_time,
        "snapshot": snapshot,
    }


@app.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: Optional[str] = Header(None),
):
    """Telegram webhook endpoint for receiving updates.
    
    Verifies secret token if configured and enqueues updates for async processing.
    Returns 200 OK immediately to prevent Telegram retries.
    """
    # Verify secret token if configured
    if _settings.telegram_secret_token:
        if x_telegram_bot_api_secret_token != _settings.telegram_secret_token:
            logger.warning("Invalid secret token in webhook request")
            raise HTTPException(status_code=403, detail="Invalid secret token")
    
    try:
        update = await request.json()
        # Enqueue for async processing
        enqueued = _telegram_queue.enqueue(update)
        if not enqueued:
            logger.warning("Telegram update queue full, update dropped")
        return {"ok": True}
    except Exception as e:
        logger.error(f"Error receiving Telegram webhook: {e}", exc_info=True)
        # Return 200 to prevent Telegram retries
        return {"ok": False, "error": str(e)}


@app.get("/telegram/status")
def telegram_status():
    """Get Telegram webhook status (for debugging)."""
    webhook_info = _telegram_client.get_webhook_info()
    return {
        "enabled": _telegram_client.enabled,
        "webhook_info": webhook_info,
        "owner_id": _settings.telegram_owner_id,
        "allowed_chat_id": _settings.telegram_allowed_chat_id,
        "control_plane_enabled": _settings.telegram_control_plane,
    }


@app.get("/telegram/metrics")
def telegram_metrics():
    """Get Telegram queue metrics (for debugging)."""
    return _telegram_queue.get_metrics()
