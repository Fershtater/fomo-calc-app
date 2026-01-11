"""State persistence for farmcalc."""

import fcntl
import json
import logging
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Callable, List, Optional

from ..models.domain import Plan, Proposal, ProposalStatus, State, Stats, Trade, WatchConfig, WatchState, WatchThresholds

logger = logging.getLogger(__name__)


class StateStore:
    """Manages persistence of farmcalc state with atomic updates."""
    
    def __init__(self, state_path: Path):
        """Initialize with state file path."""
        self.state_path = state_path
        self.lock_path = state_path.with_suffix(state_path.suffix + ".lock")
    
    @contextmanager
    def _lock(self):
        """Acquire file lock for atomic updates."""
        lock_file = open(self.lock_path, "w")
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            lock_file.close()
    
    def update_atomic(self, fn: Callable[[State], None]):
        """Update state atomically with file locking.
        
        Args:
            fn: Function that takes State and modifies it in place
        """
        with self._lock():
            state = self.load()
            fn(state)
            self.save(state)
    
    def load(self) -> State:
        """Load state from JSON file."""
        if self.state_path.exists():
            try:
                with open(self.state_path, "r") as f:
                    data = json.load(f)
                    plan = Plan(**data.get("plan", {}))
                    stats = Stats(**data.get("stats", {}))
                    trades = [Trade(**t) for t in data.get("trades", [])]
                    
                    # Handle schema version for migrations
                    schema_version = data.get("schema_version", 1)
                    
                    # Migration from v1 to v2: add proposals and watcher_enabled
                    if schema_version < 2:
                        proposals = {}
                        watcher_enabled = True
                    else:
                        proposals_data = data.get("proposals", {})
                        proposals = {
                            pid: Proposal(**p) for pid, p in proposals_data.items()
                        }
                        watcher_enabled = data.get("watcher_enabled", True)
                    
                    return State(
                        plan=plan,
                        stats=stats,
                        trades=trades,
                        proposals=proposals,
                        watcher_enabled=watcher_enabled,
                        schema_version=max(schema_version, 2),
                    )
            except Exception as e:
                logger.warning(f"Error loading state: {e}, creating new state")
        
        return State(
            plan=Plan(),
            stats=Stats(),
            trades=[],
            proposals={},
            watcher_enabled=True,
            schema_version=2,
        )
    
    def save(self, state: State):
        """Save state to JSON file."""
        data = {
            "plan": asdict(state.plan),
            "stats": asdict(state.stats),
            "trades": [asdict(t) for t in state.trades],
            "proposals": {pid: asdict(p) for pid, p in state.proposals.items()},
            "watcher_enabled": state.watcher_enabled,
            "schema_version": state.schema_version,
        }
        with open(self.state_path, "w") as f:
            json.dump(data, f, indent=2)
        logger.debug(f"State saved to {self.state_path}")


class WatchStateStore:
    """Manages persistence of watch state with atomic updates."""
    
    def __init__(self, state_path: Path):
        """Initialize with state file path."""
        self.state_path = state_path
        self.lock_path = state_path.with_suffix(state_path.suffix + ".lock")
    
    @contextmanager
    def _lock(self):
        """Acquire file lock for atomic updates."""
        lock_file = open(self.lock_path, "w")
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            lock_file.close()
    
    def update_atomic(self, fn: Callable[[WatchState], None]):
        """Update watch state atomically with file locking.
        
        Args:
            fn: Function that takes WatchState and modifies it in place
        """
        with self._lock():
            state = self.load()
            fn(state)
            self.save(state)
    
    def load(self) -> WatchState:
        """Load watch state from JSON file."""
        if self.state_path.exists():
            try:
                with open(self.state_path, "r") as f:
                    data = json.load(f)
                    config_data = data.get("config", {})
                    thresholds = WatchThresholds(**config_data.get("thresholds", {}))
                    config = WatchConfig(
                        **{k: v for k, v in config_data.items() if k != "thresholds"},
                        thresholds=thresholds,
                    )
                    return WatchState(
                        config=config,
                        last_poll_time=data.get("last_poll_time"),
                        last_alerts=data.get("last_alerts", []),
                        last_alert_ts=data.get("last_alert_ts", {}),
                        last_safe_snapshot=data.get("last_safe_snapshot", {}),
                        is_running=False,  # Don't restore running state
                        enabled=data.get("enabled", True),
                        muted_coins=data.get("muted_coins", {}),
                        last_proposal_time=data.get("last_proposal_time", 0.0),
                    )
            except Exception as e:
                logger.warning(f"Error loading watch state: {e}, creating new state")
        
        return WatchState(
            config=WatchConfig(),
            is_running=False,
            enabled=True,
            muted_coins={},
            last_proposal_time=0.0,
        )
    
    def save(self, state: WatchState):
        """Save watch state to JSON file."""
        data = {
            "config": {
                **asdict(state.config),
                "thresholds": asdict(state.config.thresholds),
            },
            "last_poll_time": state.last_poll_time,
            "last_alerts": state.last_alerts[-50:],  # Keep last 50 alerts
            "last_alert_ts": state.last_alert_ts,
            "last_safe_snapshot": state.last_safe_snapshot,
            "enabled": state.enabled,
            "muted_coins": state.muted_coins,
            "last_proposal_time": state.last_proposal_time,
        }
        with open(self.state_path, "w") as f:
            json.dump(data, f, indent=2)
        logger.debug(f"Watch state saved to {self.state_path}")

