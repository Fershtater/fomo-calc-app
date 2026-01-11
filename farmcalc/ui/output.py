"""Output formatting utilities."""

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ..models.domain import Plan

console = Console()


def print_disclaimer():
    """Print risk disclaimer."""
    console.print(Panel(
        "[bold red]⚠️  RISK DISCLAIMER[/bold red]\n\n"
        "High leverage trading is extremely risky and can result in total loss of capital.\n"
        "This tool is for calculation purposes only and does NOT execute trades.\n"
        "Always do your own research and never risk more than you can afford to lose.",
        style="red"
    ))
    console.print()


def print_plan(plan: Plan):
    """Print plan details."""
    plan_table = Table(show_header=False, box=None)
    plan_table.add_column("Setting", style="cyan")
    plan_table.add_column("Value", style="yellow", justify="right")
    
    plan_table.add_row("Deposit", f"${plan.deposit:,.2f}")
    plan_table.add_row("Default Margin", f"${plan.default_margin:,.2f}")
    plan_table.add_row("Default Leverage", f"{plan.default_leverage}x")
    plan_table.add_row("Target Volume", f"${plan.target_volume:,.2f}")
    plan_table.add_row("Target Frozen", f"${plan.target_frozen:,.2f}")
    plan_table.add_row("Unfreeze Factor", str(plan.unfreeze_factor))
    plan_table.add_row("Level Factor", str(plan.level_factor))
    
    console.print(plan_table)

