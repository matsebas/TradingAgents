#!/usr/bin/env python3
"""
Test script to verify that the basic layout renders correctly
"""
from rich.console import Console
from rich.panel import Panel
from rich.layout import Layout
from rich.live import Live
from rich.table import Table
from rich import box
import time

console = Console()

def create_test_layout():
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="main"),
        Layout(name="footer", size=3),
    )
    layout["main"].split_column(
        Layout(name="upper", size=18),
        Layout(name="analysis")
    )
    layout["upper"].split_row(
        Layout(name="progress"),
        Layout(name="messages")
    )
    return layout

def update_test_display(layout):
    # Header
    layout["header"].update(
        Panel(
            "[bold green]Test Header[/bold green]\n[dim]Testing layout[/dim]",
            title="Header Test",
            border_style="green",
            padding=(1, 2),
        )
    )

    # Progress table
    progress_table = Table(
        show_header=True,
        header_style="bold magenta",
        box=box.SIMPLE_HEAD,
        padding=(0, 1),
        expand=True,
    )
    progress_table.add_column("Team", style="cyan")
    progress_table.add_column("Agent", style="green")
    progress_table.add_column("Status", style="yellow", width=12)

    progress_table.add_row("Test Team", "Test Agent", "[green]completed[/green]")

    layout["progress"].update(
        Panel(progress_table, title="Progress", border_style="cyan", padding=(0, 1))
    )

    # Messages table
    messages_table = Table(
        show_header=True,
        header_style="bold magenta",
        box=box.MINIMAL,
        show_lines=True,
        padding=(0, 1),
        expand=True,
    )
    messages_table.add_column("Time", style="cyan", width=8)
    messages_table.add_column("Type", style="green", width=10)
    messages_table.add_column("Content", style="white", no_wrap=False)

    messages_table.add_row("12:00:00", "System", "Test message 1")
    messages_table.add_row("12:00:01", "Reasoning", "Test message 2")

    layout["messages"].update(
        Panel(messages_table, title="Messages & Tools", border_style="blue", padding=(1, 2))
    )

    # Analysis panel
    layout["analysis"].update(
        Panel(
            "[bold]Test Analysis Content[/bold]\n\nThis is a test of the analysis panel.\n\nIt should show multiple lines.",
            title="Current Report",
            border_style="green",
            padding=(1, 2),
        )
    )

    # Footer
    stats_table = Table(show_header=False, box=None, padding=(0, 2), expand=True)
    stats_table.add_column("Stats", justify="center")
    stats_table.add_row("Tool Calls: 0 | LLM Calls: 0 | Generated Reports: 0")

    layout["footer"].update(Panel(stats_table, border_style="grey50"))

if __name__ == "__main__":
    console.print("[bold cyan]Testing Layout Rendering...[/bold cyan]\n")

    # Clear console
    console.clear()

    layout = create_test_layout()

    with Live(layout, refresh_per_second=4, console=console) as live:
        update_test_display(layout)

        console.print("\n[green]✓ Layout is rendering correctly![/green]")
        console.print("[yellow]Press Ctrl+C to exit...[/yellow]")

        # Keep alive for 10 seconds
        for i in range(10):
            time.sleep(1)

    console.print("\n[bold green]Test completed successfully![/bold green]")

