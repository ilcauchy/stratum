from __future__ import annotations

import html
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

from .analysis import run_analysis
from .config import DEFAULT_FORM_VALUES, OBJECTIVE_LABELS, RISK_LABELS
from .formatters import (
    format_currency,
    format_number,
    format_percent,
    format_signed_number,
    format_signed_percent,
)
from .market_data import build_market_data_snapshot
from .models import AnalysisResult, InvestorProfile, MarketDataSnapshot
from .parsing import build_profile, validate_profile_form


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


def render_page(
    form_values: dict[str, str],
    errors: dict[str, str] | None = None,
    report_html: str = "",
) -> str:
    errors = errors or {}
    status_note = (
        "<div class=\"notice notice-error\">Fix the highlighted input issues and submit again.</div>"
        if errors
        else "<div class=\"notice\">Enter a portfolio scenario and the page will generate a practical baseline plan.</div>"
    )
    positions_value = html.escape(form_values.get("positions", ""))

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
      grid-template-columns: minmax(0, 1.2fr) minmax(280px, 0.8fr);
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
    .grid {{
      display: grid;
      grid-template-columns: minmax(320px, 420px) minmax(0, 1fr);
      gap: 24px;
      margin-top: 24px;
      align-items: start;
    }}
    .panel {{
      background: var(--paper);
      border: 1px solid var(--stroke);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      backdrop-filter: blur(12px);
    }}
    .form-panel {{
      padding: 28px;
      position: sticky;
      top: 16px;
    }}
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
    .result-panel {{
      padding: 28px;
      min-height: 100%;
    }}
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
    .wide-card {{
      grid-column: 1 / -1;
    }}
    h3 {{
      margin: 0 0 16px;
      font-size: 1.08rem;
    }}
    .allocation-stack,
    .holding-stack,
    .market-stack {{
      display: grid;
      gap: 12px;
    }}
    .allocation-row {{
      display: grid;
      gap: 8px;
    }}
    .allocation-meta,
    .holding-row {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
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
    @media (max-width: 980px) {{
      .grid,
      .hero-grid,
      .result-grid,
      .stat-grid {{
        grid-template-columns: 1fr;
      }}
      .form-panel {{
        position: static;
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
      .form-panel,
      .result-panel {{
        border-radius: 28px;
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
          <h1>Build the portfolio before chasing picks.</h1>
          <p>Use this page for a first-pass portfolio plan: enter capital, time horizon, drawdown tolerance, and current holdings, and it will return a baseline risk profile, target allocation, and execution checklist.</p>
        </div>
        <aside class="hero-aside">
          <strong>Runs locally</strong>
          <p>No third-party framework is required. Launch it with the Python standard library, connect an Alpha Vantage API key, and you can view portfolio planning output alongside provider-backed quote data.</p>
        </aside>
      </div>
    </section>
    <section class="grid">
      <aside class="panel form-panel">
        <div class="panel-head">
          <p class="eyebrow">Inputs</p>
          <h2>Build your investor profile</h2>
          <p>This form focuses on baseline asset allocation. It does not provide live prices or stock-picking signals.</p>
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
            <p class="hint">Use commas or new lines, for example `VTI:40000`. Leave it blank if you are starting a new portfolio.</p>
            {render_error("positions", errors)}
          </div>
          <div class="submit-row">
            <button type="submit">Generate Plan</button>
            <a class="ghost-link" href="/">Reset</a>
          </div>
        </form>
      </aside>
      {report_html or '''
      <section class="panel result-panel empty-state">
        <div class="inner">
          <p class="eyebrow">Output</p>
          <h2>Your plan will appear here.</h2>
          <p>Start with a realistic input set. A typical test case is a 10-year horizon, 20% drawdown tolerance, and core holdings split between a broad equity ETF and bonds.</p>
          <div class="pill-row">
            <span class="pill">Risk profile</span>
            <span class="pill">Asset allocation</span>
            <span class="pill">Concentration check</span>
            <span class="pill">Contribution plan</span>
          </div>
        </div>
      </section>
      '''}
    </section>
  </main>
</body>
</html>
"""


class StratumHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path not in {"/", "/index.html"}:
            self.send_error(HTTPStatus.NOT_FOUND, "Page not found")
            return
        self.respond_html(render_page(DEFAULT_FORM_VALUES))

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
            self.respond_html(render_page(values, errors=errors), status=HTTPStatus.BAD_REQUEST)
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
        self.respond_html(render_page(values, report_html=report_html))

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
