"""Tests for Telegram control plane."""

import pytest
from datetime import datetime, timezone

from farmcalc.models.domain import Proposal, ProposalStatus, State, WatchState
from farmcalc.services.proposals import accept_proposal, reject_proposal
from farmcalc.services.telegram_control import is_owner
from farmcalc.settings import Settings


@pytest.fixture
def settings_with_owner():
    """Settings with owner ID."""
    settings = Settings()
    settings.telegram_owner_id = 123456789
    settings.telegram_allowed_chat_id = None
    return settings


@pytest.fixture
def settings_with_chat_restriction():
    """Settings with owner ID and chat restriction."""
    settings = Settings()
    settings.telegram_owner_id = 123456789
    settings.telegram_allowed_chat_id = "-987654321"
    return settings


def test_is_owner_valid(settings_with_owner):
    """Test owner check with valid owner ID."""
    assert is_owner(123456789, None, settings_with_owner) is True
    assert is_owner(123456789, -123456789, settings_with_owner) is True


def test_is_owner_invalid(settings_with_owner):
    """Test owner check with invalid owner ID."""
    assert is_owner(999999999, None, settings_with_owner) is False


def test_is_owner_chat_restriction(settings_with_chat_restriction):
    """Test owner check with chat ID restriction."""
    # Valid owner, valid chat
    assert is_owner(123456789, -987654321, settings_with_chat_restriction) is True
    
    # Valid owner, wrong chat
    assert is_owner(123456789, -111111111, settings_with_chat_restriction) is False
    
    # Invalid owner, valid chat
    assert is_owner(999999999, -987654321, settings_with_chat_restriction) is False


def test_accept_proposal_idempotent():
    """Test that accepting a proposal twice is idempotent."""
    from farmcalc.services.proposals import accept_proposal
    from farmcalc.settings import Settings
    
    settings = Settings()
    settings.default_taker_fee = 0.00045
    settings.default_maker_fee = 0.00015
    
    state = State(
        plan=Plan(),
        stats=Stats(),
        trades=[],
        proposals={},
    )
    
    # Create a proposal
    proposal = Proposal(
        id="TEST_BTC_LONG_123",
        coin="BTC",
        side="LONG",
        score=85.0,
        reasons=["spread ok"],
        metrics={},
        suggested_prices={"open_limit_px": 100.0, "close_limit_px": 101.0},
        offsets={"open_offset_bps": 10.0, "close_offset_bps": 10.0},
        fill_probs={"open_fill_prob": 0.8, "close_fill_prob": 0.8},
        margin=100.0,
        leverage=10.0,
        hold_min=60,
        fee_mode="maker",
        funding_kind="hourly",
        funding_raw=0.00001,
        funding_hourly=0.00001,
        created_at=datetime.now(timezone.utc).isoformat(),
        expires_at=(datetime.now(timezone.utc).replace(second=0, microsecond=0) + timedelta(minutes=15)).isoformat(),
        status=ProposalStatus.PENDING.value,
    )
    
    state.proposals[proposal.id] = proposal
    
    # First accept
    trade1 = accept_proposal(state, proposal.id, 123456789, settings)
    assert trade1 is not None
    assert proposal.status == ProposalStatus.ACCEPTED.value
    assert proposal.decision == "ACCEPT"
    
    # Second accept (should be idempotent)
    trade2 = accept_proposal(state, proposal.id, 123456789, settings)
    assert trade2 is None  # Already handled
    assert proposal.status == ProposalStatus.ACCEPTED.value  # Still accepted


def test_reject_proposal_idempotent():
    """Test that rejecting a proposal twice is idempotent."""
    from farmcalc.services.proposals import reject_proposal
    
    state = State(
        plan=Plan(),
        stats=Stats(),
        trades=[],
        proposals={},
    )
    
    proposal = Proposal(
        id="TEST_BTC_LONG_123",
        coin="BTC",
        side="LONG",
        score=85.0,
        reasons=[],
        metrics={},
        suggested_prices={},
        offsets={},
        fill_probs={},
        margin=100.0,
        leverage=10.0,
        hold_min=60,
        fee_mode="maker",
        funding_kind="hourly",
        funding_raw=0.0,
        funding_hourly=0.0,
        created_at=datetime.now(timezone.utc).isoformat(),
        expires_at=(datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(),
        status=ProposalStatus.PENDING.value,
    )
    
    state.proposals[proposal.id] = proposal
    
    # First reject
    result1 = reject_proposal(state, proposal.id, 123456789)
    assert result1 is True
    assert proposal.status == ProposalStatus.REJECTED.value
    assert proposal.decision == "REJECT"
    
    # Second reject (should be idempotent)
    result2 = reject_proposal(state, proposal.id, 123456789)
    assert result2 is False  # Already handled
    assert proposal.status == ProposalStatus.REJECTED.value  # Still rejected

