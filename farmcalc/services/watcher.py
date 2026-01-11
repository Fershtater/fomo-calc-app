"""Watcher service for polling and alerting with debouncing and rate limiting."""

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional

from ..clients.hyperliquid import HyperliquidClient
from ..clients.telegram import TelegramClient
from ..models.domain import WatchConfig, WatchState
from ..services.fill_model import FillModelService
from ..services.pricing import suggested_limit_prices
from ..services.proposals import create_proposal_from_snapshot, format_proposal_message
from ..services.scoring import SafeEntryScore, evaluate_safe_entry
from ..settings import Settings
from ..storage.state_store import StateStore, WatchStateStore

logger = logging.getLogger(__name__)


@dataclass
class AlertState:
    """State for debouncing and hysteresis."""
    consecutive_passes: int = 0
    consecutive_fails: int = 0
    armed: bool = False
    last_alert_time: float = 0.0


@dataclass
class AlertState:
    """State for debouncing and hysteresis."""
    consecutive_passes: int = 0
    consecutive_fails: int = 0
    armed: bool = False
    last_alert_time: float = 0.0


class WatcherService:
    """Service for watching market conditions with debouncing and rate limiting."""
    
    def __init__(
        self,
        hl_client: HyperliquidClient,
        telegram_client: TelegramClient,
        watch_state_store: WatchStateStore,
        state_store: StateStore,
        settings: Settings,
        fill_model: Optional[FillModelService] = None,
    ):
        """Initialize watcher service."""
        self.hl_client = hl_client
        self.telegram_client = telegram_client
        self.watch_state_store = watch_state_store
        self.state_store = state_store
        self.settings = settings
        self.fill_model = fill_model or FillModelService()
        self._state: Optional[WatchState] = None
        self._poll_thread: Optional[threading.Thread] = None
        self._last_snapshot: Dict[str, Dict] = {}
        
        # Debouncing/hysteresis state per coin+side
        self._alert_states: Dict[str, AlertState] = {}
        
        # Global rate limiting
        self._alert_times: deque = deque(maxlen=100)  # Track last 100 alerts
        self._max_alerts_per_hour: int = 10
        
        # Round-robin for L2 polling
        self._l2_poll_index: int = 0
        
        # Meta refresh slower (60s default)
        self._meta_refresh_interval: float = 60.0
    
    def get_state(self) -> WatchState:
        """Get current watch state."""
        if not self._state:
            self._state = self.watch_state_store.load()
        return self._state
    
    def save_state(self):
        """Save current watch state."""
        if self._state:
            self.watch_state_store.save(self._state)
    
    def start(self):
        """Start the watcher polling loop."""
        state = self.get_state()
        if state.is_running:
            logger.warning("Watcher is already running")
            return
        
        state.is_running = True
        state.config.enabled = True
        self.save_state()
        
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()
        logger.info("Watcher started")
    
    def stop(self):
        """Stop the watcher polling loop."""
        state = self.get_state()
        if not state.is_running:
            logger.warning("Watcher is not running")
            return
        
        state.is_running = False
        state.config.enabled = False
        self.save_state()
        logger.info("Watcher stopped")
    
    def update_config(self, config: WatchConfig):
        """Update watch configuration."""
        state = self.get_state()
        state.config = config
        self.save_state()
        logger.info("Watch configuration updated")
    
    def get_last_snapshot(self) -> Dict[str, Dict]:
        """Get last computed snapshot."""
        return self._last_snapshot
    
    def evaluate_now(self) -> Optional[Dict[str, Dict]]:
        """Force immediate evaluation and return best candidates.
        
        Returns:
            Dict of coin -> snapshot data, or None if error
        """
        try:
            state = self.get_state()
            
            # Fetch market data
            universe, contexts = self.hl_client.fetch_market_data()
            
            # Get top N coins
            coins_with_data = []
            for i, u in enumerate(universe):
                coin_name = u.get("name")
                if coin_name and i < len(contexts):
                    ctx = contexts[i]
                    if not isinstance(ctx, dict):
                        continue
                    
                    # Extract funding safely
                    funding_value = 0.0
                    funding_field = ctx.get("funding")
                    if isinstance(funding_field, dict):
                        funding_value = float(funding_field.get("funding", 0))
                    elif isinstance(funding_field, (int, float)):
                        funding_value = float(funding_field)
                    elif isinstance(funding_field, str):
                        try:
                            funding_value = float(funding_field)
                        except (ValueError, TypeError):
                            funding_value = 0.0
                    
                    # Helper to extract float from dict, handling strings
                    def _to_float(d: dict, key: str, default: float = 0.0) -> float:
                        val = d.get(key, default)
                        if isinstance(val, (int, float)):
                            return float(val)
                        elif isinstance(val, str):
                            try:
                                return float(val)
                            except (ValueError, TypeError):
                                return default
                        return default
                    
                    coins_with_data.append({
                        "coin": coin_name,
                        "dayNtlVlm": _to_float(ctx, "dayNtlVlm", 0),
                        "data": {
                            "maxLeverage": _to_float(u, "maxLeverage", 0),
                            "onlyIsolated": u.get("onlyIsolated", False),
                            "marginMode": u.get("marginMode"),
                            "funding": funding_value,
                            "markPx": _to_float(ctx, "markPx", 0),
                            "midPx": _to_float(ctx, "midPx", 0),
                            "oraclePx": _to_float(ctx, "oraclePx", 0),
                            "openInterest": _to_float(ctx, "openInterest", 0),
                            "dayNtlVlm": _to_float(ctx, "dayNtlVlm", 0),
                        }
                    })
            
            coins_with_data.sort(key=lambda x: x["dayNtlVlm"], reverse=True)
            top_coins = coins_with_data[:state.config.top_n]
            
            snapshot = {}
            for coin_info in top_coins[:5]:  # Limit to 5 for /next
                coin = coin_info["coin"]
                coin_data = coin_info["data"]
                
                # Check mute
                if coin in state.muted_coins:
                    if time.time() < state.muted_coins[coin]:
                        continue
                    else:
                        # Expired mute, clean up
                        state.muted_coins.pop(coin)
                
                l2_book = self.hl_client.get_l2_book(coin)
                if not l2_book:
                    continue
                
                score_result = evaluate_safe_entry(
                    coin, coin_data, l2_book, state.config,
                    score_threshold=80.0
                )
                
                if score_result and score_result.passed:
                    snapshot[coin] = {
                        "score": score_result.total_score,
                        "reasons": score_result.reasons,
                        "metrics": score_result.metrics,
                    }
            
            return snapshot if snapshot else None
        except Exception as e:
            logger.error(f"Error in evaluate_now: {e}", exc_info=True)
            return None
    
    def _check_rate_limit(self) -> bool:
        """Check if we're within global rate limit.
        
        Returns:
            True if we can send an alert, False if rate limited
        """
        current_time = time.time()
        # Remove alerts older than 1 hour
        while self._alert_times and current_time - self._alert_times[0] > 3600:
            self._alert_times.popleft()
        
        return len(self._alert_times) < self._max_alerts_per_hour
    
    def _should_trigger_alert(
        self,
        alert_key: str,
        score: float,
        threshold: float,
        debounce_count: int = 3,
        hysteresis: float = 5.0,
    ) -> bool:
        """Check if alert should trigger with debouncing and hysteresis.
        
        Args:
            alert_key: Unique key for coin+side
            score: Current score
            threshold: Pass threshold
            debounce_count: Number of consecutive passes needed
            hysteresis: Hysteresis band (clear only if score <= threshold - hysteresis)
        
        Returns:
            True if alert should trigger
        """
        if alert_key not in self._alert_states:
            self._alert_states[alert_key] = AlertState()
        
        state = self._alert_states[alert_key]
        
        # Check if score passes threshold
        if score >= threshold:
            state.consecutive_passes += 1
            state.consecutive_fails = 0
            
            # Arm if we have enough consecutive passes
            if state.consecutive_passes >= debounce_count:
                state.armed = True
        else:
            state.consecutive_passes = 0
            
            # Clear armed state only if score drops below threshold - hysteresis
            if score <= (threshold - hysteresis):
                state.consecutive_fails += 1
                if state.consecutive_fails >= debounce_count:
                    state.armed = False
        
        return state.armed
    
    def _poll_loop(self):
        """Background polling loop with improved staggering."""
        state = self.get_state()
        logger.info(f"Starting watch poll loop (interval: {state.config.poll_interval_sec}s)")
        
        # Cache for metaAndAssetCtxs (refresh slower)
        last_meta_fetch = 0
        cached_universe = []
        cached_contexts = []
        
        while state.is_running:
            try:
                current_time = time.time()
                
                # Fetch market data (with slower refresh)
                if current_time - last_meta_fetch > self._meta_refresh_interval:
                    try:
                        universe, contexts = self.hl_client.fetch_market_data()
                        cached_universe = universe
                        cached_contexts = contexts
                        last_meta_fetch = current_time
                        logger.debug("Refreshed market data cache")
                    except Exception as e:
                        logger.error(f"Error fetching market data: {e}")
                        time.sleep(state.config.poll_interval_sec)
                        continue
                
                # Helper to extract float from dict, handling strings
                def _to_float(d: dict, key: str, default: float = 0.0) -> float:
                    val = d.get(key, default)
                    if isinstance(val, (int, float)):
                        return float(val)
                    elif isinstance(val, str):
                        try:
                            return float(val)
                        except (ValueError, TypeError):
                            return default
                    return default
                
                # Get top N coins by volume
                coins_with_data = []
                for i, u in enumerate(cached_universe):
                    coin_name = u.get("name")
                    if coin_name and i < len(cached_contexts):
                        ctx = cached_contexts[i]
                        if not isinstance(ctx, dict):
                            continue
                        
                        # Extract funding safely
                        funding_value = 0.0
                        funding_field = ctx.get("funding")
                        if isinstance(funding_field, dict):
                            funding_value = float(funding_field.get("funding", 0))
                        elif isinstance(funding_field, (int, float)):
                            funding_value = float(funding_field)
                        elif isinstance(funding_field, str):
                            try:
                                funding_value = float(funding_field)
                            except (ValueError, TypeError):
                                funding_value = 0.0
                        
                        coins_with_data.append({
                            "coin": coin_name,
                            "dayNtlVlm": _to_float(ctx, "dayNtlVlm", 0),
                            "data": {
                                "maxLeverage": _to_float(u, "maxLeverage", 0),
                                "onlyIsolated": u.get("onlyIsolated", False),
                                "marginMode": u.get("marginMode"),
                                "funding": funding_value,
                                "markPx": _to_float(ctx, "markPx", 0),
                                "midPx": _to_float(ctx, "midPx", 0),
                                "oraclePx": _to_float(ctx, "oraclePx", 0),
                                "openInterest": _to_float(ctx, "openInterest", 0),
                                "dayNtlVlm": _to_float(ctx, "dayNtlVlm", 0),
                            }
                        })
                
                # Sort by volume and take top N
                coins_with_data.sort(key=lambda x: x["dayNtlVlm"], reverse=True)
                top_coins = coins_with_data[:state.config.top_n]
                
                # Round-robin L2 polling: process subset each tick
                coins_per_tick = max(1, len(top_coins) // 3)  # Process 1/3 each tick
                start_idx = self._l2_poll_index % len(top_coins) if top_coins else 0
                coins_to_poll = []
                for i in range(coins_per_tick):
                    idx = (start_idx + i) % len(top_coins)
                    coins_to_poll.append(top_coins[idx])
                
                self._l2_poll_index = (self._l2_poll_index + coins_per_tick) % len(top_coins) if top_coins else 0
                
                # Staggered polling interval
                min_coin_interval = max(
                    self.settings.poll_interval_floor_sec,
                    state.config.poll_interval_sec / len(coins_to_poll) if coins_to_poll else 2.0
                )
                
                snapshot = {}
                for coin_info in coins_to_poll:
                    if not state.is_running:
                        break
                    
                    coin = coin_info["coin"]
                    coin_data = coin_info["data"]
                    
                    # Fetch L2 book
                    l2_book = self.hl_client.get_l2_book(coin)
                    if not l2_book:
                        time.sleep(min_coin_interval)
                        continue
                    
                    # Add snapshot for fill model
                    self.fill_model.add_snapshot(coin, {
                        "mid": l2_book.get("mid", 0),
                        "bid": l2_book.get("best_bid", 0),
                        "ask": l2_book.get("best_ask", 0),
                        "spread": l2_book.get("spread_bps", 0),
                        "depth_top": l2_book.get("depth_top", 0),
                    })
                    
                    # Evaluate safe entry with scoring
                    score_result = evaluate_safe_entry(
                        coin, coin_data, l2_book, state.config,
                        score_threshold=80.0  # Default threshold
                    )
                    
                    if not score_result:
                        time.sleep(min_coin_interval)
                        continue
                    
                    # Store in snapshot
                    snapshot[coin] = {
                        "score": score_result.total_score,
                        "passed": score_result.passed,
                        "metrics": score_result.metrics,
                        "reasons": score_result.reasons,
                        "component_scores": {
                            "spread": score_result.component_scores.spread_score,
                            "mark_dev": score_result.component_scores.mark_dev_score,
                            "oracle_dev": score_result.component_scores.oracle_dev_score,
                            "funding": score_result.component_scores.funding_score,
                            "liquidity": score_result.component_scores.liquidity_score,
                            "depth": score_result.component_scores.depth_score,
                        },
                    }
                    
                    # Get safe sides from score result
                    safe_sides = score_result.metrics.get("safe_sides", [])
                    
                    # Check if watcher is enabled
                    if not state.enabled:
                        logger.debug("Watcher is paused, skipping alerts")
                        time.sleep(min_coin_interval)
                        continue
                    
                    # Check mute
                    if coin in state.muted_coins:
                        unmute_time = state.muted_coins[coin]
                        if time.time() < unmute_time:
                            logger.debug(f"Coin {coin} is muted until {unmute_time}")
                            time.sleep(min_coin_interval)
                            continue
                        else:
                            # Expired mute, clean up
                            state.muted_coins.pop(coin)
                    
                    # Check spam guard
                    if current_time - state.last_proposal_time < self.settings.telegram_spam_guard_sec:
                        logger.debug("Spam guard: skipping proposal")
                        time.sleep(min_coin_interval)
                        continue
                    
                    # Check each side with debouncing
                    for side_info in safe_sides:
                        side = side_info["side"]
                        if not score_result.passed:
                            continue
                        
                        alert_key = f"{coin}_{side}"
                        
                        # Check debouncing/hysteresis
                        if not self._should_trigger_alert(alert_key, score_result.total_score, 80.0):
                            continue
                        
                        # Check per-coin+side cooldown
                        last_alert = state.last_alert_ts.get(alert_key, 0)
                        if current_time - last_alert < state.config.cooldown_sec:
                            continue
                        
                        # Check global rate limit
                        if not self._check_rate_limit():
                            logger.warning("Global rate limit reached, skipping alert")
                            continue
                        
                        # Get limit prices from side_info
                        open_limit_px = side_info.get("open_limit_px", 0)
                        close_limit_px = side_info.get("close_limit_px", 0)
                        
                        # Estimate fill probabilities
                        spread_bps = score_result.metrics.get("spread_bps", 0)
                        depth_top = score_result.metrics.get("depth_top", 5000.0)
                        notional = 1000.0  # Default assumption, could be from config
                        
                        fill_prob_open = self.fill_model.estimate_fill_prob(
                            coin, spread_bps, depth_top, notional,
                            state.config.open_offset_bps
                        )
                        fill_prob_close = self.fill_model.estimate_fill_prob(
                            coin, spread_bps, depth_top, notional,
                            state.config.close_offset_bps
                        )
                        
                        # Create proposal and send interactive message
                        if state.config.telegram_enabled and self.telegram_client.enabled:
                            # Build snapshot for proposal
                            snapshot = {
                                "score": score_result.total_score,
                                "reasons": score_result.reasons,
                                "metrics": score_result.metrics,
                                "fill_probs": {
                                    "open": fill_prob_open,
                                    "close": fill_prob_close,
                                },
                            }
                            
                            # Get plan defaults from state
                            app_state = self.state_store.load()
                            
                            # Create proposal
                            proposal = create_proposal_from_snapshot(
                                snapshot,
                                coin,
                                side,
                                {
                                    "margin": app_state.plan.default_margin,
                                    "leverage": app_state.plan.default_leverage,
                                    "hold_min": 60,
                                    "fee_mode": "maker",
                                    "funding_kind": state.config.funding_kind,
                                    "open_offset_bps": state.config.open_offset_bps,
                                    "close_offset_bps": state.config.close_offset_bps,
                                },
                                self.settings,
                            )
                            
                            # Store proposal in state (already loaded above)
                            app_state.proposals[proposal.id] = proposal
                            self.state_store.save(app_state)
                            
                            # Format and send message
                            text, reply_markup = format_proposal_message(proposal, self.settings)
                            
                            if self.telegram_client.send_message(text, reply_markup=reply_markup):
                                # Store message_id and chat_id in proposal
                                proposal.chat_id = int(self.telegram_client.chat_id) if self.telegram_client.chat_id else None
                                
                                state.last_alert_ts[alert_key] = current_time
                                state.last_proposal_time = current_time
                                self._alert_times.append(current_time)
                                state.last_alerts.append({
                                    "coin": coin,
                                    "side": side,
                                    "timestamp": datetime.now(timezone.utc).isoformat(),
                                    "timestamp_ts": current_time,
                                    "score": score_result.total_score,
                                    "reasons": score_result.reasons,
                                    "proposal_id": proposal.id,
                                })
                                logger.info(f"Proposal sent: {coin} {side} (score: {score_result.total_score:.1f}, proposal: {proposal.id})")
                        
                        # Update snapshot
                        state.last_safe_snapshot[coin] = {
                            "score": score_result.total_score,
                            "metrics": score_result.metrics,
                            "reasons": score_result.reasons,
                        }
                    
                    time.sleep(min_coin_interval)
                
                # Update last poll time and snapshot
                state.last_poll_time = datetime.now(timezone.utc).isoformat()
                self._last_snapshot = snapshot
                self.save_state()
                
                # Sleep until next poll cycle
                elapsed = time.time() - current_time
                sleep_time = max(0, state.config.poll_interval_sec - elapsed)
                time.sleep(sleep_time)
                
            except Exception as e:
                logger.error(f"Error in watch poll loop: {e}", exc_info=True)
                time.sleep(state.config.poll_interval_sec)
