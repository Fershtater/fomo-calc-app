"""Rich table renderers for CLI output."""

from rich.console import Console
from rich.table import Table

from ..models.domain import State, Trade

console = Console()


def render_assets_table(coins: list, sort_by: str = "funding", limit: int = 20):
    """Render assets table."""
    # Sort
    if sort_by == "funding":
        coins.sort(key=lambda x: x.get("funding", 0), reverse=True)
    elif sort_by == "volume":
        coins.sort(key=lambda x: x.get("dayNtlVlm", 0), reverse=True)
    elif sort_by == "oi":
        coins.sort(key=lambda x: x.get("openInterest", 0), reverse=True)
    
    # Display
    table = Table(title="Hyperliquid Perpetuals")
    table.add_column("Coin", style="cyan")
    table.add_column("Funding (1h)", style="yellow", justify="right")
    table.add_column("Mark", justify="right")
    table.add_column("Mid", justify="right")
    table.add_column("Oracle", justify="right")
    table.add_column("Max Lev", justify="right")
    table.add_column("24h Volume", justify="right")
    
    for coin in coins[:limit]:
        funding = coin.get("funding", 0)
        funding_str = f"{funding:.6f}" if funding else "N/A"
        table.add_row(
            coin["coin"],
            funding_str,
            f"{coin.get('markPx', 0):.4f}",
            f"{coin.get('midPx', 0):.4f}",
            f"{coin.get('oraclePx', 0):.4f}",
            str(coin.get("maxLeverage", 0)),
            f"{coin.get('dayNtlVlm', 0):,.0f}",
        )
    
    console.print(table)


def render_status_table(state: State):
    """Render status table."""
    from rich.panel import Panel
    
    console.print(Panel("[bold]Farming Plan[/bold]", style="cyan"))
    print_plan(state.plan)
    
    console.print("\n" + Panel("[bold]Statistics[/bold]", style="cyan"))
    stats_table = Table(show_header=False, box=None)
    stats_table.add_column("Metric", style="cyan")
    stats_table.add_column("Value", style="yellow", justify="right")
    
    remaining_volume = max(0, state.plan.target_volume - state.stats.total_volume_done)
    stats_table.add_row("Total Volume Done", f"${state.stats.total_volume_done:,.2f}")
    stats_table.add_row("Target Volume", f"${state.plan.target_volume:,.2f}")
    stats_table.add_row("Remaining Volume", f"${remaining_volume:,.2f}")
    stats_table.add_row("Total Fees Paid", f"${state.stats.total_fees:.2f}")
    stats_table.add_row("Total Funding PnL", f"${state.stats.total_funding_pnl:.2f}")
    stats_table.add_row("Net PnL", f"${state.stats.total_funding_pnl - state.stats.total_fees:.2f}")
    
    # Calculate how many more trades needed
    from ..services.calc import roundtrips_needed, calculate_volume
    
    if state.plan.default_margin > 0 and state.plan.default_leverage > 0:
        notional_per_trade = state.plan.default_margin * state.plan.default_leverage
        trades_needed = roundtrips_needed(remaining_volume, notional_per_trade)
        stats_table.add_row("Trades Needed (est.)", str(trades_needed))
    
    console.print(stats_table)
    
    # Active trades
    active_trades = [t for t in state.trades if t.close_price is None]
    if active_trades:
        render_trades_table(active_trades, title="Active Trades")


def render_trades_table(trades: list[Trade], title: str = "Trades"):
    """Render trades table."""
    console.print(f"\n[bold]{title}: {len(trades)}[/bold]")
    trades_table = Table()
    trades_table.add_column("ID", style="cyan")
    trades_table.add_column("Coin", style="yellow")
    trades_table.add_column("Side", justify="center")
    trades_table.add_column("Notional", justify="right")
    trades_table.add_column("Open Price", justify="right")
    trades_table.add_column("Hold Min", justify="right")
    
    for trade in trades:
        trades_table.add_row(
            trade.id,
            trade.coin,
            trade.side,
            f"${trade.notional:,.2f}",
            f"${trade.open_price:.4f}" if trade.open_price else "N/A",
            str(trade.planned_hold_min),
        )
    console.print(trades_table)

