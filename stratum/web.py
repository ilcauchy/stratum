from __future__ import annotations

import html
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .analysis import run_analysis
from .config import OBJECTIVE_LABELS, RISK_LABELS, build_default_form_values
from .formatters import (
    format_currency,
    format_number,
    format_percent,
    format_signed_number,
    format_signed_percent,
)
from .market_data import build_market_data_snapshot
from .models import (
    AnalysisResult,
    InvestorProfile,
    MarketDataSnapshot,
    PortfolioDashboard,
    PortfolioHolding,
    PortfolioPerformanceView,
    PortfolioTransaction,
)
from .parsing import build_profile, validate_profile_form
from .performance import build_portfolio_performance
from .portfolio_csv import load_portfolio_dashboard


WINDOW_OPTIONS = [
    ("1m", "1M"),
    ("3m", "3M"),
    ("6m", "6M"),
    ("1y", "1Y"),
    ("3y", "3Y"),
    ("5y", "5Y"),
    ("ytd", "YTD"),
    ("all", "All"),
]


def render_error(field: str, errors: dict[str, str]) -> str:
    if field not in errors:
        return ""
    return f'<p class="field-error">{html.escape(errors[field])}</p>'


def render_options(selected: str) -> str:
    options = []
    for value, label in OBJECTIVE_LABELS.items():
        checked = " checked" if value == selected else ""
        options.append(
            "<label class=\"choice-card\">"
            f"<input type=\"radio\" name=\"objective\" value=\"{value}\"{checked}>"
            f"<span>{html.escape(label)}</span>"
            "</label>"
        )
    return "".join(options)


def render_allocation_bars(allocation: dict[str, int]) -> str:
    bars = []
    tones = ["tone-a", "tone-b", "tone-c", "tone-d", "tone-e"]
    for index, (asset, percentage) in enumerate(allocation.items()):
        tone = tones[index % len(tones)]
        bars.append(
            "<div class=\"allocation-row\">"
            "<div class=\"allocation-meta\">"
            f"<span>{html.escape(asset)}</span><strong>{percentage}%</strong>"
            "</div>"
            f"<div class=\"allocation-bar\"><span class=\"{tone}\" style=\"width:{percentage}%\"></span></div>"
            "</div>"
        )
    return "".join(bars)


def render_list(items: list[str]) -> str:
    return "".join(f"<li>{html.escape(item)}</li>" for item in items)


def render_positions(positions: dict[str, float]) -> str:
    if not positions:
        return "<p class=\"muted\">No holdings were entered. The plan is being treated as a new portfolio build.</p>"
    rows = []
    for ticker, amount in sorted(positions.items(), key=lambda item: item[1], reverse=True):
        rows.append(
            "<div class=\"holding-row\">"
            f"<span>{html.escape(ticker)}</span>"
            f"<strong>{html.escape(format_currency(amount))}</strong>"
            "</div>"
        )
    return "".join(rows)


def quote_change_tone(change: float) -> str:
    if change > 0:
        return "quote-positive"
    if change < 0:
        return "quote-negative"
    return "quote-neutral"


def render_market_data_panel(snapshot: MarketDataSnapshot) -> str:
    rows = []
    for quote in snapshot.quotes:
        badge_class = quote_change_tone(quote.change)
        volume = f"Volume {quote.volume:,}" if quote.volume is not None else "Volume n/a"
        rows.append(
            "<div class=\"market-row\">"
            "<div class=\"market-symbol\">"
            f"<strong>{html.escape(quote.symbol)}</strong>"
            f"<span>Latest session {html.escape(quote.latest_trading_day or 'n/a')}</span>"
            "</div>"
            "<div class=\"market-meta\">"
            f"<span>Last {html.escape(format_number(quote.price))}</span>"
            f"<span>Prev {html.escape(format_number(quote.previous_close))}</span>"
            f"<span>{html.escape(volume)}</span>"
            "</div>"
            "<div class=\"market-change\">"
            f"<strong>{html.escape(format_signed_number(quote.change))}</strong>"
            f"<span class=\"quote-badge {badge_class}\">{html.escape(format_signed_percent(quote.change_percent))}</span>"
            "</div>"
            "</div>"
        )

    if not rows:
        rows.append("<p class=\"muted\">No quote rows are available yet.</p>")

    errors_html = ""
    if snapshot.errors:
        errors_html = (
            "<ul class=\"market-errors\">"
            + "".join(f"<li>{html.escape(error)}</li>" for error in snapshot.errors)
            + "</ul>"
        )

    return (
        "<article class=\"glass-card wide-card\">"
        "<h3>Market Data</h3>"
        f"<p class=\"muted market-note\">Provider: {html.escape(snapshot.provider)}</p>"
        f"<p class=\"muted market-note\">{html.escape(snapshot.note)}</p>"
        f"<div class=\"market-stack\">{''.join(rows)}</div>"
        f"{errors_html}"
        "</article>"
    )


def format_share_quantity(quantity: float) -> str:
    if abs(quantity - round(quantity)) < 1e-6:
        return f"{int(round(quantity)):,}"
    return f"{quantity:,.3f}".rstrip("0").rstrip(".")


def format_date_label(raw_date) -> str:
    return raw_date.strftime("%Y-%m-%d")


def format_signed_currency(value: float) -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}{format_number(value)}"


def history_color(index: int) -> str:
    palette = ["#ff7b54", "#2a9d8f", "#264653", "#e9c46a", "#b56576", "#6d597a"]
    return palette[index % len(palette)]


def build_step_path(points: list[tuple[float, float]]) -> str:
    if not points:
        return ""

    path = [f"M {points[0][0]:.2f} {points[0][1]:.2f}"]
    previous_x, previous_y = points[0]
    for x, y in points[1:]:
        path.append(f"L {x:.2f} {previous_y:.2f}")
        path.append(f"L {x:.2f} {y:.2f}")
        previous_x, previous_y = x, y
    return " ".join(path)


def render_exposure_rows(
    holdings: list[PortfolioHolding], performance_lookup: dict[str, float] | None = None
) -> str:
    if not holdings:
        return "<p class=\"muted\">No positive holdings are available in the cleaned portfolio export.</p>"

    performance_lookup = performance_lookup or {}
    rows = []
    for index, holding in enumerate(holdings):
        pnl_class = "metric-up" if holding.unrealized_pnl >= 0 else "metric-down"
        realized_class = "metric-up" if holding.realized_pnl >= 0 else "metric-down"
        window_return = performance_lookup.get(holding.symbol)
        window_html = (
            f"<span class=\"{'metric-up' if window_return >= 0 else 'metric-down'}\">Window {html.escape(format_signed_percent(window_return * 100, decimals=1))}</span>"
            if window_return is not None
            else "<span>Window n/a</span>"
        )
        rows.append(
            "<div class=\"exposure-row\">"
            "<div class=\"exposure-head\">"
            "<div>"
            f"<strong>{html.escape(holding.symbol)}</strong>"
            f"<span>{html.escape(format_share_quantity(holding.quantity))} shares at {html.escape(format_number(holding.current_price))}</span>"
            "</div>"
            "<div class=\"exposure-value\">"
            f"<strong>{html.escape(format_currency(holding.market_value))}</strong>"
            f"<span>{html.escape(format_percent(holding.weight))}</span>"
            "</div>"
            "</div>"
            f"<div class=\"exposure-bar\"><span style=\"width:{holding.weight * 100:.2f}%; background:{history_color(index)}\"></span></div>"
            "<div class=\"exposure-meta\">"
            f"<span>Cost {html.escape(format_currency(holding.cost_basis))}</span>"
            f"{window_html}"
            "</div>"
            "<div class=\"exposure-meta\">"
            f"<span class=\"{realized_class}\">Realized {html.escape(format_signed_currency(holding.realized_pnl))}</span>"
            f"<span class=\"{pnl_class}\">Unrealized {html.escape(format_signed_currency(holding.unrealized_pnl))}</span>"
            "</div>"
            "</div>"
        )
    return "".join(rows)


def render_history_chart(dashboard: PortfolioDashboard) -> str:
    if not dashboard.snapshots or not dashboard.history_symbols:
        return "<p class=\"muted\">History will appear once there are tracked transactions in the portfolio CSV.</p>"

    width = 760
    height = 320
    left = 56
    right = 18
    top = 18
    bottom = 42
    chart_width = width - left - right
    chart_height = height - top - bottom
    x_count = len(dashboard.snapshots)
    x_step = chart_width / max(x_count - 1, 1)

    x_points = [left + (x_step * index if x_count > 1 else chart_width / 2) for index in range(x_count)]
    grid_lines = []
    for index, pct in enumerate((0, 0.25, 0.5, 0.75, 1.0)):
        y = top + chart_height - (chart_height * pct)
        label = f"{int(pct * 100)}%"
        grid_lines.append(
            f'<line x1="{left}" y1="{y:.2f}" x2="{width - right}" y2="{y:.2f}" class="chart-grid" />'
            f'<text x="{left - 10}" y="{y + 4:.2f}" class="chart-axis-label" text-anchor="end">{label}</text>'
        )

    date_labels = []
    label_indexes = sorted({0, x_count // 2, x_count - 1})
    for label_index in label_indexes:
        x = x_points[label_index]
        label = format_date_label(dashboard.snapshots[label_index].trade_date)
        date_labels.append(
            f'<text x="{x:.2f}" y="{height - 12}" class="chart-axis-label" text-anchor="middle">{html.escape(label)}</text>'
        )

    paths = []
    legend = []
    for index, symbol in enumerate(dashboard.history_symbols):
        peak_quantity = max(snapshot.quantities.get(symbol, 0.0) for snapshot in dashboard.snapshots)
        if peak_quantity <= 0:
            continue

        points = []
        for snapshot_index, snapshot in enumerate(dashboard.snapshots):
            normalized = snapshot.quantities.get(symbol, 0.0) / peak_quantity
            y = top + chart_height - (chart_height * normalized)
            points.append((x_points[snapshot_index], y))

        color = history_color(index)
        paths.append(
            f'<path d="{build_step_path(points)}" fill="none" stroke="{color}" stroke-width="3" stroke-linejoin="round" stroke-linecap="round" />'
        )

        current_quantity = dashboard.snapshots[-1].quantities.get(symbol, 0.0)
        legend.append(
            "<div class=\"legend-item\">"
            f"<span class=\"legend-swatch\" style=\"background:{color}\"></span>"
            f"<strong>{html.escape(symbol)}</strong>"
            f"<span>{html.escape(format_share_quantity(current_quantity))} shares now</span>"
            "</div>"
        )

    svg = (
        f'<svg viewBox="0 0 {width} {height}" class="history-chart" role="img" aria-label="Normalized holding history">'
        f'{"".join(grid_lines)}'
        f'{"".join(paths)}'
        f'{"".join(date_labels)}'
        "</svg>"
    )

    return (
        "<div class=\"history-card-body\">"
        f"{svg}"
        "<p class=\"muted\">Each line is normalized to that symbol's own peak share count, so you can see build-up and trim decisions on one chart.</p>"
        f"<div class=\"legend-row\">{''.join(legend)}</div>"
        "</div>"
    )


def render_recent_transactions(transactions: list[PortfolioTransaction]) -> str:
    if not transactions:
        return "<p class=\"muted\">No recent transactions were found in the cleaned CSV.</p>"

    rows = []
    for transaction in transactions:
        side_class = "side-buy" if transaction.side == "BUY" else "side-sell"
        rows.append(
            "<div class=\"transaction-row\">"
            "<div class=\"transaction-main\">"
            f"<span class=\"transaction-badge {side_class}\">{html.escape(transaction.side)}</span>"
            f"<strong>{html.escape(transaction.symbol)}</strong>"
            "</div>"
            f"<span>{html.escape(format_date_label(transaction.trade_date))}</span>"
            f"<span>{html.escape(format_share_quantity(transaction.quantity))} @ {html.escape(format_number(transaction.price))}</span>"
            "</div>"
        )
    return "".join(rows)


def chart_path(
    points: list[tuple[float, float]], baseline_y: float | None = None
) -> tuple[str, str]:
    if not points:
        return "", ""

    line = [f"M {points[0][0]:.2f} {points[0][1]:.2f}"]
    for x, y in points[1:]:
        line.append(f"L {x:.2f} {y:.2f}")

    area = ""
    if baseline_y is not None:
        area_parts = [f"M {points[0][0]:.2f} {baseline_y:.2f}", f"L {points[0][0]:.2f} {points[0][1]:.2f}"]
        for x, y in points[1:]:
            area_parts.append(f"L {x:.2f} {y:.2f}")
        area_parts.append(f"L {points[-1][0]:.2f} {baseline_y:.2f} Z")
        area = " ".join(area_parts)

    return " ".join(line), area


def series_points(
    values: list[float],
    width: int,
    height: int,
    left: int,
    top: int,
    chart_width: int,
    chart_height: int,
    minimum: float,
    maximum: float,
) -> list[tuple[float, float]]:
    if not values:
        return []

    spread = maximum - minimum
    if spread <= 1e-9:
        spread = 1.0

    x_step = chart_width / max(len(values) - 1, 1)
    points = []
    for index, value in enumerate(values):
        x = left + (x_step * index if len(values) > 1 else chart_width / 2)
        y = top + chart_height - (((value - minimum) / spread) * chart_height)
        points.append((x, y))
    return points


def render_chart(
    points: list[tuple[float, float]],
    width: int,
    height: int,
    left: int,
    right: int,
    top: int,
    bottom: int,
    minimum: float,
    maximum: float,
    labels: tuple[str, str, str],
    line_color: str,
    area_color: str,
    secondary_points: list[tuple[float, float]] | None = None,
    secondary_color: str = "#264653",
) -> str:
    chart_width = width - left - right
    chart_height = height - top - bottom
    grid = []
    for pct in (0.0, 0.25, 0.5, 0.75, 1.0):
        y = top + chart_height - (chart_height * pct)
        grid.append(
            f'<line x1="{left}" y1="{y:.2f}" x2="{width - right}" y2="{y:.2f}" class="chart-grid" />'
        )

    start_label, mid_label, end_label = labels
    x_positions = [left, left + chart_width / 2, width - right]
    axis_labels = [
        f'<text x="{x:.2f}" y="{height - 10}" class="chart-axis-label" text-anchor="middle">{html.escape(label)}</text>'
        for x, label in zip(x_positions, (start_label, mid_label, end_label))
    ]

    line_path, area_path = chart_path(points, baseline_y=top + chart_height)
    secondary_path = ""
    if secondary_points:
        secondary_path, _ = chart_path(secondary_points)
    secondary_html = ""
    if secondary_path:
        secondary_html = (
            f'<path d="{secondary_path}" fill="none" stroke="{secondary_color}" '
            'stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"></path>'
        )

    return (
        f'<svg viewBox="0 0 {width} {height}" class="history-chart" role="img">'
        f'{"".join(grid)}'
        f'<path d="{area_path}" fill="{area_color}" opacity="0.18"></path>'
        f'<path d="{line_path}" fill="none" stroke="{line_color}" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"></path>'
        f"{secondary_html}"
        f'{"".join(axis_labels)}'
        "</svg>"
    )


def render_performance_controls(window_key: str, start_raw: str, end_raw: str) -> str:
    options = []
    for value, label in WINDOW_OPTIONS:
        selected = " selected" if value == window_key else ""
        options.append(f'<option value="{value}"{selected}>{label}</option>')

    return (
        "<form method=\"get\" action=\"/\" class=\"window-form\">"
        "<div class=\"window-row\">"
        "<div class=\"field-group compact-field\">"
        "<label for=\"window\">Window</label>"
        f"<select id=\"window\" name=\"window\">{''.join(options)}</select>"
        "</div>"
        "<div class=\"field-group compact-field\">"
        "<label for=\"start\">Start</label>"
        f"<input id=\"start\" type=\"date\" name=\"start\" value=\"{html.escape(start_raw)}\">"
        "</div>"
        "<div class=\"field-group compact-field\">"
        "<label for=\"end\">End</label>"
        f"<input id=\"end\" type=\"date\" name=\"end\" value=\"{html.escape(end_raw)}\">"
        "</div>"
        "<div class=\"submit-row\">"
        "<button type=\"submit\">Update</button>"
        "<a class=\"ghost-link\" href=\"/\">Reset</a>"
        "</div>"
        "</div>"
        "</form>"
    )


def render_performance_section(
    performance: PortfolioPerformanceView | None,
    window_key: str,
    start_raw: str,
    end_raw: str,
) -> str:
    controls_html = render_performance_controls(window_key, start_raw, end_raw)

    if performance is None or not performance.available:
        note = performance.note if performance else "Performance data is unavailable."
        errors_html = ""
        if performance and performance.errors:
            errors_html = "<ul class=\"market-errors\">" + "".join(
                f"<li>{html.escape(error)}</li>" for error in performance.errors
            ) + "</ul>"
        return (
            "<article class=\"panel dashboard-card wide-card\">"
            "<div class=\"card-head\">"
            "<div><p class=\"eyebrow\">Performance</p><h2>Total asset value in the selected window</h2></div>"
            "</div>"
            f"{controls_html}"
            f"<p class=\"muted\">{html.escape(note)}</p>"
            f"{errors_html}"
            "</article>"
        )

    width = 760
    height = 280
    left = 52
    right = 18
    top = 14
    bottom = 34
    chart_width = width - left - right
    chart_height = height - top - bottom

    asset_values = [point.total_value for point in performance.points]
    asset_min = min(asset_values)
    asset_max = max(asset_values)
    asset_points = series_points(
        asset_values,
        width,
        height,
        left,
        top,
        chart_width,
        chart_height,
        asset_min,
        asset_max,
    )

    start_label = format_date_label(performance.points[0].trade_date)
    mid_label = format_date_label(performance.points[len(performance.points) // 2].trade_date)
    end_label = format_date_label(performance.points[-1].trade_date)
    asset_chart = render_chart(
        asset_points,
        width,
        height,
        left,
        right,
        top,
        bottom,
        asset_min,
        asset_max,
        labels=(start_label, mid_label, end_label),
        line_color="#cf5c36",
        area_color="#cf5c36",
    )
    total_return = performance.points[-1].total_return
    errors_html = ""
    if performance.errors:
        errors_html = "<ul class=\"market-errors\">" + "".join(
            f"<li>{html.escape(error)}</li>" for error in performance.errors
        ) + "</ul>"

    return f"""
    <article class="panel dashboard-card wide-card">
      <div class="card-head">
        <div>
          <p class="eyebrow">Performance</p>
          <h2>Total asset value in the selected window</h2>
        </div>
        <p class="muted">{html.escape(performance.note)}</p>
      </div>
      {controls_html}
      <div class="metric-strip metric-strip-3">
        <div>
          <span class="metric-label">Window return</span>
          <strong class="{'metric-up' if total_return >= 0 else 'metric-down'}">{html.escape(format_signed_percent(total_return * 100, decimals=1))}</strong>
        </div>
        <div>
          <span class="metric-label">Window start value</span>
          <strong>{html.escape(format_currency(performance.points[0].total_value))}</strong>
        </div>
        <div>
          <span class="metric-label">Window end value</span>
          <strong>{html.escape(format_currency(performance.points[-1].total_value))}</strong>
        </div>
      </div>
      <div class="performance-panel">
        <h3>Total asset value</h3>
        {asset_chart}
      </div>
      {errors_html}
    </article>
    """


def render_dashboard(
    dashboard: PortfolioDashboard | None,
    performance: PortfolioPerformanceView | None = None,
    window_key: str = "1y",
    start_raw: str = "",
    end_raw: str = "",
) -> str:
    if dashboard is None:
        return (
            "<section class=\"dashboard-grid\">"
            "<article class=\"panel dashboard-card empty-dashboard wide-card\">"
            "<p class=\"eyebrow\">Portfolio Dashboard</p>"
            "<h2>No cleaned portfolio file was found.</h2>"
            "<p>Place a Yahoo Finance export at <code>data/portfolio.cleaned.csv</code> and the homepage will render current holdings and historical position changes automatically.</p>"
            "</article>"
            "</section>"
        )

    performance_lookup = {
        item.symbol: item.return_pct for item in (performance.holdings if performance else [])
    }
    holdings_html = render_exposure_rows(dashboard.holdings, performance_lookup=performance_lookup)
    history_html = render_history_chart(dashboard)
    transactions_html = render_recent_transactions(dashboard.recent_transactions)
    performance_html = render_performance_section(
        performance,
        window_key=window_key,
        start_raw=start_raw,
        end_raw=end_raw,
    )
    holdings_count = len(dashboard.holdings)
    realized_class = "metric-up" if dashboard.total_realized_pnl >= 0 else "metric-down"
    pnl_class = "metric-up" if dashboard.total_unrealized_pnl >= 0 else "metric-down"
    holdings_table_html = "".join(
        "<div class=\"table-row\">"
        f"<strong>{html.escape(holding.symbol)}</strong>"
        f"<span>{html.escape(format_share_quantity(holding.quantity))} sh</span>"
        f"<span>{html.escape(format_currency(holding.market_value))}</span>"
        "</div>"
        for holding in dashboard.holdings
    )

    return f"""
    <section class="dashboard-grid">
      <article class="panel dashboard-card wide-card hero-metrics">
        <div class="metric-strip">
          <div>
            <span class="metric-label">Total market value</span>
            <strong>{html.escape(format_currency(dashboard.total_market_value))}</strong>
          </div>
          <div>
            <span class="metric-label">Realized P/L</span>
            <strong class="{realized_class}">{html.escape(format_signed_currency(dashboard.total_realized_pnl))}</strong>
          </div>
          <div>
            <span class="metric-label">Unrealized P/L</span>
            <strong class="{pnl_class}">{html.escape(format_signed_currency(dashboard.total_unrealized_pnl))}</strong>
          </div>
          <div>
            <span class="metric-label">Active holdings</span>
            <strong>{holdings_count}</strong>
          </div>
          <div>
            <span class="metric-label">History span</span>
            <strong>{html.escape(format_date_label(dashboard.start_date))} to {html.escape(format_date_label(dashboard.end_date))}</strong>
          </div>
        </div>
      </article>
      {performance_html}
      <article class="panel dashboard-card wide-card">
        <div class="card-head">
          <div>
            <p class="eyebrow">Current Exposure</p>
            <h2>What the portfolio looks like now</h2>
          </div>
          <p class="muted">As of {html.escape(dashboard.as_of_label or format_date_label(dashboard.end_date))}</p>
        </div>
        <div class="exposure-stack">{holdings_html}</div>
      </article>
      <article class="panel dashboard-card wide-card">
        <div class="card-head">
          <div>
            <p class="eyebrow">Holding Path</p>
            <h2>How the major positions changed over time</h2>
          </div>
          <p class="muted">Tracked symbols: {html.escape(", ".join(dashboard.history_symbols))}</p>
        </div>
        {history_html}
      </article>
      <article class="panel dashboard-card">
        <div class="card-head">
          <div>
            <p class="eyebrow">Holdings Table</p>
            <h2>Current positions</h2>
          </div>
        </div>
        <div class="table-stack">{holdings_table_html}</div>
      </article>
      <article class="panel dashboard-card">
        <div class="card-head">
          <div>
            <p class="eyebrow">Recent Activity</p>
            <h2>Latest transactions</h2>
          </div>
          <p class="muted">{dashboard.transaction_count} trades in the cleaned history</p>
        </div>
        <div class="transaction-stack">{transactions_html}</div>
      </article>
    </section>
    """


def render_result_panel(
    profile: InvestorProfile,
    result: AnalysisResult,
    market_snapshot: MarketDataSnapshot | None = None,
) -> str:
    market_panel_html = render_market_data_panel(market_snapshot) if market_snapshot else ""
    return f"""
    <section class="panel result-panel" id="report">
      <div class="panel-head">
        <p class="eyebrow">Strategy Snapshot</p>
        <h2>{html.escape(RISK_LABELS[result.risk_level])} Portfolio Framework</h2>
        <p>Your objective is {html.escape(OBJECTIVE_LABELS[profile.objective])}. The portfolio should be built around diversified core exposures rather than concentrated theme bets.</p>
      </div>
      <div class="stat-grid">
        <article class="stat-card">
          <span>Risk Profile</span>
          <strong>{html.escape(RISK_LABELS[result.risk_level])}</strong>
        </article>
        <article class="stat-card">
          <span>Investable Capital</span>
          <strong>{html.escape(format_currency(profile.capital))}</strong>
        </article>
        <article class="stat-card">
          <span>Mapped Holdings</span>
          <strong>{html.escape(format_currency(result.invested_amount))}</strong>
        </article>
        <article class="stat-card">
          <span>Cash Ratio</span>
          <strong>{html.escape(format_percent(result.cash_ratio))}</strong>
        </article>
      </div>
      <div class="result-grid">
        <article class="glass-card">
          <h3>Target Allocation</h3>
          <div class="allocation-stack">{render_allocation_bars(result.allocation)}</div>
        </article>
        <article class="glass-card">
          <h3>Current Holdings</h3>
          <div class="holding-stack">{render_positions(profile.positions)}</div>
        </article>
        <article class="glass-card">
          <h3>Risk Flags</h3>
          <ul>{render_list(result.concentration_warnings)}</ul>
        </article>
        <article class="glass-card">
          <h3>Action Plan</h3>
          <ul>{render_list(result.rebalance_actions)}</ul>
        </article>
        {market_panel_html}
        <article class="glass-card wide-card">
          <h3>Portfolio Principles</h3>
          <ul>{render_list(result.principles)}</ul>
        </article>
      </div>
    </section>
    """


def render_analysis_tools(
    form_values: dict[str, str],
    report_html: str = "",
    errors: dict[str, str] | None = None,
) -> str:
    errors = errors or {}
    status_note = (
        "<div class=\"notice notice-error\">Fix the highlighted input issues and submit again.</div>"
        if errors
        else "<div class=\"notice\">This analysis form is secondary now. Use it when you want a quick allocation opinion on top of the position dashboard.</div>"
    )
    positions_value = html.escape(form_values.get("positions", ""))

    return f"""
    <section class="planning-shell" id="analysis-tools">
      <div class="section-header">
        <div>
          <p class="eyebrow">Secondary Tool</p>
          <h2>Allocation and risk profile form</h2>
        </div>
        <a class="ghost-link" href="/">Back to dashboard</a>
      </div>
      <div class="planning-grid">
        <aside class="panel planning-panel">
          <div class="panel-head">
            <h2>Run a planning pass</h2>
            <p>This still uses the original heuristic analysis if you want an allocation baseline.</p>
          </div>
          {status_note}
          <form method="post" action="/analyze">
            <div class="field-row">
              <div class="field-group">
                <label for="capital">Investable capital</label>
                <input id="capital" name="capital" inputmode="decimal" value="{html.escape(form_values.get("capital", ""))}" placeholder="100000">
                {render_error("capital", errors)}
              </div>
              <div class="field-group">
                <label for="monthly_contribution">Monthly contribution</label>
                <input id="monthly_contribution" name="monthly_contribution" inputmode="decimal" value="{html.escape(form_values.get("monthly_contribution", ""))}" placeholder="3000">
                {render_error("monthly_contribution", errors)}
              </div>
            </div>
            <div class="field-row">
              <div class="field-group">
                <label for="horizon_years">Investment horizon (years)</label>
                <input id="horizon_years" name="horizon_years" inputmode="numeric" value="{html.escape(form_values.get("horizon_years", ""))}" placeholder="10">
                {render_error("horizon_years", errors)}
              </div>
              <div class="field-group">
                <label for="max_drawdown">Max drawdown tolerance (%)</label>
                <input id="max_drawdown" name="max_drawdown" inputmode="numeric" value="{html.escape(form_values.get("max_drawdown", ""))}" placeholder="20">
                {render_error("max_drawdown", errors)}
              </div>
            </div>
            <div class="field-group">
              <label>Primary objective</label>
              <div class="choice-grid">{render_options(form_values.get("objective", "balanced"))}</div>
              {render_error("objective", errors)}
            </div>
            <div class="field-group">
              <label for="positions">Current holdings</label>
              <textarea id="positions" name="positions" placeholder="VTI:40000, BND:15000, QQQ:10000">{positions_value}</textarea>
              <p class="hint">This field is prefilled from <code>data/portfolio.cleaned.csv</code>, but you can override it manually.</p>
              {render_error("positions", errors)}
            </div>
            <div class="submit-row">
              <button type="submit">Generate Plan</button>
              <a class="ghost-link" href="/">Reset</a>
            </div>
          </form>
        </aside>
        {report_html or '''
        <section class="panel result-panel empty-analysis">
          <div class="inner">
            <p class="eyebrow">Analysis</p>
            <h2>The original planning output still lives here.</h2>
            <p>If you fill the form, the page will append the risk profile, target allocation, concentration checks, and the live Alpha Vantage quote panel below.</p>
          </div>
        </section>
        '''}
      </div>
    </section>
    """


def render_page(
    form_values: dict[str, str],
    dashboard_html: str,
    errors: dict[str, str] | None = None,
    report_html: str = "",
) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Stratum</title>
  <style>
    :root {{
      --bg: #f4efe4;
      --ink: #14281d;
      --muted: #5c685d;
      --paper: rgba(255, 251, 244, 0.76);
      --stroke: rgba(20, 40, 29, 0.12);
      --accent: #cf5c36;
      --accent-2: #2d6a4f;
      --accent-3: #d4a373;
      --shadow: 0 18px 60px rgba(20, 40, 29, 0.12);
      --radius: 28px;
      --font: "Avenir Next", "IBM Plex Sans", "Segoe UI", sans-serif;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: var(--font);
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(207, 92, 54, 0.18), transparent 32%),
        radial-gradient(circle at 85% 15%, rgba(45, 106, 79, 0.18), transparent 28%),
        linear-gradient(180deg, #f7f2e8 0%, var(--bg) 100%);
      min-height: 100vh;
    }}
    .shell {{
      width: min(1180px, calc(100% - 32px));
      margin: 0 auto;
      padding: 28px 0 56px;
    }}
    .hero {{
      position: relative;
      overflow: hidden;
      background: linear-gradient(135deg, rgba(20, 40, 29, 0.96), rgba(45, 106, 79, 0.92));
      color: #f9f7f1;
      border-radius: 36px;
      padding: 36px;
      box-shadow: var(--shadow);
    }}
    .hero::after {{
      content: "";
      position: absolute;
      inset: auto -40px -80px auto;
      width: 280px;
      height: 280px;
      border-radius: 50%;
      background: rgba(212, 163, 115, 0.16);
      filter: blur(10px);
    }}
    .hero-grid {{
      display: grid;
      grid-template-columns: minmax(0, 1.25fr) minmax(280px, 0.75fr);
      gap: 28px;
      align-items: end;
      position: relative;
      z-index: 1;
    }}
    .eyebrow {{
      text-transform: uppercase;
      letter-spacing: 0.16em;
      font-size: 12px;
      margin: 0 0 12px;
      opacity: 0.74;
    }}
    h1 {{
      font-size: clamp(2.3rem, 6vw, 4.6rem);
      line-height: 0.94;
      margin: 0 0 16px;
      max-width: 10ch;
    }}
    .hero p {{
      margin: 0;
      font-size: 1rem;
      line-height: 1.7;
      color: rgba(249, 247, 241, 0.82);
      max-width: 58ch;
    }}
    .hero-aside {{
      background: rgba(255, 255, 255, 0.08);
      border: 1px solid rgba(255, 255, 255, 0.12);
      backdrop-filter: blur(10px);
      border-radius: 28px;
      padding: 22px;
    }}
    .hero-aside strong {{
      display: block;
      font-size: 1.8rem;
      margin-bottom: 6px;
    }}
    .hero-cta {{
      display: inline-flex;
      margin-top: 22px;
      align-items: center;
      gap: 10px;
      padding: 12px 18px;
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.12);
      color: #f9f7f1;
      text-decoration: none;
      font-weight: 700;
    }}
    .dashboard-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 24px;
      margin-top: 24px;
    }}
    .panel {{
      background: var(--paper);
      border: 1px solid var(--stroke);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      backdrop-filter: blur(12px);
    }}
    .dashboard-card,
    .planning-panel,
    .result-panel {{
      padding: 28px;
    }}
    .wide-card {{ grid-column: 1 / -1; }}
    .panel-head h2 {{
      margin: 0;
      font-size: 1.6rem;
    }}
    .panel-head p {{
      margin: 10px 0 0;
      color: var(--muted);
      line-height: 1.6;
    }}
    .notice {{
      margin: 20px 0 0;
      padding: 14px 16px;
      border-radius: 18px;
      background: rgba(45, 106, 79, 0.08);
      color: var(--ink);
      font-size: 0.95rem;
    }}
    .notice-error {{
      background: rgba(207, 92, 54, 0.12);
      color: #8a2d14;
    }}
    form {{
      margin-top: 22px;
      display: grid;
      gap: 16px;
    }}
    .field-group {{
      display: grid;
      gap: 8px;
    }}
    .field-row {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 14px;
    }}
    label {{
      font-weight: 600;
      font-size: 0.95rem;
    }}
    input[type="text"],
    input[type="number"],
    input[type="date"],
    select,
    textarea {{
      width: 100%;
      border: 1px solid rgba(20, 40, 29, 0.14);
      border-radius: 18px;
      padding: 14px 16px;
      font: inherit;
      color: var(--ink);
      background: rgba(255, 255, 255, 0.72);
      transition: border-color 140ms ease, transform 140ms ease, box-shadow 140ms ease;
    }}
    input:focus,
    select:focus,
    textarea:focus {{
      outline: none;
      border-color: rgba(207, 92, 54, 0.7);
      box-shadow: 0 0 0 4px rgba(207, 92, 54, 0.12);
      transform: translateY(-1px);
    }}
    textarea {{
      min-height: 110px;
      resize: vertical;
    }}
    .hint {{
      color: var(--muted);
      font-size: 0.86rem;
      line-height: 1.5;
    }}
    .choice-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
    }}
    .choice-card {{
      position: relative;
      display: flex;
      align-items: stretch;
    }}
    .choice-card input {{
      position: absolute;
      opacity: 0;
      pointer-events: none;
    }}
    .choice-card span {{
      width: 100%;
      padding: 14px 12px;
      border-radius: 18px;
      border: 1px solid rgba(20, 40, 29, 0.12);
      background: rgba(255, 255, 255, 0.72);
      text-align: center;
      font-weight: 600;
      transition: all 140ms ease;
    }}
    .choice-card input:checked + span {{
      border-color: rgba(207, 92, 54, 0.5);
      background: rgba(207, 92, 54, 0.12);
      color: #8a2d14;
      transform: translateY(-1px);
    }}
    .field-error {{
      margin: 0;
      color: #b23a1b;
      font-size: 0.86rem;
    }}
    .submit-row {{
      display: flex;
      gap: 12px;
      align-items: center;
      flex-wrap: wrap;
      margin-top: 6px;
    }}
    button {{
      border: 0;
      border-radius: 999px;
      padding: 14px 24px;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
      background: linear-gradient(135deg, var(--accent), #d97743);
      color: #fffaf5;
      box-shadow: 0 12px 30px rgba(207, 92, 54, 0.24);
    }}
    .ghost-link {{
      color: var(--accent-2);
      text-decoration: none;
      font-weight: 600;
    }}
    .section-header,
    .card-head {{
      display: flex;
      align-items: end;
      justify-content: space-between;
      gap: 20px;
      margin-bottom: 18px;
    }}
    .section-header h2,
    .card-head h2 {{
      margin: 0;
      font-size: 1.5rem;
    }}
    .metric-strip {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 14px;
    }}
    .metric-strip-3 {{
      grid-template-columns: repeat(3, minmax(0, 1fr));
      margin: 18px 0;
    }}
    .metric-strip div {{
      padding: 18px;
      border-radius: 22px;
      background: linear-gradient(180deg, rgba(255,255,255,0.92), rgba(255,255,255,0.68));
      border: 1px solid rgba(20, 40, 29, 0.08);
    }}
    .metric-label {{
      display: block;
      color: var(--muted);
      font-size: 0.88rem;
      margin-bottom: 10px;
    }}
    .metric-strip strong {{
      font-size: 1.35rem;
    }}
    .metric-up {{ color: #0f5132; }}
    .metric-down {{ color: #842029; }}
    .stat-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      margin-top: 22px;
    }}
    .stat-card {{
      padding: 18px;
      border-radius: 22px;
      background: linear-gradient(180deg, rgba(255,255,255,0.92), rgba(255,255,255,0.68));
      border: 1px solid rgba(20, 40, 29, 0.08);
    }}
    .stat-card span {{
      display: block;
      color: var(--muted);
      font-size: 0.88rem;
      margin-bottom: 10px;
    }}
    .stat-card strong {{
      font-size: 1.35rem;
    }}
    .result-grid {{
      margin-top: 18px;
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 16px;
    }}
    .glass-card {{
      padding: 22px;
      border-radius: 24px;
      background: linear-gradient(180deg, rgba(255,255,255,0.88), rgba(255,255,255,0.64));
      border: 1px solid rgba(20, 40, 29, 0.08);
    }}
    h3 {{
      margin: 0 0 16px;
      font-size: 1.08rem;
    }}
    .exposure-stack,
    .allocation-stack,
    .holding-stack,
    .market-stack,
    .table-stack,
    .transaction-stack {{
      display: grid;
      gap: 14px;
    }}
    .allocation-row {{
      display: grid;
      gap: 8px;
    }}
    .exposure-row,
    .table-row,
    .transaction-row {{
      padding: 16px 18px;
      border-radius: 20px;
      background: linear-gradient(180deg, rgba(255,255,255,0.9), rgba(255,255,255,0.68));
      border: 1px solid rgba(20, 40, 29, 0.08);
    }}
    .exposure-head,
    .exposure-meta,
    .allocation-meta,
    .holding-row,
    .table-row,
    .transaction-row,
    .transaction-main {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }}
    .exposure-head strong,
    .table-row strong,
    .transaction-main strong {{
      font-size: 1rem;
    }}
    .exposure-head span,
    .exposure-meta span,
    .table-row span,
    .transaction-row span {{
      color: var(--muted);
      font-size: 0.9rem;
      line-height: 1.5;
    }}
    .exposure-value {{
      text-align: right;
    }}
    .exposure-bar {{
      margin: 12px 0 10px;
      height: 12px;
      border-radius: 999px;
      background: rgba(20, 40, 29, 0.08);
      overflow: hidden;
    }}
    .exposure-bar span {{
      display: block;
      height: 100%;
      border-radius: inherit;
    }}
    .history-card-body {{
      display: grid;
      gap: 16px;
    }}
    .history-chart {{
      width: 100%;
      height: auto;
      display: block;
      background:
        linear-gradient(180deg, rgba(255,255,255,0.94), rgba(255,255,255,0.78));
      border-radius: 22px;
      border: 1px solid rgba(20, 40, 29, 0.08);
      padding: 4px;
    }}
    .chart-grid {{
      stroke: rgba(20, 40, 29, 0.12);
      stroke-width: 1;
    }}
    .chart-axis-label {{
      fill: #5c685d;
      font-size: 11px;
      font-family: var(--font);
    }}
    .legend-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
    }}
    .legend-item {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 10px 12px;
      border-radius: 999px;
      background: rgba(20, 40, 29, 0.06);
    }}
    .legend-item span {{
      color: var(--muted);
      font-size: 0.88rem;
    }}
    .legend-swatch {{
      width: 12px;
      height: 12px;
      border-radius: 50%;
    }}
    .window-form {{
      margin: 10px 0 18px;
    }}
    .window-row {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      align-items: end;
    }}
    .compact-field label {{
      font-size: 0.84rem;
    }}
    .performance-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 16px;
    }}
    .performance-panel {{
      display: grid;
      gap: 12px;
    }}
    .transaction-badge {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 52px;
      padding: 4px 8px;
      border-radius: 999px;
      font-size: 0.78rem;
      font-weight: 700;
    }}
    .side-buy {{
      background: rgba(45, 106, 79, 0.16);
      color: #0f5132;
    }}
    .side-sell {{
      background: rgba(154, 3, 30, 0.14);
      color: #842029;
    }}
    .market-row {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(0, 1.2fr) auto;
      gap: 14px;
      align-items: center;
      padding: 14px 16px;
      border-radius: 18px;
      background: rgba(20, 40, 29, 0.05);
    }}
    .market-symbol,
    .market-meta,
    .market-change {{
      display: grid;
      gap: 4px;
    }}
    .market-symbol strong,
    .market-change strong {{
      font-size: 1rem;
    }}
    .market-symbol span,
    .market-meta span,
    .market-note,
    .market-errors {{
      color: var(--muted);
      font-size: 0.9rem;
      line-height: 1.55;
    }}
    .market-change {{
      justify-items: end;
      text-align: right;
    }}
    .quote-badge {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 86px;
      padding: 6px 10px;
      border-radius: 999px;
      font-weight: 700;
      font-size: 0.84rem;
    }}
    .quote-positive {{
      color: #0f5132;
      background: rgba(45, 106, 79, 0.16);
    }}
    .quote-negative {{
      color: #842029;
      background: rgba(154, 3, 30, 0.14);
    }}
    .quote-neutral {{
      color: #374151;
      background: rgba(20, 40, 29, 0.1);
    }}
    .market-errors {{
      margin: 14px 0 0;
      padding-left: 18px;
    }}
    .allocation-bar {{
      height: 12px;
      border-radius: 999px;
      background: rgba(20, 40, 29, 0.08);
      overflow: hidden;
    }}
    .allocation-bar span {{
      display: block;
      height: 100%;
      border-radius: inherit;
    }}
    .tone-a {{ background: linear-gradient(90deg, #cf5c36, #e07a5f); }}
    .tone-b {{ background: linear-gradient(90deg, #2d6a4f, #40916c); }}
    .tone-c {{ background: linear-gradient(90deg, #d4a373, #ddb892); }}
    .tone-d {{ background: linear-gradient(90deg, #5f0f40, #9a031e); }}
    .tone-e {{ background: linear-gradient(90deg, #3a5a40, #588157); }}
    ul {{
      margin: 0;
      padding-left: 18px;
      color: var(--ink);
      line-height: 1.75;
    }}
    .muted {{
      margin: 0;
      color: var(--muted);
      line-height: 1.7;
    }}
    .empty-state {{
      height: 100%;
      display: grid;
      place-items: center;
      min-height: 520px;
      text-align: left;
      background:
        linear-gradient(135deg, rgba(255,255,255,0.76), rgba(255,255,255,0.58)),
        radial-gradient(circle at top right, rgba(45,106,79,0.12), transparent 28%);
    }}
    .empty-state .inner {{
      max-width: 520px;
      padding: 12px;
    }}
    .empty-state h2 {{
      font-size: clamp(2rem, 4vw, 3rem);
      margin: 0 0 14px;
      line-height: 1.02;
    }}
    .empty-state p {{
      margin: 0 0 16px;
      color: var(--muted);
      line-height: 1.75;
    }}
    .pill-row {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 18px;
    }}
    .pill {{
      padding: 10px 14px;
      border-radius: 999px;
      background: rgba(20, 40, 29, 0.08);
      color: var(--ink);
      font-size: 0.92rem;
    }}
    .planning-shell {{
      margin-top: 30px;
    }}
    .planning-grid {{
      display: grid;
      grid-template-columns: minmax(320px, 420px) minmax(0, 1fr);
      gap: 24px;
      margin-top: 18px;
      align-items: start;
    }}
    .empty-analysis {{
      min-height: 420px;
      display: grid;
      place-items: center;
      background:
        linear-gradient(135deg, rgba(255,255,255,0.76), rgba(255,255,255,0.58)),
        radial-gradient(circle at top right, rgba(45,106,79,0.12), transparent 28%);
    }}
    .empty-dashboard {{
      min-height: 280px;
      display: grid;
      align-content: center;
    }}
    @media (max-width: 980px) {{
      .dashboard-grid,
      .hero-grid,
      .planning-grid,
      .metric-strip {{
        grid-template-columns: 1fr;
      }}
      .performance-grid,
      .window-row {{
        grid-template-columns: 1fr;
      }}
      .choice-grid,
      .field-row,
      .market-row {{
        grid-template-columns: 1fr;
      }}
      .shell {{
        width: min(100% - 20px, 1180px);
        padding-top: 10px;
      }}
      .hero,
      .planning-panel,
      .result-panel {{
        border-radius: 28px;
      }}
      .section-header,
      .card-head,
      .exposure-head,
      .transaction-row,
      .table-row {{
        display: grid;
      }}
    }}
  </style>
</head>
<body>
  <main class="shell">
    <section class="hero">
      <div class="hero-grid">
        <div>
          <p class="eyebrow">Stratum</p>
          <h1>See the portfolio, not the questionnaire.</h1>
          <p>The homepage now starts from your actual Yahoo Finance history. It surfaces current exposure, how positions were built and trimmed over time, and only keeps the old planning form as a secondary tool.</p>
          <a class="hero-cta" href="#analysis-tools">Use the old analysis form</a>
        </div>
        <aside class="hero-aside">
          <strong>CSV-driven dashboard</strong>
          <p>The page reads <code>data/portfolio.cleaned.csv</code>, reconstructs your current holdings, and visualizes the holding path directly from the transaction history you exported from Yahoo Finance.</p>
        </aside>
      </div>
    </section>
    {dashboard_html}
    {render_analysis_tools(form_values, report_html=report_html, errors=errors)}
  </main>
</body>
</html>
"""


def build_dashboard_html(
    window_key: str = "1y", start_raw: str = "", end_raw: str = ""
) -> str:
    dashboard = load_portfolio_dashboard()
    performance = None
    if dashboard is not None:
        performance = build_portfolio_performance(
            dashboard,
            window_key=window_key,
            start_raw=start_raw,
            end_raw=end_raw,
        )
    return render_dashboard(
        dashboard,
        performance=performance,
        window_key=window_key,
        start_raw=start_raw,
        end_raw=end_raw,
    )


class StratumHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed_url = urlparse(self.path)
        if parsed_url.path not in {"/", "/index.html"}:
            self.send_error(HTTPStatus.NOT_FOUND, "Page not found")
            return
        query = parse_qs(parsed_url.query, keep_blank_values=True)
        window_key = query.get("window", ["1y"])[-1]
        start_raw = query.get("start", [""])[-1]
        end_raw = query.get("end", [""])[-1]
        self.respond_html(
            render_page(
                build_default_form_values(),
                dashboard_html=build_dashboard_html(
                    window_key=window_key,
                    start_raw=start_raw,
                    end_raw=end_raw,
                ),
            )
        )

    def do_POST(self) -> None:
        if self.path != "/analyze":
            self.send_error(HTTPStatus.NOT_FOUND, "Page not found")
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length).decode("utf-8")
        parsed = parse_qs(raw_body, keep_blank_values=True)
        form_values = {key: values[-1] if values else "" for key, values in parsed.items()}
        values, errors = validate_profile_form(form_values)
        if errors:
            self.respond_html(
                render_page(
                    values,
                    dashboard_html=build_dashboard_html(),
                    errors=errors,
                ),
                status=HTTPStatus.BAD_REQUEST,
            )
            return

        profile = build_profile(
            values["capital"],
            values["monthly_contribution"],
            values["horizon_years"],
            values["max_drawdown"],
            values["objective"],
            values["positions"],
        )
        result = run_analysis(profile)
        market_snapshot = build_market_data_snapshot(profile)
        report_html = render_result_panel(profile, result, market_snapshot=market_snapshot)
        self.respond_html(
            render_page(
                values,
                dashboard_html=build_dashboard_html(),
                report_html=report_html,
            )
        )

    def log_message(self, format: str, *args: object) -> None:
        return

    def respond_html(self, body: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def run_server(host: str, port: int) -> None:
    server = ThreadingHTTPServer((host, port), StratumHandler)
    print(f"Stratum web server is running at http://{host}:{port}")
    print("Press Ctrl+C to stop the server.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        server.server_close()
