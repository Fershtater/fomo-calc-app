# FarmCalc

**Hyperliquid Perpetual Futures Farming Calculator** - A comprehensive CLI and FastAPI tool for calculating fees, funding, volume, and identifying safe entry windows for perpetual futures trading on Hyperliquid.

⚠️ **CRITICAL RISK DISCLAIMER**: High leverage trading is extremely risky and can result in total loss of capital. This tool is for **calculation and informational purposes only** and does **NOT execute trades**. Always do your own research and never risk more than you can afford to lose. No guarantees are provided.

## Table of Contents

- [Overview](#overview)
- [Key Concepts](#key-concepts)
- [Installation](#installation)
- [Configuration](#configuration)
- [CLI Usage](#cli-usage)
- [API Usage](#api-usage)
- [Telegram Setup](#telegram-setup)
- [Configuration Reference](#configuration-reference)
- [Architecture](#architecture)
- [Testing](#testing)
- [Deployment](#deployment)
- [Troubleshooting](#troubleshooting)

## Overview

FarmCalc is a paper-only tool that helps you:

- **Calculate trading costs**: Fees, funding payments, and expected PnL for perpetual futures positions
- **Plan volume farming**: Track progress toward volume targets with maker/taker fee modeling
- **Identify safe entry windows**: Score-based evaluation of market conditions for limit order entries
- **Monitor markets**: Background watcher with Telegram alerts for favorable conditions
- **Estimate fill probability**: Adaptive model for maker limit order fill likelihood

### What FarmCalc Does

- ✅ Fetches live market data from Hyperliquid public API
- ✅ Calculates fees, funding, and volume for trade planning
- ✅ Suggests maker-safe limit prices with offsets
- ✅ Scores market conditions for safe entry windows
- ✅ Sends Telegram alerts when conditions are favorable
- ✅ Tracks trades and farming progress in local JSON state
- ✅ Provides REST API for programmatic access

### What FarmCalc Does NOT Do

- ❌ Execute trades or place orders
- ❌ Access private keys or exchange credentials
- ❌ Provide trading advice or guarantees
- ❌ Store sensitive data or credentials

## Key Concepts

### Volume Farming

Volume farming involves generating trading volume (often for token rewards) by opening and closing positions. FarmCalc helps you:

- Track total volume generated toward a target
- Calculate expected fees for maker vs taker orders
- Estimate round-trip volume (open + close notional)
- Plan number of trades needed to reach targets

### Funding Rates

Perpetual futures charge funding rates (typically hourly) that are paid from longs to shorts (or vice versa if negative). FarmCalc:

- Calculates expected funding payments based on hold time
- Supports hourly and 8-hour funding rate interpretations
- Shows funding PnL in trade proposals

### Maker vs Taker Fees

- **Maker fees**: Lower fees (default 0.015%) for limit orders that add liquidity
- **Taker fees**: Higher fees (default 0.045%) for market orders that remove liquidity
- FarmCalc models fill probability to estimate expected fees

### Safe Entry Scoring

FarmCalc uses a score-based system (0-100) to evaluate safe entry conditions:

- **Spread score**: Tighter spreads = higher score
- **Mark deviation score**: Lower deviation from mark price = higher score
- **Oracle deviation score**: Lower deviation from oracle = higher score
- **Funding score**: Lower absolute funding rate = higher score
- **Liquidity score**: Higher 24h volume = higher score
- **Depth score**: Deeper order book = higher score

Default threshold: **80/100** triggers "safe window" alerts.

### Fill Probability Estimation

Adaptive model estimates likelihood of maker limit order fills based on:

- Spread tightness
- Order book depth vs order size
- Short-term price volatility
- Price offset aggressiveness
- Optional sentiment bias

User feedback improves calibration over time.

## Installation

### Requirements

- Python 3.9 or higher
- pip package manager

### Install from Source

```bash
# Clone or navigate to project directory
cd farmcalc

# Install dependencies
pip install -r requirements.txt

# Or install in editable mode (recommended)
pip install -e .
```

### Verify Installation

```bash
python -m farmcalc --help
```

## Configuration

### Environment Variables

**All sensitive data must be stored in environment variables.** Never commit secrets to version control.

#### Required for Telegram Control

```bash
# Telegram Bot (required)
export TELEGRAM_BOT_TOKEN="1234567890:ABCdefGHIjklMNOpqrsTUVwxyz"
export TELEGRAM_CHAT_ID="-1234567890"  # Group chat ID (negative for groups)
export TELEGRAM_OWNER_ID="123456789"  # Your Telegram user ID (single user)

# Telegram Webhook (optional, for production)
export TELEGRAM_WEBHOOK_URL="https://your-domain.com/telegram/webhook"
export TELEGRAM_SECRET_TOKEN="your-secret-token-here"  # Optional, for webhook verification

# Optional: Restrict to specific chat
export TELEGRAM_ALLOWED_CHAT_ID="-1234567890"  # Optional chat ID restriction
```

#### Optional Configuration

```bash
# Telegram settings
export TELEGRAM_PARSE_MODE="HTML"  # HTML or Markdown, default: HTML

# File paths (optional, defaults to ~/.farmcalc_*.json)
export FARM_STATE_PATH="$HOME/.farmcalc_state.json"
export WATCH_STATE_PATH="$HOME/.farmcalc_watch_state.json"
export COINGECKO_CACHE_PATH="$HOME/.farmcalc_coingecko_cache.json"

# Proposal settings
export PROPOSAL_EXPIRY_MINUTES="15"  # How long proposals remain valid
export TELEGRAM_SPAM_GUARD_SEC="15"  # Min seconds between proposal messages
export TELEGRAM_CONTROL_PLANE="true"  # Enable Telegram control features

# Logging (optional)
export LOG_FORMAT="json"  # or "text" (default: text)
export LOG_LEVEL="INFO"   # DEBUG, INFO, WARNING, ERROR

# API URLs (optional, defaults provided)
export HL_INFO_URL="https://api.hyperliquid.xyz/info"
```

### Environment File Example

Create `/etc/farmcalc.env` (or `~/.farmcalc.env`):

```bash
TELEGRAM_BOT_TOKEN=your_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
TELEGRAM_OWNER_ID=123456789
TELEGRAM_WEBHOOK_URL=https://your-domain.com/telegram/webhook
TELEGRAM_SECRET_TOKEN=your-secret-token
LOG_FORMAT=json
LOG_LEVEL=INFO
```

Load with: `source /etc/farmcalc.env` or use with systemd `EnvironmentFile`.

### State Files

FarmCalc stores state in JSON files:

- `~/.farmcalc_state.json`: Farming plan, statistics, and trades
- `~/.farmcalc_watch_state.json`: Watcher configuration and alert history
- `~/.farmcalc_coingecko_cache.json`: CoinGecko API cache (if used)

## CLI Usage

### Basic Commands

#### Initialize Plan

```bash
python -m farmcalc init \
  --deposit 1000 \
  --margin 100 \
  --leverage 10 \
  --target-volume 10000
```

Sets your farming plan parameters.

#### List Assets

```bash
# Sort by funding rate (default)
python -m farmcalc assets --sort funding --limit 20

# Sort by 24h volume
python -m farmcalc assets --sort volume --limit 25

# Sort by open interest
python -m farmcalc assets --sort oi --limit 10
```

#### Get Quote

```bash
python -m farmcalc quote BTC
```

Shows best bid/ask, mid, mark, oracle, and funding rate.

#### Propose Trade

```bash
python -m farmcalc propose BTC \
  --side LONG \
  --margin 100 \
  --leverage 10 \
  --hold-min 60 \
  --fee-mode maker \
  --open-offset-bps 10 \
  --close-offset-bps 10
```

Shows:

- Safe entry score (if conditions are evaluated)
- Suggested maker limit prices
- Estimated fill probabilities
- Expected fees and funding PnL
- Net expected PnL

#### Accept Trade

```bash
python -m farmcalc accept BTC \
  --side LONG \
  --margin 100 \
  --leverage 10 \
  --open-offset-bps 10
```

Records the trade in state with locked-in prices.

#### Close Trade

```bash
# Auto-fetch close price
python -m farmcalc close <trade_id>

# Manual close price
python -m farmcalc close <trade_id> --close-price 45000.0

# Override actual fee mode
python -m farmcalc close <trade_id> --actual-close-fee-mode maker
```

Calculates realized PnL and updates statistics.

#### Fill Feedback

```bash
# Record that open order was filled
python -m farmcalc fill-feedback <trade_id> --open filled

# Record that open was missed, close was filled
python -m farmcalc fill-feedback <trade_id> --open missed --close filled
```

Improves fill probability estimation for future trades.

#### Check Status

```bash
python -m farmcalc status
```

Shows:

- Current plan settings
- Progress toward volume target
- Total fees paid
- Total funding PnL
- Active trades
- Estimated trades needed

#### Watch Mode

```bash
python -m farmcalc watch \
  --interval 5 \
  --top 25 \
  --side either \
  --cooldown 300
```

Runs foreground polling and sends Telegram alerts when safe entry windows are detected.

### Advanced Options

#### Custom Fee Rates

```bash
python -m farmcalc propose BTC \
  --taker-fee 0.0005 \
  --maker-fee 0.0002
```

#### Funding Kind

```bash
# Assume API funding is hourly (default)
python -m farmcalc propose BTC --funding-kind hourly

# Assume API funding is 8-hour (divides by 8)
python -m farmcalc propose BTC --funding-kind 8h
```

#### Fill Probability Override

```bash
# Manual fill probability (overrides estimation)
python -m farmcalc propose BTC --fill-prob 0.9
```

## API Usage

### Start Server

```bash
# Development (with auto-reload)
uvicorn farmcalc.api:app --host 127.0.0.1 --port 8000 --reload

# Production
uvicorn farmcalc.api:app --host 0.0.0.0 --port 8000
```

### API Endpoints

#### Health Check

```bash
curl http://localhost:8000/health
```

Returns:

```json
{
  "status": "healthy",
  "timestamp": "2024-01-01T00:00:00Z",
  "version": "1.0.0"
}
```

#### Get Assets

```bash
curl "http://localhost:8000/assets?sort_by=funding&limit=20"
```

#### Get Quote

```bash
curl http://localhost:8000/quote/BTC
```

#### Propose Trade

```bash
curl -X POST "http://localhost:8000/propose" \
  -H "Content-Type: application/json" \
  -d '{
    "coin": "BTC",
    "side": "LONG",
    "margin": 100,
    "leverage": 10,
    "hold_min": 60,
    "fee_mode": "maker"
  }'
```

#### Watch Control

```bash
# Start watcher
curl -X POST http://localhost:8000/watch/start

# Check status
curl http://localhost:8000/watch/status

# Update config
curl -X POST http://localhost:8000/watch/config \
  -H "Content-Type: application/json" \
  -d '{
    "poll_interval_sec": 10,
    "top_n": 30,
    "side": "long"
  }'

# Get last snapshot
curl http://localhost:8000/watch/last

# Stop watcher
curl -X POST http://localhost:8000/watch/stop
```

### API Documentation

Interactive API docs available at:

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## Telegram Setup

### Create Bot

1. Open Telegram and search for `@BotFather`
2. Send `/newbot` and follow instructions
3. Save the bot token (e.g., `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`)

### Get Chat ID

#### For Personal Chat

1. Start a chat with your bot
2. Send any message
3. Visit: `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
4. Find `"chat":{"id":123456789}` in the response

#### For Group Chat

1. Add bot to group
2. Send a message in the group
3. Visit the same URL above
4. Find the group chat ID (usually negative number)

### Configure

```bash
export TELEGRAM_BOT_TOKEN="your_token_here"
export TELEGRAM_CHAT_ID="your_chat_id_here"
```

### Example Alert

```
🔔 Safe Entry: BTC | LONG | Score: 86

Reasons: spread ok, oracle ok, funding ok

Metrics Summary:
Spread: 2.5 bps
Oracle Dev: 3.2 bps
Funding (1h): 0.000015

Suggested Limits:
Open: $45000.00 (fill prob: 85%)
Close: $45100.00 (fill prob: 82%)

Prices: Bid $44999.50 | Ask $45000.50 | Mid $45000.00

Timestamp: 2024-01-01 12:00:00 UTC

⚠️ Paper-only alerts. No trading executed.
```

## Configuration Reference

### WatchConfig Parameters

| Parameter           | Default  | Description                                |
| ------------------- | -------- | ------------------------------------------ |
| `poll_interval_sec` | 5.0      | Polling interval (minimum 2s)              |
| `top_n`             | 25       | Number of top coins to monitor             |
| `side`              | "either" | Side preference: "long", "short", "either" |
| `open_offset_bps`   | 0.0      | Open limit price offset in basis points    |
| `close_offset_bps`  | 0.0      | Close limit price offset in basis points   |
| `funding_kind`      | "hourly" | "hourly" or "8h"                           |
| `cooldown_sec`      | 300.0    | Cooldown between alerts per coin+side      |
| `score_threshold`   | 80.0     | Minimum score to trigger alert             |
| `debounce_count`    | 3        | Consecutive passes needed to arm alert     |
| `hysteresis`        | 5.0      | Hysteresis band for clearing armed state   |

### Score Thresholds

| Threshold         | Default  | Description                              |
| ----------------- | -------- | ---------------------------------------- |
| `spread_bad_bps`  | 10.0     | Spread at which score = 0                |
| `spread_good_bps` | 1.0      | Spread at which score = 100              |
| `mark_bad_bps`    | 20.0     | Mark deviation at which score = 0        |
| `mark_good_bps`   | 2.0      | Mark deviation at which score = 100      |
| `oracle_bad_bps`  | 30.0     | Oracle deviation at which score = 0      |
| `oracle_good_bps` | 5.0      | Oracle deviation at which score = 100    |
| `funding_bad`     | 0.0001   | Funding rate at which score = 0 (hourly) |
| `funding_good`    | 0.00001  | Funding rate at which score = 100        |
| `liq_bad`         | 100000   | 24h volume at which score = 0            |
| `liq_good`        | 10000000 | 24h volume at which score = 100          |
| `depth_bad`       | 1000     | Order book depth at which score = 0      |
| `depth_good`      | 10000    | Order book depth at which score = 100    |

## Architecture

### Module Structure

```
farmcalc/
  models/          # Domain models (Plan, Trade, State, WatchConfig)
  clients/         # API clients (Hyperliquid, Telegram, CoinGecko)
  services/        # Business logic
    calc.py        # Pure math (fees, funding, volume)
    pricing.py     # Limit price calculations, L2 parsing
    scoring.py     # Score-based safe entry evaluation
    fill_model.py  # Adaptive fill probability estimation
    watcher.py     # Background polling and alerting
    sentiment.py   # CoinGecko sentiment mapping
  storage/         # State persistence and caching
  ui/              # CLI output formatting
  main.py          # CLI entry point
  api.py           # FastAPI entry point
  settings.py      # Configuration management
  logging_config.py # Structured logging setup
```

### Data Flow

1. **CLI/API** → Calls services with injected clients
2. **Services** → Pure functions + stateful services (watcher, fill model)
3. **Clients** → Isolated network calls to external APIs
4. **Storage** → JSON persistence with versioning
5. **UI** → Rich formatting for CLI only

### Adding New Features

#### Add a New Scoring Metric

1. Add calculation function to `services/scoring.py`
2. Add component to `ScoreComponents` dataclass
3. Add weight to `ScoreWeights`
4. Update `calculate_component_scores()`
5. Add tests in `tests/test_scoring.py`

#### Add a New Sentiment Provider

1. Create client in `clients/` (e.g., `clients/sentiment_provider.py`)
2. Update `services/sentiment.py` to use new client
3. Add configuration to `settings.py`
4. Wire into watcher if needed

## Testing

### Run Tests

```bash
# All tests
pytest tests/ -v

# Specific test file
pytest tests/test_calc.py -v

# With coverage
pytest tests/ --cov=farmcalc --cov-report=html
```

### Test Coverage

Tests cover:

- ✅ Pure calculation functions (fees, funding, volume)
- ✅ Pricing functions (limit prices, L2 parsing)
- ✅ Scoring functions (component scores, total score)
- ✅ Edge cases and monotonicity

### Writing Tests

Example test structure:

```python
def test_calculate_fees():
    """Test fee calculation."""
    fees, details = calculate_fees(1000.0, 0.00045, 0.00015, "maker")
    assert fees > 0
    assert details["open_fee_mode"] == "maker"
```

## Deployment

### Non-Docker Deployment (Recommended)

FarmCalc is designed to run without Docker, using systemd for process management.

#### 1. Install Dependencies

```bash
# Install Python dependencies
pip install -r requirements.txt

# Or install in editable mode
pip install -e .
```

#### 2. Configure Environment Variables

Create `/etc/farmcalc.env`:

```bash
TELEGRAM_BOT_TOKEN=your_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
TELEGRAM_OWNER_ID=123456789
TELEGRAM_WEBHOOK_URL=https://your-domain.com/telegram/webhook
TELEGRAM_SECRET_TOKEN=your-secret-token
LOG_FORMAT=json
LOG_LEVEL=INFO
```

#### 3. Set Up Webhook (Production)

```bash
# Set webhook URL
python -m farmcalc telegram set-webhook \
  --url https://your-domain.com/telegram/webhook \
  --secret-token your-secret-token

# Verify webhook status
python -m farmcalc telegram status
```

#### 4. Create Systemd Service

Create `/etc/systemd/system/farmcalc.service`:

```ini
[Unit]
Description=FarmCalc API Server
After=network.target

[Service]
Type=simple
User=farmcalc
Group=farmcalc
WorkingDirectory=/opt/farmcalc
EnvironmentFile=/etc/farmcalc.env
ExecStart=/usr/local/bin/uvicorn farmcalc.api:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable farmcalc
sudo systemctl start farmcalc
sudo systemctl status farmcalc
```

#### 5. Start Watcher

Via API:

```bash
curl -X POST http://localhost:8000/watch/start
```

Or via CLI (foreground):

```bash
python -m farmcalc watch --interval 5 --top 25
```

### Docker Deployment (Optional)

#### Build Image

```bash
docker build -t farmcalc:latest .
```

#### Run Container

```bash
docker run -d \
  --name farmcalc \
  -p 8000:8000 \
  --env-file /etc/farmcalc.env \
  -v $(pwd)/data:/app/data \
  farmcalc:latest
```

#### Docker Compose

```bash
# Start services
docker-compose up -d

# View logs
docker-compose logs -f

# Stop services
docker-compose down
```

### Production Considerations

#### Webhook vs Polling

**Webhook Mode (Recommended for Production):**

- Requires public HTTPS endpoint
- More efficient (Telegram pushes updates)
- Set webhook: `python -m farmcalc telegram set-webhook --url https://your-domain.com/telegram/webhook`
- Verify secret token header for security

**Polling Mode (Development/Testing):**

- No public endpoint required
- Use: `python -m farmcalc telegram poll`
- **Do NOT run webhook and polling simultaneously**

#### Rate Limiting

- Hyperliquid API: Respect rate limits (meta refresh every 60s, L2 staggered)
- Telegram API: Max 10 alerts/hour global limit (configurable)
- Per-coin cooldown: 5 minutes default (configurable)

#### Polling Intervals

- **Meta data**: Refresh every 60 seconds (market data, funding rates)
- **L2 books**: Round-robin, process 1/3 of coins per tick
- **Minimum interval**: 2 seconds floor (prevents API overload)

#### Observability

- **Structured logging**: Set `LOG_FORMAT=json` for production
- **Health checks**: `/health` endpoint for monitoring
- **State persistence**: JSON files survive restarts
- **Telegram status**: `GET /telegram/status` for webhook info

#### Resource Usage

- **Memory**: ~50-100MB typical
- **CPU**: Low (mostly I/O bound)
- **Network**: Moderate (polling every 5-60s)

#### Security

- **Owner-only controls**: Only the user in `TELEGRAM_OWNER_ID` can accept/reject/pause
- **Webhook secret token**: Optional but recommended for production
- **Environment variables**: Never commit secrets to version control

### Makefile Commands

```bash
make install      # Install dependencies
make test         # Run tests
make run-cli      # Run CLI
make run-api      # Run FastAPI server
make run-watch    # Run watch mode
make docker-build # Build Docker image
make docker-run   # Run with docker-compose
make clean        # Clean cache files
```

## Troubleshooting

### Common Issues

#### "Coin not found"

- Check coin symbol (case-sensitive, e.g., "BTC" not "btc")
- Verify Hyperliquid API is accessible
- Check network connectivity

#### "Telegram alerts not sending"

- Verify `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set
- Check bot token is valid
- Verify chat ID is correct (group IDs are negative)
- Test with: `curl https://api.telegram.org/bot<TOKEN>/getMe`
- Use `/whoami` command to verify your user ID matches `TELEGRAM_OWNER_ID`

#### "Webhook not receiving updates"

- Verify webhook URL is accessible (HTTPS required)
- Check webhook status: `python -m farmcalc telegram status`
- Verify secret token matches if configured
- Check server logs for webhook requests
- Test webhook: `curl -X POST https://your-domain.com/telegram/webhook -d '{"test": true}'`

#### "Wrong chat_id"

- Use `/whoami` to see current chat ID
- Update `TELEGRAM_CHAT_ID` environment variable
- Restart the service

#### "Bot privacy mode"

- In groups, bots with privacy mode enabled only receive messages that:
  - Start with `/` (commands)
  - Mention the bot
  - Reply to bot messages
- Inline keyboard callbacks work regardless of privacy mode
- For full message access, disable privacy mode in @BotFather

#### "Rate limit 429"

- Telegram API rate limits: ~30 messages/second
- FarmCalc has built-in spam guard (default 15s between proposals)
- If hitting limits, increase `TELEGRAM_SPAM_GUARD_SEC`
- Check queue metrics: `GET /telegram/metrics`

#### "Watcher not starting"

- Check logs for errors
- Verify state file permissions
- Ensure poll interval >= 2 seconds
- Check if watcher is paused: `/status` command

#### "Score always 0"

- Check if L2 book data is available
- Verify thresholds are reasonable
- Check if coin has sufficient liquidity

#### "Unauthorized" errors

- Verify `TELEGRAM_OWNER_ID` matches your user ID
- Use `/whoami` to check your user ID
- If using `TELEGRAM_ALLOWED_CHAT_ID`, verify chat ID matches

### Debug Mode

```bash
# Enable debug logging
export LOG_LEVEL=DEBUG
python -m farmcalc watch --interval 10
```

### State File Issues

If state file is corrupted:

```bash
# Backup and reset
mv ~/.farmcalc_state.json ~/.farmcalc_state.json.bak
python -m farmcalc init  # Creates new state
```

### Queue Metrics

Check Telegram queue health:

```bash
curl http://localhost:8000/telegram/metrics
```

Returns:

```json
{
  "updates_received": 100,
  "updates_processed": 99,
  "processing_errors": 1,
  "queue_drops": 0,
  "queue_depth": 0
}
```

## License

MIT License - See LICENSE file for details.

## Contributing

Contributions welcome! Please:

1. Follow existing code style
2. Add tests for new features
3. Update documentation
4. Keep paper-only behavior (no trading)

## Support

For issues and questions:

- Check this README first
- Review logs with `LOG_LEVEL=DEBUG`
- Check API health: `curl http://localhost:8000/health`

---

**Remember**: This tool is for informational purposes only. Always do your own research and never risk more than you can afford to lose. High leverage trading can result in total loss of capital.
# fomo-calc-app
