#!/usr/bin/env python3
"""
Test script to demonstrate the improved scroll functionality in the CLI.
This simulates how the Current Report panel handles long content.
"""

from rich.console import Console, Group
from rich.panel import Panel
from rich.layout import Layout
from rich.markdown import Markdown
from rich.text import Text
from rich.live import Live
import time

console = Console()

# Simulate a long report (like the Portfolio Management Decision)
long_report = """### Portfolio Management Decision

As the Risk Management Judge and Debate Facilitator, I have evaluated the arguments presented by Risky, Neutral, and Safe regarding Berkshire Hathaway (BRK). 

The core of this debate centers on a conflict between **latent fundamental power** (the $382B cash pile) and **immediate technical deterioration** (the break below the 200-day SMA). While the Risky analyst correctly identifies Berkshire as a "lender of last resort," the Safe analyst provides a devastating counter-point regarding management's own lack of conviction (the cessation of share buybacks).

### **Summarized Key Arguments**

1.  **The "Buffett Premium" vs. "The Machine"**: The bear/safe case highlights the departure of the "psychological safety net" and the exit of key talent like Todd Combs. Conversely, the bull case argues that the "Berkshire Machine"—a diversified industrial backbone—is now more important than stock-picking.
2.  **The Cash Fortress**: All parties acknowledge the $382 billion. Risky sees it as "ammunition" for a pivot into AI/Tech; Safe sees it as a sign that management finds nothing—including their own stock—worth buying.
3.  **Technical Breakdown**: The price has slipped below the 50-day and 200-day SMAs. Safe and Neutral correctly identify this as a signal of "active distribution" by institutions, which often leads to further downside before stabilization.

---

### **The Decision: BUY (Tactical Scale-In)**

I am upholding the **Buy** recommendation but **significantly tightening the risk controls** of the trader's original plan. We are moving from a "buy the dip" mentality to a "buy the floor" strategy.

#### **Rationale**
*   **Refuting the Assertive Buy**: Risky argues we should "front-run the inevitable" and buy now because "technicals are tea leaves." This is rejected. As the Neutral analyst pointed out, ignoring the 200-day SMA break "ignores how institutional algorithms actually function." We will not enter a full position while the "herd" is actively selling.
*   **Refuting the Hold**: Safe suggests holding until the first Abel-era report. While prudent, this risks missing the "dislocation" entry that Berkshire is designed for. As Risky noted, "By the time that headline hits... the stock will be trading $50 higher."
*   **The Buyback Signal**: The most critical data point is the slowdown in share buybacks. If management isn't buying at $496, we shouldn't be "backing the truck up" there either. However, historical valuation floors suggest that as we approach the $475-$485 range, the "Berkshire Machine" is likely to resume its own support.

---

### **The Refined Investment Plan**

The original plan's 50% initial entry is too aggressive given the "death cross" and technical weakness. We will shift to a more defensive stance.

**1. The "Feeler" Entry (20% Position):** 
Initiate only 20% of the intended position at the current level (~$496). This satisfies the need for "skin in the game" in case of a lightning-strike acquisition, while respecting the Neutral analyst's warning that "the short-term trend is clearly bearish."

**2. The "Institutional Floor" Target (60% Position):**
Set heavy limit orders in the **$482 to $488 range**. This aligns with the Bollinger Lower Band and the historical support levels identified by the Safe analyst. This is where we expect the "distribution" to exhaust itself and where the valuation becomes too compelling for even a conservative management to ignore.

**3. The "Abel Catalyst" (Remaining 20%):**
The final 20% will be deployed only *after* the Q1 2026 earnings or the first shareholder letter, confirming that capital allocation (dividends or major buybacks) is a priority. We must see "proof of capital allocation" before being fully committed.

**4. Hard Stop-Loss:**
The original mental stop at $475 is now a **hard stop**. If the stock closes below $475 for three consecutive days, we exit. As the Safe analyst warned, a break here would signal a fundamental "re-rating of the company much lower than its tangible book value," likely due to systemic macro shifts (BoJ/Yen carry trade) that even $382B in cash cannot immediately offset.

**Final Verdict:** We are buying a **fortress at a discount**, but we are doing so with the clinical patience of the machine itself, not the fervor of the myth. **Buy, but scale-in with extreme discipline.**"""


def test_scroll_display():
    """Test the scroll functionality with the improved implementation."""

    # Get terminal dimensions
    terminal_height = console.size.height
    console.print(f"[cyan]Terminal height: {terminal_height} lines[/cyan]")
    console.print(f"[cyan]Terminal width: {console.size.width} columns[/cyan]\n")

    # Calculate available height (same logic as in main.py)
    available_height = max(10, terminal_height - 32)

    # Split report into lines
    report_lines = long_report.split('\n')
    total_lines = len(report_lines)

    console.print(f"[yellow]Report has {total_lines} lines[/yellow]")
    console.print(f"[yellow]Available height for display: {available_height} lines[/yellow]\n")

    # Show the panel with scroll indicator
    if total_lines > available_height:
        visible_lines = report_lines[-available_height:]
        scrollable_report = '\n'.join(visible_lines)

        # Create scroll indicator
        scroll_indicator = Text(
            f"↑ Scroll: Showing last {available_height} of {total_lines} lines",
            style="dim italic yellow"
        )

        # Create markdown content
        markdown_content = Markdown(scrollable_report)

        # Combine using Group
        display_content = Group(scroll_indicator, Text(""), markdown_content)

        panel = Panel(
            display_content,
            title="Current Report [dim](Auto-scrolled to latest)[/dim]",
            border_style="green",
            padding=(1, 2),
        )
    else:
        panel = Panel(
            Markdown(long_report),
            title="Current Report",
            border_style="green",
            padding=(1, 2),
        )

    console.print(panel)

    console.print("\n[bold green]✓ Scroll indicator is shown at the top[/bold green]")
    console.print("[bold green]✓ Only the last N lines are visible (most recent content)[/bold green]")
    console.print("[bold green]✓ You can use your terminal's native scroll to see this output[/bold green]")


if __name__ == "__main__":
    console.print(Panel.fit(
        "[bold cyan]Testing Improved Scroll Functionality[/bold cyan]\n\n"
        "This demonstrates how the Current Report panel handles long content.\n"
        "The panel will show a scroll indicator and display only the most recent lines.",
        border_style="cyan"
    ))
    console.print()

    test_scroll_display()

    console.print("\n" + "="*80)
    console.print("[bold magenta]How scrolling works in Rich:[/bold magenta]")
    console.print("1. [yellow]During Live display[/yellow]: The layout shows last N lines with indicator")
    console.print("2. [yellow]After completion[/yellow]: Full report is printed and you can scroll in terminal")
    console.print("3. [yellow]Terminal scroll[/yellow]: Use your terminal's scrollbar or keyboard shortcuts")
    console.print("="*80 + "\n")

