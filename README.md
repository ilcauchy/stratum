# Stratum

Stratum is a locally hosted investment research prototype. It runs on the Python standard library and is designed to grow into a layered market analysis system for portfolio planning, visualization, technical work, level analysis, and fundamentals.

Current capabilities:

- Generate a risk profile from horizon, drawdown tolerance, and portfolio objective
- Suggest a baseline asset allocation
- Check position concentration and cash weight
- Produce contribution and rebalancing guidance
- Pull the latest provider quote data for holdings tickers through Alpha Vantage
- Render the workflow in a local web page

## Project Layout

```text
stratum/
  analysis.py      # portfolio logic and allocation rules
  app.py           # CLI/Web entry wiring
  cli.py           # terminal prompts and report output
  config.py        # constants and environment loading
  formatters.py    # display formatting helpers
  market_data.py   # Alpha Vantage client and quote snapshots
  models.py        # dataclasses for profiles, results, and quotes
  parsing.py       # input parsing and validation
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

This project now supports live provider-backed quote lookups, but it still does not connect to brokers, research feeds, portfolio backtests, or transaction history. Right now it is best used as:

- A personal investment planning tool
- An allocation discussion prototype
- A base layer for later expansion into market data, backtesting, and LLM workflows

## Good Next Steps

1. Add fund and stock metadata beyond simple quotes
2. Add portfolio backtests with drawdown and return analysis
3. Add saved portfolios, snapshots, and multi-account management
4. Add LLM-powered natural language Q&A
