# Stratum

Stratum is a locally hosted investment research prototype. It runs on the Python standard library and is designed to grow into a layered market analysis system for portfolio planning, visualization, technical work, level analysis, and fundamentals.

Current capabilities:

- Generate a risk profile from horizon, drawdown tolerance, and portfolio objective
- Suggest a baseline asset allocation
- Check position concentration and cash weight
- Produce contribution and rebalancing guidance
- Pull the latest provider quote data for holdings tickers through Alpha Vantage
- Rebuild a portfolio dashboard from transaction history in `data/portfolio.cleaned.csv`
- Clean a raw Yahoo Finance export into a reconciled transaction ledger
- Render the workflow in a local web page

## Project Layout

```text
clean_portfolio_csv.py  # turns raw Yahoo exports into cleaned ledger files
data/                   # raw and cleaned portfolio CSV files
stratum/
  analysis.py      # portfolio logic and allocation rules
  app.py           # CLI/Web entry wiring
  cli.py           # terminal prompts and report output
  config.py        # constants and environment loading
  formatters.py    # display formatting helpers
  market_data.py   # Alpha Vantage client and quote snapshots
  models.py        # dataclasses for profiles, results, and quotes
  parsing.py       # input parsing and validation
  performance.py   # portfolio performance windows and chart inputs
  portfolio_csv.py # transaction parsing, holdings, and CSV reconciliation
  web.py           # HTML rendering and HTTP server
main.py            # thin executable entrypoint
test_main.py       # regression tests
```

## Run It

Start the web app:

```bash
python3 main.py
```

Then open:

```text
http://127.0.0.1:8000
```

Use a different host or port if needed:

```bash
python3 main.py --host 127.0.0.1 --port 9000
```

If you still want the CLI flow:

```bash
python3 main.py --cli
```

## Market Data Setup

The app automatically loads a local `.env` file if it exists.

Example:

```bash
ALPHAVANTAGE_API_KEY=your_api_key_here
```

You can still use shell environment variables if you prefer:

```bash
export ALPHAVANTAGE_API_KEY=your_api_key_here
```

Optional:

```bash
export ALPHAVANTAGE_ENTITLEMENT=delayed
```

The app uses Alpha Vantage's `GLOBAL_QUOTE` endpoint for holdings tickers. Without premium entitlements, the latest quote may be end-of-day rather than real-time for some markets.

## Portfolio CSV Cleaning

The dashboard reads `data/portfolio.cleaned.csv`. If you start from a raw Yahoo Finance export, clean it first:

```bash
python3 clean_portfolio_csv.py
```

By default this reads `data/portfolio.csv` and writes `data/portfolio.cleaned.csv`.
It also auto-reconciles any symbol whose ending quantity is negative by adding a synthetic row back to `0`, which is useful when dividend reinvestments or similar adjustments were missing from the raw export.

If a symbol was oversold because dividend reinvestments or other adjustments were missing from the raw export, add a synthetic reconciliation row to force the ending quantity you expect:

```bash
python3 clean_portfolio_csv.py --zero-symbol AAPL --zero-symbol ARKW
```

You can also force an exact ending quantity:

```bash
python3 clean_portfolio_csv.py --set-position SOFI=120
```

The script prints reconciliation notes so you can see which synthetic rows were added.

## Inputs

- Investable capital
- Monthly contribution
- Investment horizon
- Maximum drawdown tolerance
- Primary objective
- Current holdings

Holdings input example:

```text
VTI:30000,BND:15000,QQQ:10000
```

Multiline input also works:

```text
VTI:30000
BND:15000
QQQ:10000
```

## Scope

This project now supports live provider-backed quote lookups and transaction-history-driven dashboard views, but it still does not connect to brokers, research feeds, or automatic corporate action reconciliation. Right now it is best used as:

- A personal investment planning tool
- An allocation discussion prototype
- A base layer for later expansion into market data, backtesting, and LLM workflows

## Good Next Steps

1. Add fund and stock metadata beyond simple quotes
2. Add portfolio backtests with drawdown and return analysis
3. Add saved portfolios, snapshots, and multi-account management
4. Add LLM-powered natural language Q&A
