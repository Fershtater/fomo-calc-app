"""Proposal management service."""

import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional, Tuple

from ..models.domain import Proposal, ProposalStatus, State, Trade
from ..settings import Settings

logger = logging.getLogger(__name__)


def create_proposal_from_snapshot(
    snapshot: Dict,
    coin: str,
    side: str,
    config: Dict,
    settings: Settings,
) -> Proposal:
    """Create a Proposal from a watcher snapshot.
    
    Args:
        snapshot: Snapshot dict with score, metrics, etc.
        coin: Coin symbol
        side: "LONG" or "SHORT"
        config: WatchConfig or dict with margin, leverage, hold_min, etc.
        settings: Settings instance
    
    Returns:
        Proposal instance
    """
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=settings.proposal_expiry_minutes)
    
    proposal_id = f"{coin}_{side}_{int(now.timestamp())}"
    
    # Extract data from snapshot
    score = snapshot.get("score", 0.0)
    metrics = snapshot.get("metrics", {})
    reasons = snapshot.get("reasons", [])
    
    # Get suggested prices from metrics safe_sides
    safe_sides = metrics.get("safe_sides", [])
    side_info = next((s for s in safe_sides if s.get("side") == side), {})
    
    suggested_prices = {
        "open_limit_px": side_info.get("open_limit_px", 0),
        "close_limit_px": side_info.get("close_limit_px", 0),
        "best_bid": side_info.get("best_bid", metrics.get("best_bid", 0)),
        "best_ask": side_info.get("best_ask", metrics.get("best_ask", 0)),
    }
    
    offsets = {
        "open_offset_bps": config.get("open_offset_bps", 0.0),
        "close_offset_bps": config.get("close_offset_bps", 0.0),
    }
    
    fill_probs = {
        "open_fill_prob": snapshot.get("fill_probs", {}).get("open", 0.8),
        "close_fill_prob": snapshot.get("fill_probs", {}).get("close", 0.8),
    }
    
    margin = config.get("margin", 100.0)
    leverage = config.get("leverage", 10.0)
    hold_min = config.get("hold_min", 60)
    fee_mode = config.get("fee_mode", "maker")
    funding_kind = config.get("funding_kind", "hourly")
    
    funding_raw = metrics.get("funding", 0)
    funding_hourly = metrics.get("funding_hourly", funding_raw)
    
    return Proposal(
        id=proposal_id,
        coin=coin,
        side=side,
        score=score,
        reasons=reasons,
        metrics=metrics,
        suggested_prices=suggested_prices,
        offsets=offsets,
        fill_probs=fill_probs,
        margin=margin,
        leverage=leverage,
        hold_min=hold_min,
        fee_mode=fee_mode,
        funding_kind=funding_kind,
        funding_raw=funding_raw,
        funding_hourly=funding_hourly,
        created_at=now.isoformat(),
        expires_at=expires_at.isoformat(),
        status=ProposalStatus.PENDING.value,
    )


def format_proposal_message(proposal: Proposal, settings: Settings) -> Tuple[str, Dict]:
    """Format proposal message text and inline keyboard.
    
    Args:
        proposal: Proposal instance
        settings: Settings instance
    
    Returns:
        Tuple of (message_text, reply_markup_dict)
    """
    now = datetime.now(timezone.utc)
    expires = datetime.fromisoformat(proposal.expires_at.replace("Z", "+00:00"))
    expires_in = int((expires - now).total_seconds() / 60)
    
    msg_parts = [
        f"<b>📊 Trade Proposal: {proposal.coin} {proposal.side}</b>",
        f"<code>ID: {proposal.id}</code>",
        "",
        f"<b>Score:</b> {proposal.score:.0f}/100",
        f"<b>Reasons:</b> {', '.join(proposal.reasons[:3]) if proposal.reasons else 'All metrics OK'}",
        "",
        "<b>Suggested Limits:</b>",
        f"Open: ${proposal.suggested_prices.get('open_limit_px', 0):.4f}",
        f"  (offset: {proposal.offsets.get('open_offset_bps', 0):.1f} bps, fill prob: {proposal.fill_probs.get('open_fill_prob', 0):.1%})",
        f"Close: ${proposal.suggested_prices.get('close_limit_px', 0):.4f}",
        f"  (offset: {proposal.offsets.get('close_offset_bps', 0):.1f} bps, fill prob: {proposal.fill_probs.get('close_fill_prob', 0):.1%})",
        "",
        "<b>Parameters:</b>",
        f"Margin: ${proposal.margin:.2f} | Leverage: {proposal.leverage}x",
        f"Notional: ${proposal.margin * proposal.leverage:,.2f} | Hold: {proposal.hold_min} min",
        f"Fee Mode: {proposal.fee_mode.upper()}",
        "",
        "<b>Key Metrics:</b>",
        f"Spread: {proposal.metrics.get('spread_bps', 0):.2f} bps",
        f"Oracle Dev: {proposal.metrics.get('oracle_dev_bps', 0):.2f} bps",
        f"Funding (1h): {proposal.funding_hourly:.6f}",
        f"24h Volume: ${proposal.metrics.get('liquidity', 0):,.0f}",
        f"Bid: ${proposal.suggested_prices.get('best_bid', 0):.4f} | Ask: ${proposal.suggested_prices.get('best_ask', 0):.4f}",
        "",
        f"<i>Expires: {expires.strftime('%H:%M:%S')} UTC ({expires_in} min) | Created: {proposal.created_at[:19]} UTC</i>",
        "",
        "<i>⚠️ Paper-only. No trading executed.</i>",
    ]
    
    # Inline keyboard with improved buttons
    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "✅ Accept", "callback_data": f"ACCEPT:{proposal.id}"},
                {"text": "❌ Reject", "callback_data": f"REJECT:{proposal.id}"},
            ],
            [
                {"text": "⏸ Pause", "callback_data": "PAUSE"},
                {"text": "▶️ Resume", "callback_data": "RESUME"},
            ],
            [
                {"text": f"🔕 Mute {proposal.coin} 60m", "callback_data": f"MUTE:{proposal.coin}:60"},
                {"text": "🔄 Next", "callback_data": "NEXT"},
            ],
        ]
    }
    
    return "\n".join(msg_parts), reply_markup


def accept_proposal(
    state: State,
    proposal_id: str,
    actor_user_id: int,
    settings: Settings,
) -> Optional[Trade]:
    """Accept a proposal and create a Trade record (idempotent).
    
    Args:
        state: Application state
        proposal_id: Proposal ID
        actor_user_id: Telegram user ID who accepted
        settings: Settings instance
    
    Returns:
        Created Trade or None if proposal not found/invalid/already handled
    """
    proposal = state.proposals.get(proposal_id)
    if not proposal:
        logger.warning(f"Proposal {proposal_id} not found")
        return None
    
    # Idempotency check: if already decided, return None
    if proposal.status != ProposalStatus.PENDING.value:
        logger.info(f"Proposal {proposal_id} already {proposal.status}, ignoring duplicate accept")
        return None
    
    # Check expiry
    now = datetime.now(timezone.utc)
    expires = datetime.fromisoformat(proposal.expires_at.replace("Z", "+00:00"))
    if now > expires:
        proposal.status = ProposalStatus.EXPIRED.value
        proposal.decided_at_utc = now.isoformat()
        proposal.decided_by_user_id = actor_user_id
        proposal.decision = "EXPIRED"
        logger.warning(f"Proposal {proposal_id} expired")
        return None
    
    # Update proposal with decision tracking
    proposal.status = ProposalStatus.ACCEPTED.value
    proposal.decided_at_utc = now.isoformat()
    proposal.decided_by_user_id = actor_user_id
    proposal.decision = "ACCEPT"
    
    # Create trade
    notional = proposal.margin * proposal.leverage
    
    # Calculate fees (simplified, could use calc service)
    taker_fee = settings.default_taker_fee
    maker_fee = settings.default_maker_fee
    
    open_fee_mode = "maker" if proposal.fee_mode == "maker" or proposal.fee_mode == "both" else "taker"
    close_fee_mode = "maker" if proposal.fee_mode == "maker" else ("maker" if proposal.fee_mode == "both" else "taker")
    
    open_fee = notional * (maker_fee if open_fee_mode == "maker" else taker_fee)
    close_fee = notional * (maker_fee if close_fee_mode == "maker" else taker_fee)
    expected_fees = open_fee + close_fee
    
    # Calculate funding PnL (simplified)
    from .calc import calculate_funding_pnl
    from ..models.domain import FundingKind
    
    funding_kind = FundingKind.HOURLY if proposal.funding_kind == "hourly" else FundingKind.EIGHT_HOUR
    expected_funding_pnl = calculate_funding_pnl(
        proposal.side,
        notional,
        proposal.funding_hourly,
        proposal.hold_min,
        funding_kind,
    )
    
    trade = Trade(
        id=proposal_id.replace("_", "_TRADE_"),
        coin=proposal.coin,
        side=proposal.side,
        leverage=proposal.leverage,
        margin=proposal.margin,
        notional=notional,
        open_timestamp=now.isoformat(),
        planned_hold_min=proposal.hold_min,
        expected_fees=expected_fees,
        expected_funding_pnl=expected_funding_pnl,
        open_price=proposal.suggested_prices.get("open_limit_px"),
        open_limit_px=proposal.suggested_prices.get("open_limit_px"),
        close_limit_px=proposal.suggested_prices.get("close_limit_px"),
        fill_prob=(proposal.fill_probs.get("open_fill_prob", 0.8) + proposal.fill_probs.get("close_fill_prob", 0.8)) / 2.0,
        open_fee_mode=open_fee_mode,
        close_fee_mode=close_fee_mode,
    )
    
    state.trades.append(trade)
    logger.info(f"Proposal {proposal_id} accepted by user {actor_user_id}, created trade {trade.id}")
    
    return trade


def reject_proposal(
    state: State,
    proposal_id: str,
    actor_user_id: int,
) -> bool:
    """Reject a proposal (idempotent).
    
    Args:
        state: Application state
        proposal_id: Proposal ID
        actor_user_id: Telegram user ID who rejected
    
    Returns:
        True if successful, False if already handled
    """
    proposal = state.proposals.get(proposal_id)
    if not proposal:
        logger.warning(f"Proposal {proposal_id} not found")
        return False
    
    # Idempotency check
    if proposal.status != ProposalStatus.PENDING.value:
        logger.info(f"Proposal {proposal_id} already {proposal.status}, ignoring duplicate reject")
        return False
    
    # Update proposal with decision tracking
    now = datetime.now(timezone.utc)
    proposal.status = ProposalStatus.REJECTED.value
    proposal.decided_at_utc = now.isoformat()
    proposal.decided_by_user_id = actor_user_id
    proposal.decision = "REJECT"
    logger.info(f"Proposal {proposal_id} rejected by user {actor_user_id}")
    
    return True


def expire_proposals(state: State) -> int:
    """Expire old proposals.
    
    Args:
        state: Application state
    
    Returns:
        Number of proposals expired
    """
    now = datetime.now(timezone.utc)
    expired_count = 0
    
    for proposal in state.proposals.values():
        if proposal.status == ProposalStatus.PENDING.value:
            expires = datetime.fromisoformat(proposal.expires_at.replace("Z", "+00:00"))
            if now > expires:
                proposal.status = ProposalStatus.EXPIRED.value
                expired_count += 1
    
    if expired_count > 0:
        logger.info(f"Expired {expired_count} proposals")
    
    return expired_count

