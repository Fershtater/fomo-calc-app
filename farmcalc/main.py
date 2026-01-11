"""CLI entry point for farmcalc."""

import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

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
from .services.scoring import SafeEntryScore, evaluate_safe_entry
from .services.telegram_control import process_update
from .services.watcher import WatcherService
from .settings import Settings
from .storage.state_store import StateStore, WatchStateStore
from .ui.output import print_disclaimer, print_plan
from .ui.tables import render_assets_table, render_status_table

# Setup logging
log_format = os.getenv("LOG_FORMAT", "text")
log_level = os.getenv("LOG_LEVEL", "INFO")
setup_logging(log_format, log_level)

logger = logging.getLogger(__name__)

app = typer.Typer(help="Hyperliquid perp farming calculator")
console = Console()

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


@app.command()
def init(
    deposit: float = typer.Option(1000.0, "--deposit", "-d", help="Total deposit amount"),
    default_margin: float = typer.Option(100.0, "--margin", "-m", help="Default margin per trade"),
    default_leverage: float = typer.Option(10.0, "--leverage", "-l", help="Default leverage"),
    target_volume: float = typer.Option(10000.0, "--target-volume", "-v", help="Target total volume"),
    target_frozen: float = typer.Option(0.0, "--target-frozen", "-f", help="Target frozen amount"),
    unfreeze_factor: float = typer.Option(1.75, "--unfreeze-factor", help="Unfreeze factor"),
    level_factor: float = typer.Option(0.25, "--level-factor", help="Level factor"),
):
    """Initialize or update the farming plan."""
    state = _state_store.load()
    state.plan = Plan(
        deposit=deposit,
        default_margin=default_margin,
        default_leverage=default_leverage,
        target_volume=target_volume,
        target_frozen=target_frozen,
        unfreeze_factor=unfreeze_factor,
        level_factor=level_factor,
    )
    _state_store.save(state)
    console.print("[green]✓ Plan initialized/updated[/green]")
    print_plan(state.plan)


@app.command()
def quote(coin: str = typer.Argument(..., help="Coin symbol (e.g., BTC)")):
    """Show best bid/ask, mid, mark, and funding for a coin."""
    coin_data = _hl_client.get_coin_data(coin)
    if not coin_data:
        console.print(f"[red]Coin {coin} not found[/red]")
        raise typer.Exit(1)
    
    l2_book = _hl_client.get_l2_book(coin)
    
    console.print(Panel(f"[bold]Market Quote: {coin}[/bold]", style="cyan"))
    
    table = Table(show_header=False, box=None)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="yellow", justify="right")
    
    if l2_book:
        table.add_row("Best Bid", f"${l2_book['best_bid']:.4f}")
        table.add_row("Best Ask", f"${l2_book['best_ask']:.4f}")
        table.add_row("Mid (L2)", f"${l2_book['mid']:.4f}")
        table.add_row("Spread", f"${l2_book['spread']:.4f} ({l2_book['spread_bps']:.2f} bps)")
    else:
        table.add_row("Best Bid", "[red]N/A[/red]")
        table.add_row("Best Ask", "[red]N/A[/red]")
    
    table.add_row("Mark", f"${coin_data.get('markPx', 0):.4f}")
    table.add_row("Mid (Market)", f"${coin_data.get('midPx', 0):.4f}")
    table.add_row("Oracle", f"${coin_data.get('oraclePx', 0):.4f}")
    table.add_row("Funding (1h)", f"{coin_data.get('funding', 0):.6f}")
    
    console.print(table)


@app.command()
def assets(
    sort_by: str = typer.Option("funding", "--sort", "-s", help="Sort by: funding, volume, oi"),
    limit: int = typer.Option(20, "--limit", "-n", help="Number of results to show"),
):
    """List all available coins with market data, sorted by funding rate."""
    coins = _hl_client.get_all_coins()
    render_assets_table(coins, sort_by, limit)


@app.command()
def propose(
    coin: str = typer.Argument(..., help="Coin symbol (e.g., BTC)"),
    side: str = typer.Option("LONG", "--side", "-s", help="LONG or SHORT"),
    margin: Optional[float] = typer.Option(None, "--margin", "-m", help="Margin amount"),
    leverage: Optional[float] = typer.Option(None, "--leverage", "-l", help="Leverage"),
    hold_min: int = typer.Option(60, "--hold-min", "-h", help="Planned hold time in minutes"),
    fee_mode: str = typer.Option("maker", "--fee-mode", "-f", help="Fee mode: taker, maker, both"),
    taker_fee: float = typer.Option(_settings.default_taker_fee, "--taker-fee", help="Taker fee rate"),
    maker_fee: float = typer.Option(_settings.default_maker_fee, "--maker-fee", help="Maker fee rate"),
    funding_kind: str = typer.Option("hourly", "--funding-kind", help="Funding kind: hourly or 8h"),
    open_offset_bps: float = typer.Option(0.0, "--open-offset-bps", help="Open limit price offset in basis points"),
    close_offset_bps: float = typer.Option(0.0, "--close-offset-bps", help="Close limit price offset in basis points"),
    fill_prob: float = typer.Option(1.0, "--fill-prob", help="Probability of maker fill (0..1)"),
):
    """Propose a trade and show expected costs/returns."""
    state = _state_store.load()
    margin = margin or state.plan.default_margin
    leverage = leverage or state.plan.default_leverage
    
    coin_data = _hl_client.get_coin_data(coin)
    if not coin_data:
        console.print(f"[red]Coin {coin} not found[/red]")
        raise typer.Exit(1)
    
    max_lev = coin_data.get("maxLeverage", 0)
    if leverage > max_lev:
        console.print(f"[yellow]Warning: Leverage {leverage}x exceeds max {max_lev}x for {coin}[/yellow]")
    
    l2_book = _hl_client.get_l2_book(coin)
    notional = margin * leverage
    
    # Evaluate safe entry with scoring
    score_result: Optional[SafeEntryScore] = None
    if l2_book:
        # Create a minimal config for scoring
        from .models.domain import WatchConfig, WatchThresholds
        temp_config = WatchConfig(
            funding_kind=funding_kind,
            thresholds=WatchThresholds(),
        )
        score_result = evaluate_safe_entry(coin, coin_data, l2_book, temp_config)
    
    # Calculate limit prices
    open_limit_px = None
    close_limit_px = None
    fill_prob_open = fill_prob
    fill_prob_close = fill_prob
    if l2_book:
        open_limit_px, close_limit_px = suggested_limit_prices(
            side, l2_book["best_bid"], l2_book["best_ask"],
            open_offset_bps, close_offset_bps
        )
        
        # Estimate fill probabilities if we have score result
        if score_result:
            spread_bps = score_result.metrics.get("spread_bps", 0)
            depth_top = score_result.metrics.get("depth_top", 5000.0)
            fill_prob_open = _fill_model.estimate_fill_prob(
                coin, spread_bps, depth_top, notional, open_offset_bps
            )
            fill_prob_close = _fill_model.estimate_fill_prob(
                coin, spread_bps, depth_top, notional, close_offset_bps
            )
    
    # Determine fee modes
    open_fee_mode = "maker" if fee_mode == "maker" or fee_mode == "both" else "taker"
    close_fee_mode = "maker" if fee_mode == "maker" else ("maker" if fee_mode == "both" else "taker")
    
    # Use estimated fill probabilities
    fees, fee_details = calculate_fees(
        notional, taker_fee, maker_fee, fee_mode, fill_prob_open,
        None, open_fee_mode, close_fee_mode
    )
    volume = calculate_volume(notional, (fill_prob_open + fill_prob_close) / 2.0)
    
    funding_rate = coin_data.get("funding", 0)
    funding_kind_enum = FundingKind.HOURLY if funding_kind == "hourly" else FundingKind.EIGHT_HOUR
    funding_pnl = calculate_funding_pnl(side, notional, funding_rate, hold_min, funding_kind_enum)
    
    liquidation_move = estimate_liquidation_move(leverage, coin_data.get("marginMode"))
    
    # Display
    console.print(Panel(f"[bold]Trade Proposal: {coin} {side}[/bold]", style="cyan"))
    
    table = Table(show_header=False, box=None)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="yellow", justify="right")
    
    table.add_row("Margin", f"${margin:,.2f}")
    table.add_row("Leverage", f"{leverage}x")
    table.add_row("Notional", f"${notional:,.2f}")
    
    if score_result:
        table.add_row("Safe Entry Score", f"{score_result.total_score:.1f}/100")
        if score_result.reasons:
            table.add_row("Limiting Factors", ", ".join(score_result.reasons[:2]))
    
    if l2_book:
        table.add_row("Best Bid", f"${l2_book['best_bid']:.4f}")
        table.add_row("Best Ask", f"${l2_book['best_ask']:.4f}")
        if open_limit_px:
            table.add_row("Open Limit Price", f"${open_limit_px:.4f} (offset: {open_offset_bps:.1f} bps)")
            table.add_row("Open Fill Prob", f"{fill_prob_open:.1%}")
        if close_limit_px:
            table.add_row("Close Limit Price", f"${close_limit_px:.4f} (offset: {close_offset_bps:.1f} bps)")
            table.add_row("Close Fill Prob", f"{fill_prob_close:.1%}")
    
    table.add_row("Open Fee Mode", fee_details["open_fee_mode"].upper())
    table.add_row("Close Fee Mode", fee_details["close_fee_mode"].upper())
    table.add_row("Expected Volume", f"${volume:,.2f}")
    table.add_row("Expected Fees", f"${fees:.2f}")
    table.add_row("Funding Rate (1h)", f"{funding_rate:.6f}")
    table.add_row("Hold Time", f"{hold_min} minutes")
    table.add_row("Expected Funding PnL", f"${funding_pnl:.2f}")
    table.add_row("Net Expected PnL", f"${funding_pnl - fees:.2f}")
    table.add_row("Liquidation Move", f"~{liquidation_move:.1f}%")
    table.add_row("Current Mark", f"${coin_data.get('markPx', 0):.4f}")
    table.add_row("Current Mid", f"${coin_data.get('midPx', 0):.4f}")
    table.add_row("Current Oracle", f"${coin_data.get('oraclePx', 0):.4f}")
    
    console.print(table)
    console.print("\n[bold yellow]⚠️  RISK WARNING: High leverage trading can result in total loss![/bold yellow]")


@app.command()
def accept(
    coin: str = typer.Argument(..., help="Coin symbol"),
    side: str = typer.Option("LONG", "--side", "-s", help="LONG or SHORT"),
    margin: Optional[float] = typer.Option(None, "--margin", "-m", help="Margin amount"),
    leverage: Optional[float] = typer.Option(None, "--leverage", "-l", help="Leverage"),
    hold_min: int = typer.Option(60, "--hold-min", "-h", help="Planned hold time in minutes"),
    fee_mode: str = typer.Option("maker", "--fee-mode", "-f", help="Fee mode"),
    taker_fee: float = typer.Option(_settings.default_taker_fee, "--taker-fee", help="Taker fee rate"),
    maker_fee: float = typer.Option(_settings.default_maker_fee, "--maker-fee", help="Maker fee rate"),
    funding_kind: str = typer.Option("hourly", "--funding-kind", help="Funding kind"),
    open_offset_bps: float = typer.Option(0.0, "--open-offset-bps", help="Open limit price offset in basis points"),
    close_offset_bps: float = typer.Option(0.0, "--close-offset-bps", help="Close limit price offset in basis points"),
    fill_prob: float = typer.Option(1.0, "--fill-prob", help="Probability of maker fill (0..1)"),
):
    """Accept and record a proposed trade."""
    state = _state_store.load()
    margin = margin or state.plan.default_margin
    leverage = leverage or state.plan.default_leverage
    
    coin_data = _hl_client.get_coin_data(coin)
    if not coin_data:
        console.print(f"[red]Coin {coin} not found[/red]")
        raise typer.Exit(1)
    
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
    
    console.print(f"[green]✓ Trade accepted: {trade_id}[/green]")
    console.print(f"  Coin: {coin} {side}")
    if open_limit_px:
        console.print(f"  Open Limit Price: ${open_limit_px:.4f}")
    console.print(f"  Open Price: ${open_price:.4f}")
    if close_limit_px:
        console.print(f"  Close Limit Price: ${close_limit_px:.4f}")
    console.print(f"  Notional: ${notional:,.2f}")
    console.print(f"  Fill Probability: {fill_prob:.1%}")
    console.print(f"  Expected Fees: ${fees:.2f} ({open_fee_mode}/{close_fee_mode})")
    console.print(f"  Expected Funding PnL: ${funding_pnl:.2f}")


@app.command()
def close(
    trade_id: str = typer.Argument(..., help="Trade ID to close"),
    close_price: Optional[float] = typer.Option(None, "--close-price", "-p", help="Close price"),
    actual_funding_pnl: Optional[float] = typer.Option(None, "--actual-funding-pnl", help="Override actual funding PnL"),
    actual_close_fee_mode: Optional[str] = typer.Option(None, "--actual-close-fee-mode", help="Actual close fee mode"),
    actual_close_fee: Optional[float] = typer.Option(None, "--actual-close-fee", help="Override actual close fee amount"),
):
    """Close a trade and calculate realized PnL."""
    state = _state_store.load()
    
    trade = None
    for t in state.trades:
        if t.id == trade_id:
            trade = t
            break
    
    if not trade:
        console.print(f"[red]Trade {trade_id} not found[/red]")
        raise typer.Exit(1)
    
    if trade.close_price is not None:
        console.print(f"[yellow]Trade {trade_id} already closed[/yellow]")
        raise typer.Exit(1)
    
    if close_price is None:
        coin_data = _hl_client.get_coin_data(trade.coin)
        if not coin_data:
            console.print(f"[red]Could not fetch price for {trade.coin}[/red]")
            raise typer.Exit(1)
        close_price = coin_data.get("midPx", 0)
    
    # Calculate realized PnL
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
    
    # Update trade
    trade.close_price = close_price
    trade.close_timestamp = datetime.now(timezone.utc).isoformat()
    trade.realized_pnl = realized_pnl
    if actual_close_fee_mode:
        trade.actual_close_fee_mode = actual_close_fee_mode.lower()
    
    # Update stats
    from .services.calc import calculate_volume
    
    state.stats.total_volume_done += calculate_volume(trade.notional, trade.fill_prob)
    state.stats.total_fees += total_actual_fees
    state.stats.total_funding_pnl += final_funding_pnl
    
    _state_store.save(state)
    
    console.print(f"[green]✓ Trade closed: {trade_id}[/green]")
    console.print(f"  Open Price: ${trade.open_price:.4f}")
    console.print(f"  Close Price: ${close_price:.4f}")
    console.print(f"  Price PnL: ${price_pnl:.2f}")
    console.print(f"  Funding PnL: ${final_funding_pnl:.2f}")
    console.print(f"  Fees: ${total_actual_fees:.2f}")
    if actual_close_fee_mode:
        console.print(f"  Close Fee Mode: {actual_close_fee_mode.upper()}")
    console.print(f"  [bold]Realized PnL: ${realized_pnl:.2f}[/bold]")


@app.command()
def delete(trade_id: str = typer.Argument(..., help="Trade ID to delete")):
    """Delete a trade from the state."""
    state = _state_store.load()
    
    original_len = len(state.trades)
    state.trades = [t for t in state.trades if t.id != trade_id]
    
    if len(state.trades) == original_len:
        console.print(f"[red]Trade {trade_id} not found[/red]")
        raise typer.Exit(1)
    
    _state_store.save(state)
    console.print(f"[green]✓ Trade {trade_id} deleted[/green]")


@app.command()
def status():
    """Show current farming status and progress."""
    state = _state_store.load()
    render_status_table(state)


@app.command()
def fill_feedback(
    trade_id: str = typer.Argument(..., help="Trade ID"),
    open_result: str = typer.Option(..., "--open", help="Open order result: filled or missed"),
    close_result: Optional[str] = typer.Option(None, "--close", help="Close order result: filled or missed"),
):
    """Record fill feedback for a trade to improve fill probability estimation."""
    state = _state_store.load()
    
    trade = None
    for t in state.trades:
        if t.id == trade_id:
            trade = t
            break
    
    if not trade:
        console.print(f"[red]Trade {trade_id} not found[/red]")
        raise typer.Exit(1)
    
    # Record feedback
    if open_result.lower() in ["filled", "fill"]:
        _fill_model.record_feedback(trade.coin, "open", True)
        console.print(f"[green]✓ Recorded open fill for {trade.coin}[/green]")
    elif open_result.lower() in ["missed", "miss"]:
        _fill_model.record_feedback(trade.coin, "open", False)
        console.print(f"[yellow]✓ Recorded open miss for {trade.coin}[/yellow]")
    else:
        console.print(f"[red]Invalid open result: {open_result}. Use 'filled' or 'missed'[/red]")
        raise typer.Exit(1)
    
    if close_result:
        if close_result.lower() in ["filled", "fill"]:
            _fill_model.record_feedback(trade.coin, "close", True)
            console.print(f"[green]✓ Recorded close fill for {trade.coin}[/green]")
        elif close_result.lower() in ["missed", "miss"]:
            _fill_model.record_feedback(trade.coin, "close", False)
            console.print(f"[yellow]✓ Recorded close miss for {trade.coin}[/yellow]")
        else:
            console.print(f"[red]Invalid close result: {close_result}. Use 'filled' or 'missed'[/red]")
            raise typer.Exit(1)


@app.command()
def watch(
    interval: float = typer.Option(5.0, "--interval", "-i", help="Poll interval in seconds"),
    top: int = typer.Option(25, "--top", "-n", help="Number of top coins to monitor"),
    side: str = typer.Option("either", "--side", "-s", help="Side preference: long, short, either"),
    funding_kind: str = typer.Option("hourly", "--funding-kind", help="Funding kind: hourly or 8h"),
    spread_max_bps: float = typer.Option(3.0, "--spread-max-bps", help="Max spread in basis points"),
    mark_dev_max_bps: float = typer.Option(5.0, "--mark-dev-max-bps", help="Max mark-mid deviation in bps"),
    oracle_dev_max_bps: float = typer.Option(10.0, "--oracle-dev-max-bps", help="Max oracle-mid deviation in bps"),
    funding_max: float = typer.Option(0.00002, "--funding-max", help="Max funding rate (hourly)"),
    cooldown: float = typer.Option(300.0, "--cooldown", "-c", help="Cooldown between alerts per coin/side (seconds)"),
    open_offset_bps: float = typer.Option(0.0, "--open-offset-bps", help="Open limit price offset in basis points"),
    close_offset_bps: float = typer.Option(0.0, "--close-offset-bps", help="Close limit price offset in basis points"),
):
    """Run watch mode in foreground - polls market data and sends Telegram alerts."""
    if not _telegram_client.enabled:
        console.print("[yellow]Warning: TELEGRAM_BOT_TOKEN and/or TELEGRAM_CHAT_ID not set. Alerts will not be sent.[/yellow]")
    
    # Adjust funding_max for 8h
    if funding_kind == "8h":
        funding_max = funding_max * 8.0
    
    config = WatchConfig(
        enabled=True,
        poll_interval_sec=max(_settings.poll_interval_floor_sec, interval),
        top_n=top,
        side=side.lower(),
        open_offset_bps=open_offset_bps,
        close_offset_bps=close_offset_bps,
        funding_kind=funding_kind,
        thresholds=WatchThresholds(
            spread_max_bps=spread_max_bps,
            mark_dev_max_bps=mark_dev_max_bps,
            oracle_dev_max_bps=oracle_dev_max_bps,
            funding_max=funding_max,
            min_day_ntl_vlm=0.0,
        ),
        cooldown_sec=cooldown,
        telegram_enabled=_telegram_client.enabled,
    )
    
    _watcher_service.update_config(config)
    state = _watcher_service.get_state()
    state.is_running = True
    _watcher_service.save_state()
    
    console.print(Panel(
        "[bold]Watch Mode Started[/bold]\n\n"
        f"Poll Interval: {config.poll_interval_sec}s\n"
        f"Top N Coins: {config.top_n}\n"
        f"Side: {config.side.upper()}\n"
        f"Funding Kind: {config.funding_kind}\n"
        f"Telegram: {'Enabled' if config.telegram_enabled else 'Disabled'}\n\n"
        "[bold red]⚠️  PAPER-ONLY ALERTS. NO TRADING EXECUTED.[/bold red]",
        style="cyan"
    ))
    
    try:
        _watcher_service.start()
        # Keep running until interrupted
        import time
        while state.is_running:
            time.sleep(1)
    except KeyboardInterrupt:
        console.print("\n[yellow]Stopping watch mode...[/yellow]")
        _watcher_service.stop()
        console.print("[green]Watch mode stopped[/green]")


# Telegram subcommands
telegram_app = typer.Typer(help="Telegram bot management commands")
app.add_typer(telegram_app, name="telegram")


@telegram_app.command()
def set_webhook(
    url: Optional[str] = typer.Option(None, "--url", help="Webhook URL (HTTPS required)"),
    secret_token: Optional[str] = typer.Option(None, "--secret-token", help="Secret token for verification"),
    drop_pending: bool = typer.Option(False, "--drop-pending", help="Drop pending updates"),
):
    """Set Telegram webhook URL."""
    webhook_url = url or _settings.telegram_webhook_url
    if not webhook_url:
        console.print("[red]Error: Webhook URL required (--url or TELEGRAM_WEBHOOK_URL)[/red]")
        raise typer.Exit(1)
    
    secret = secret_token or _settings.telegram_secret_token
    
    if _telegram_client.set_webhook(
        webhook_url,
        secret_token=secret,
        drop_pending_updates=drop_pending,
    ):
        console.print(f"[green]✓ Webhook set to {webhook_url}[/green]")
    else:
        console.print("[red]✗ Failed to set webhook[/red]")
        raise typer.Exit(1)


@telegram_app.command()
def delete_webhook(
    drop_pending: bool = typer.Option(False, "--drop-pending", help="Drop pending updates"),
):
    """Delete Telegram webhook."""
    if _telegram_client.delete_webhook(drop_pending_updates=drop_pending):
        console.print("[green]✓ Webhook deleted[/green]")
    else:
        console.print("[red]✗ Failed to delete webhook[/red]")
        raise typer.Exit(1)


@telegram_app.command()
def poll(
    timeout: int = typer.Option(30, "--timeout", "-t", help="Polling timeout in seconds"),
):
    """Run Telegram long polling (for development/testing)."""
    console.print("[yellow]Starting Telegram long polling (Ctrl+C to stop)...[/yellow]")
    console.print("[yellow]Note: Do not run webhook and polling simultaneously![/yellow]")
    
    from .services.telegram_queue import TelegramUpdateQueue
    
    # Create queue for polling mode
    queue = TelegramUpdateQueue(maxsize=100)
    queue.set_processor(
        lambda update: process_update(
            update, _state_store, _watch_state_store, _telegram_client, _settings, _watcher_service
        )
    )
    queue.start_worker()
    
    offset = None
    
    try:
        while True:
            updates = _telegram_client.get_updates(
                offset=offset,
                timeout=timeout,
            )
            
            if updates:
                for update in updates:
                    # Enqueue for async processing (same path as webhook)
                    queue.enqueue(update)
                    
                    # Update offset
                    update_id = update.get("update_id")
                    if update_id:
                        offset = update_id + 1
            
    except KeyboardInterrupt:
        console.print("\n[yellow]Polling stopped[/yellow]")
        queue.stop_worker()


@telegram_app.command()
def send_test():
    """Send a test message to verify Telegram configuration."""
    if not _telegram_client.enabled:
        console.print("[red]Telegram not configured (missing token or chat_id)[/red]")
        raise typer.Exit(1)
    
    test_msg = (
        "<b>🧪 FarmCalc Test Message</b>\n\n"
        "If you see this, Telegram integration is working correctly!"
    )
    
    if _telegram_client.send_message(test_msg):
        console.print("[green]✓ Test message sent[/green]")
    else:
        console.print("[red]✗ Failed to send test message[/red]")
        raise typer.Exit(1)


@telegram_app.command()
def status():
    """Show Telegram webhook status."""
    webhook_info = _telegram_client.get_webhook_info()
    
    console.print(Panel("[bold]Telegram Status[/bold]", style="cyan"))
    table = Table(show_header=False, box=None)
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="yellow")
    
    table.add_row("Enabled", "✅ Yes" if _telegram_client.enabled else "❌ No")
    table.add_row("Chat ID", str(_telegram_client.chat_id) if _telegram_client.chat_id else "Not set")
    table.add_row("Admin IDs", ", ".join(map(str, _settings.telegram_admin_ids)) if _settings.telegram_admin_ids else "None")
    
    if webhook_info:
        table.add_row("Webhook URL", webhook_info.get("url", "Not set"))
        table.add_row("Pending Updates", str(webhook_info.get("pending_update_count", 0)))
    
    console.print(table)


def main():
    """Main entry point."""
    # Load .env file if it exists
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    
    print_disclaimer()
    app()


if __name__ == "__main__":
    main()

