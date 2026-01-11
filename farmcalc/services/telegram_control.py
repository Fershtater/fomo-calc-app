"""Telegram update handling and control plane (single-user)."""

import logging
import time
from datetime import datetime, timezone
from typing import Dict, Optional

from ..clients.telegram import TelegramClient
from ..models.domain import ProposalStatus, State, WatchState
from ..services.proposals import (
    accept_proposal,
    expire_proposals,
    format_proposal_message,
    reject_proposal,
)
from ..settings import Settings
from ..storage.state_store import StateStore, WatchStateStore

logger = logging.getLogger(__name__)


def is_owner(user_id: int, chat_id: Optional[int], settings: Settings) -> bool:
    """Check if user is the owner and chat is allowed.
    
    Args:
        user_id: Telegram user ID
        chat_id: Chat ID (optional)
        settings: Settings instance
    
    Returns:
        True if user is owner and chat is allowed
    """
    # Check owner ID
    if not settings.telegram_owner_id or user_id != settings.telegram_owner_id:
        return False
    
    # Check chat ID restriction if set
    if settings.telegram_allowed_chat_id:
        chat_id_str = str(chat_id) if chat_id else None
        if chat_id_str != settings.telegram_allowed_chat_id:
            return False
    
    return True


def get_user_id_from_update(update: Dict) -> Optional[int]:
    """Extract user ID from Telegram update.
    
    Args:
        update: Telegram update dict
    
    Returns:
        User ID or None
    """
    # From message
    if "message" in update:
        from_user = update["message"].get("from", {})
        return from_user.get("id")
    
    # From callback_query
    if "callback_query" in update:
        from_user = update["callback_query"].get("from", {})
        return from_user.get("id")
    
    return None


def get_chat_id_from_update(update: Dict) -> Optional[int]:
    """Extract chat ID from Telegram update.
    
    Args:
        update: Telegram update dict
    
    Returns:
        Chat ID or None
    """
    # From message
    if "message" in update:
        return update["message"].get("chat", {}).get("id")
    
    # From callback_query
    if "callback_query" in update:
        message = update["callback_query"].get("message", {})
        return message.get("chat", {}).get("id")
    
    return None


def get_username_from_update(update: Dict) -> Optional[str]:
    """Extract username from Telegram update.
    
    Args:
        update: Telegram update dict
    
    Returns:
        Username or None
    """
    # From message
    if "message" in update:
        from_user = update["message"].get("from", {})
        return from_user.get("username")
    
    # From callback_query
    if "callback_query" in update:
        from_user = update["callback_query"].get("from", {})
        return from_user.get("username")
    
    return None


def handle_message(
    update: Dict,
    state_store: StateStore,
    watch_state_store: WatchStateStore,
    telegram_client: TelegramClient,
    settings: Settings,
    watcher_service=None,
) -> bool:
    """Handle incoming message (commands).
    
    Args:
        update: Telegram update dict
        state_store: State store
        watch_state_store: Watch state store
        telegram_client: Telegram client
        settings: Settings instance
        watcher_service: Optional WatcherService instance
    
    Returns:
        True if handled
    """
    message = update.get("message", {})
    text = message.get("text", "")
    chat_id = message.get("chat", {}).get("id")
    user_id = get_user_id_from_update(update)
    username = get_username_from_update(update)
    
    if not text.startswith("/"):
        return False
    
    # Check owner
    if not is_owner(user_id, chat_id, settings):
        telegram_client.send_message(
            "❌ Unauthorized. Only the owner can use this bot.",
            chat_id=chat_id,
        )
        return True
    
    command_parts = text.split()
    command = command_parts[0].lower()
    
    if command == "/whoami":
        # Determine bot mode
        webhook_info = telegram_client.get_webhook_info()
        bot_mode = "webhook" if webhook_info and webhook_info.get("url") else "polling"
        
        watch_state = watch_state_store.load()
        
        msg = (
            f"<b>👤 User Info</b>\n\n"
            f"<b>User ID:</b> <code>{user_id}</code>\n"
            f"<b>Chat ID:</b> <code>{chat_id}</code>\n"
            f"<b>Username:</b> @{username if username else 'N/A'}\n"
            f"<b>Bot Mode:</b> {bot_mode}\n"
            f"<b>Watcher Running:</b> {'🟢 Yes' if watch_state.is_running else '🔴 No'}\n"
            f"<b>Watcher Enabled:</b> {'✅ Yes' if watch_state.enabled else '⏸ Paused'}\n"
        )
        telegram_client.send_message(msg, chat_id=chat_id)
        return True
    
    if command == "/status":
        state = state_store.load()
        watch_state = watch_state_store.load()
        
        active_trades = [t for t in state.trades if t.close_price is None]
        pending_proposals = [
            p for p in state.proposals.values()
            if p.status == ProposalStatus.PENDING.value
        ]
        
        # Count alerts in last hour
        now = time.time()
        alerts_last_hour = sum(
            1 for alert in watch_state.last_alerts
            if now - alert.get("timestamp_ts", 0) < 3600
        )
        
        msg_parts = [
            "<b>📊 FarmCalc Status</b>",
            "",
            "<b>Watcher:</b>",
            f"Running: {'🟢 Yes' if watch_state.is_running else '🔴 No'}",
            f"Enabled: {'✅ Yes' if watch_state.enabled else '⏸ Paused'}",
            f"Poll Interval: {watch_state.config.poll_interval_sec}s",
            f"Top N: {watch_state.config.top_n}",
            f"Score Threshold: {watch_state.config.thresholds.spread_max_bps:.1f} bps spread",
            f"Last Tick: {watch_state.last_poll_time or 'Never'}",
            f"Alerts (1h): {alerts_last_hour}",
            "",
            "<b>Plan Progress:</b>",
            f"Total Volume: ${state.stats.total_volume_done:,.2f}",
            f"Remaining: ${max(0, state.plan.target_volume - state.stats.total_volume_done):,.2f}",
            f"Frozen Remaining: ${state.stats.frozen_remaining:,.2f}",
            f"FOMO Minted Est: {state.stats.estimated_fomo_minted:.2f}",
            "",
            f"<b>Active Trades:</b> {len(active_trades)}",
            f"<b>Pending Proposals:</b> {len(pending_proposals)}",
            "",
            f"<b>Total Fees:</b> ${state.stats.total_fees:.2f}",
            f"<b>Funding PnL:</b> ${state.stats.total_funding_pnl:.2f}",
        ]
        
        telegram_client.send_message("\n".join(msg_parts), chat_id=chat_id)
        return True
    
    if command == "/pause":
        watch_state_store.update_atomic(lambda ws: setattr(ws, "enabled", False))
        telegram_client.send_message(
            "⏸ Watcher paused. Use /resume to resume.",
            chat_id=chat_id,
        )
        logger.info(f"Watcher paused by user {user_id}")
        return True
    
    if command == "/resume":
        watch_state_store.update_atomic(lambda ws: setattr(ws, "enabled", True))
        telegram_client.send_message(
            "▶️ Watcher resumed.",
            chat_id=chat_id,
        )
        logger.info(f"Watcher resumed by user {user_id}")
        return True
    
    if command == "/mute":
        if len(command_parts) < 2:
            telegram_client.send_message(
                "Usage: /mute <COIN> [minutes]\nExample: /mute BTC 60",
                chat_id=chat_id,
            )
            return True
        
        coin = command_parts[1].upper()
        minutes = int(command_parts[2]) if len(command_parts) > 2 and command_parts[2].isdigit() else 60
        
        unmute_time = time.time() + (minutes * 60)
        
        def update_mute(ws: WatchState):
            ws.muted_coins[coin] = unmute_time
        
        watch_state_store.update_atomic(update_mute)
        
        telegram_client.send_message(
            f"🔕 Muted {coin} for {minutes} minutes.",
            chat_id=chat_id,
        )
        return True
    
    if command == "/unmute":
        if len(command_parts) < 2:
            telegram_client.send_message(
                "Usage: /unmute <COIN>\nExample: /unmute BTC",
                chat_id=chat_id,
            )
            return True
        
        coin = command_parts[1].upper()
        
        def remove_mute(ws: WatchState):
            ws.muted_coins.pop(coin, None)
        
        watch_state_store.update_atomic(remove_mute)
        
        telegram_client.send_message(
            f"🔔 Unmuted {coin}.",
            chat_id=chat_id,
        )
        return True
    
    if command == "/mutes":
        watch_state = watch_state_store.load()
        now = time.time()
        
        active_mutes = []
        for coin, unmute_time in watch_state.muted_coins.items():
            if unmute_time > now:
                minutes_left = int((unmute_time - now) / 60)
                active_mutes.append(f"{coin}: {minutes_left}m")
        
        if active_mutes:
            msg = "<b>🔕 Active Mutes:</b>\n" + "\n".join(active_mutes)
        else:
            msg = "No active mutes."
        
        telegram_client.send_message(msg, chat_id=chat_id)
        return True
    
    if command == "/history":
        n = int(command_parts[1]) if len(command_parts) > 1 and command_parts[1].isdigit() else 10
        state = state_store.load()
        
        proposals = sorted(
            state.proposals.values(),
            key=lambda p: p.created_at,
            reverse=True,
        )[:n]
        
        if not proposals:
            telegram_client.send_message("No proposals found.", chat_id=chat_id)
            return True
        
        msg_parts = [f"<b>📜 Last {len(proposals)} Proposals:</b>", ""]
        for prop in proposals:
            status_emoji = {
                ProposalStatus.PENDING.value: "⏳",
                ProposalStatus.ACCEPTED.value: "✅",
                ProposalStatus.REJECTED.value: "❌",
                ProposalStatus.EXPIRED.value: "⏰",
            }.get(prop.status, "❓")
            
            msg_parts.append(
                f"{status_emoji} {prop.coin} {prop.side} | Score: {prop.score:.0f} | {prop.created_at[:19]}"
            )
        
        telegram_client.send_message("\n".join(msg_parts), chat_id=chat_id)
        return True
    
    if command == "/next":
        if not watcher_service:
            telegram_client.send_message(
                "❌ Watcher service not available.",
                chat_id=chat_id,
            )
            return True
        
        # Force evaluation
        try:
            snapshot = watcher_service.evaluate_now()
            if snapshot:
                # Get best candidate
                best = max(
                    snapshot.items(),
                    key=lambda x: x[1].get("score", 0),
                )
                coin, data = best
                
                telegram_client.send_message(
                    f"<b>🔄 Best Current Candidate:</b>\n\n"
                    f"<b>{coin}</b>\n"
                    f"Score: {data.get('score', 0):.0f}/100\n"
                    f"Reasons: {', '.join(data.get('reasons', [])[:3])}",
                    chat_id=chat_id,
                )
            else:
                telegram_client.send_message(
                    "No safe entry candidates found at this time.",
                    chat_id=chat_id,
                )
        except Exception as e:
            logger.error(f"Error in /next: {e}", exc_info=True)
            telegram_client.send_message(
                f"❌ Error: {str(e)}",
                chat_id=chat_id,
            )
        return True
    
    return False


def handle_callback_query(
    update: Dict,
    state_store: StateStore,
    watch_state_store: WatchStateStore,
    telegram_client: TelegramClient,
    settings: Settings,
) -> bool:
    """Handle callback query (button presses).
    
    Args:
        update: Telegram update dict
        state_store: State store
        watch_state_store: Watch state store
        telegram_client: Telegram client
        settings: Settings instance
    
    Returns:
        True if handled
    """
    callback_query = update.get("callback_query", {})
    callback_data = callback_query.get("data", "")
    callback_id = callback_query.get("id")
    user_id = get_user_id_from_update(update)
    chat_id = get_chat_id_from_update(update)
    message = callback_query.get("message", {})
    message_id = message.get("message_id")
    
    # Check owner
    if not is_owner(user_id, chat_id, settings):
        telegram_client.answer_callback_query(
            callback_id,
            text="❌ Unauthorized. Only the owner can use this bot.",
            show_alert=True,
        )
        return True
    
    # Always answer callback query
    telegram_client.answer_callback_query(callback_id)
    
    # Parse callback data
    if callback_data.startswith("ACCEPT:"):
        proposal_id = callback_data.split(":", 1)[1]
        
        trade_result = [None]
        proposal_result = [None]
        
        def accept_and_update(state: State):
            trade = accept_proposal(state, proposal_id, user_id, settings)
            trade_result[0] = trade
            proposal_result[0] = state.proposals.get(proposal_id)
        
        # Use atomic update
        state_store.update_atomic(accept_and_update)
        trade = trade_result[0]
        proposal = proposal_result[0]
        
        if trade and proposal:
            # Update message
            text, _ = format_proposal_message(proposal, settings)
            now = datetime.now(timezone.utc)
            text = f"✅ <b>ACCEPTED</b> at {now.strftime('%H:%M:%S')} UTC\n\n{text}"
            
            telegram_client.edit_message_text(
                text,
                chat_id=chat_id,
                message_id=message_id,
                reply_markup={"inline_keyboard": [
                    [{"text": "🔄 Next", "callback_data": "NEXT"}],
                    [{"text": "📊 Status", "callback_data": "STATUS"}],
                ]},
            )
            logger.info(f"Proposal {proposal_id} accepted via Telegram")
        else:
            # Already handled or expired
            if proposal and proposal.status != ProposalStatus.PENDING.value:
                status_text = {
                    ProposalStatus.ACCEPTED.value: "✅ Already accepted",
                    ProposalStatus.REJECTED.value: "❌ Already rejected",
                    ProposalStatus.EXPIRED.value: "⏰ Expired",
                }.get(proposal.status, "Already handled")
                
                telegram_client.answer_callback_query(
                    callback_id,
                    text=status_text,
                    show_alert=True,
                )
        
        return True
    
    if callback_data.startswith("REJECT:"):
        proposal_id = callback_data.split(":", 1)[1]
        
        success_result = [False]
        proposal_result = [None]
        
        def reject_and_update(state: State):
            success = reject_proposal(state, proposal_id, user_id)
            success_result[0] = success
            proposal_result[0] = state.proposals.get(proposal_id)
        
        # Use atomic update
        state_store.update_atomic(reject_and_update)
        success = success_result[0]
        proposal = proposal_result[0]
        
        if success and proposal:
            # Update message
            text, _ = format_proposal_message(proposal, settings)
            now = datetime.now(timezone.utc)
            text = f"❌ <b>REJECTED</b> at {now.strftime('%H:%M:%S')} UTC\n\n{text}"
            
            telegram_client.edit_message_text(
                text,
                chat_id=chat_id,
                message_id=message_id,
                reply_markup={"inline_keyboard": [
                    [{"text": "🔄 Next", "callback_data": "NEXT"}],
                    [{"text": "📊 Status", "callback_data": "STATUS"}],
                ]},
            )
            logger.info(f"Proposal {proposal_id} rejected via Telegram")
        else:
            if proposal and proposal.status != ProposalStatus.PENDING.value:
                status_text = {
                    ProposalStatus.ACCEPTED.value: "✅ Already accepted",
                    ProposalStatus.REJECTED.value: "❌ Already rejected",
                    ProposalStatus.EXPIRED.value: "⏰ Expired",
                }.get(proposal.status, "Already handled")
                
                telegram_client.answer_callback_query(
                    callback_id,
                    text=status_text,
                    show_alert=True,
                )
        
        return True
    
    if callback_data == "PAUSE":
        watch_state_store.update_atomic(lambda ws: setattr(ws, "enabled", False))
        telegram_client.answer_callback_query(
            callback_id,
            text="⏸ Watcher paused",
        )
        logger.info(f"Watcher paused via Telegram by user {user_id}")
        return True
    
    if callback_data == "RESUME":
        watch_state_store.update_atomic(lambda ws: setattr(ws, "enabled", True))
        telegram_client.answer_callback_query(
            callback_id,
            text="▶️ Watcher resumed",
        )
        logger.info(f"Watcher resumed via Telegram by user {user_id}")
        return True
    
    if callback_data.startswith("MUTE:"):
        parts = callback_data.split(":")
        if len(parts) >= 3:
            coin = parts[1]
            minutes = int(parts[2]) if parts[2].isdigit() else 60
            unmute_time = time.time() + (minutes * 60)
            
            watch_state_store.update_atomic(
                lambda ws: ws.muted_coins.update({coin: unmute_time})
            )
            
            telegram_client.answer_callback_query(
                callback_id,
                text=f"🔕 Muted {coin} for {minutes}m",
            )
        return True
    
    if callback_data == "NEXT":
        telegram_client.answer_callback_query(
            callback_id,
            text="Use /next command for best candidate",
        )
        return True
    
    if callback_data == "STATUS":
        telegram_client.answer_callback_query(
            callback_id,
            text="Use /status command for detailed status",
        )
        return True
    
    return False


def process_update(
    update: Dict,
    state_store: StateStore,
    watch_state_store: WatchStateStore,
    telegram_client: TelegramClient,
    settings: Settings,
    watcher_service=None,
) -> bool:
    """Process a Telegram update.
    
    Args:
        update: Telegram update dict
        state_store: State store
        watch_state_store: Watch state store
        telegram_client: Telegram client
        settings: Settings instance
        watcher_service: Optional WatcherService instance
    
    Returns:
        True if update was handled
    """
    # Expire old proposals first
    state_store.update_atomic(lambda s: expire_proposals(s))
    
    # Handle callback queries
    if "callback_query" in update:
        return handle_callback_query(
            update, state_store, watch_state_store, telegram_client, settings
        )
    
    # Handle messages (commands)
    if "message" in update:
        return handle_message(
            update, state_store, watch_state_store, telegram_client, settings, watcher_service
        )
    
    return False
