# UPSTOX EMA Crossover Engine Dashboard

A real-time UPSTOX live market monitoring system that subscribes to selected option instruments, builds 1-minute candles from live ticks, calculates EMA crossover signals, stores state in MongoDB, and displays live updates on a FastAPI dashboard.

The application is mainly designed for monitoring NIFTY option strikes and detecting EMA 9 / EMA 21 bullish and bearish crossovers.

================================================================================
PROJECT PURPOSE
================================================================================

This project automates the full market monitoring workflow:

1. Start a FastAPI dashboard server.
2. Connect to MongoDB.
3. Load subscribed option strike instruments from MongoDB.
4. Build runtime EMA state for each instrument.
5. Recover missing intraday candles if the app starts during market hours.
6. Load UPSTOX access token only when required for live feed subscription.
7. Start UPSTOX live WebSocket feed.
8. Receive live LTP ticks.
9. Convert ticks into 1-minute OHLCV candles.
10. Calculate EMA 9 and EMA 21.
11. Detect bullish and bearish crossovers.
12. Save candles, EMA state, and crossover events to MongoDB.
13. Update live dashboard state.
14. Push live LTP updates to frontend clients through WebSocket.
15. Send optional Telegram alerts.
16. Stop feed, flush pending candles, and clean runtime state after market close.

Important token behavior:

    UPSTOX access token is required only for live market feed subscription.

    UPSTOX access token is not required for:
    - MongoDB fetch/save
    - Loading strike documents
    - Loading EMA documents
    - Intraday candle recovery using HistoryApi()

================================================================================
HIGH-LEVEL ARCHITECTURE
================================================================================

FastAPI Application
    |
    |-- Dashboard API Routes
    |-- Frontend WebSocket Route
    |
Application Bootstrap
    |
MarketScheduler
    |
    |-- PreloadService
    |-- IntradayRecoveryService
    |-- UpstoxStreamService
    |-- CandleBuilder
    |-- CrossoverEngine
    |
MongoDB
    |
DashboardState
    |
Frontend Dashboard

================================================================================
MAIN FEATURES
================================================================================

- FastAPI based dashboard.
- UPSTOX live market WebSocket integration.
- MongoDB-backed token and market data storage.
- Runtime preload of all configured instruments.
- Intraday recovery after restart during market hours.
- Intraday candle recovery without Upstox access token.
- Live LTP processing.
- 1-minute candle creation.
- EMA 9 / EMA 21 calculation.
- Bullish and bearish crossover detection.
- Live browser WebSocket updates.
- Dashboard API snapshot.
- Health check API.
- Telegram notification support.
- Graceful shutdown and market close cleanup.
- Runtime dashboard state with bullish/bearish summary.

================================================================================
TOKEN USAGE DESIGN
================================================================================

The application separates token usage clearly.

TOKEN REQUIRED
--------------

UPSTOX access token is required for:

    Live market WebSocket feed subscription

This is handled by:

    services/upstox_stream.py

The live feed uses:

    upstox_client.MarketDataStreamerV3

with authenticated configuration.

TOKEN NOT REQUIRED
------------------

UPSTOX access token is not required for:

    MongoDB read/write
    Intraday candle recovery
    Runtime preload
    Strike loading
    EMA state loading
    Dashboard APIs
    Frontend WebSocket clients

Intraday candle recovery uses:

    upstox_client.HistoryApi()

without passing access token.

================================================================================
TRADING LOGIC
================================================================================

The application uses EMA 9 and EMA 21.

For each completed 1-minute candle:

    EMA Short = EMA 9
    EMA Long  = EMA 21

Relation is calculated as:

    EMA9 > EMA21 => ABOVE
    EMA9 < EMA21 => BELOW

Crossover detection:

    Previous relation BELOW + Current relation ABOVE = BULLISH
    Previous relation ABOVE + Current relation BELOW = BEARISH

When a crossover is detected, the event is saved into MongoDB and shown on the dashboard.

================================================================================
PROJECT FOLDER STRUCTURE
================================================================================

t_system_v1-point-5/
|
|-- main.py
|-- Procfile
|-- requirements.txt
|-- run.bat
|
|-- api/
|   |-- dashboard_api.py
|
|-- config/
|   |-- settings.py
|
|-- core/
|   |-- logger.py
|   |-- logger_new.py
|
|-- db/
|   |-- mongo_app.py
|   |-- repositories.py
|
|-- indicators/
|   |-- ema.py
|
|-- models/
|   |-- strike_state.py
|
|-- services/
|   |-- candle_builder.py
|   |-- crossover_engine.py
|   |-- dashboard_state.py
|   |-- intraday_recovery_service.py
|   |-- market_scheduler.py
|   |-- market_status_service.py
|   |-- preload_service.py
|   |-- telegram_service.py
|   |-- upstox_stream.py
|   |-- websocket_manager.py
|
|-- static/
|   |-- css/
|   |   |-- style.css
|   |-- js/
|       |-- script.js
|
|-- templates/
    |-- index.html

================================================================================
IMPORTANT MODULES
================================================================================

main.py
-------
Application entry point.

Responsibilities:
- Creates FastAPI app.
- Mounts static files.
- Registers dashboard API routes.
- Initializes Telegram notifier.
- Initializes market scheduler.
- Connects MongoDB.
- Starts scheduler in a background thread.
- Starts Uvicorn server.
- Handles graceful application shutdown.

services/market_scheduler.py
----------------------------
Controls daily market flow.

Responsibilities:
- Detect new trading day.
- Check whether market is open today.
- Run preload at configured preload time.
- Start market feed at configured market open time.
- Stop market feed at configured market close time.
- Flush pending candles.
- Clear runtime state after market close.
- Try loading Upstox token during preload.
- Require Upstox token only when starting live feed.

Important behavior:

    Preload does not fail only because Upstox token is missing.
    Live feed start fails if token is missing.

services/preload_service.py
---------------------------
Loads all required instrument state before market starts.

Responsibilities:
- Load all strike documents from MongoDB.
- Ensure today's daily bucket exists.
- Load latest EMA state from MongoDB.
- Build runtime StrikeState objects.
- Trigger intraday recovery if the app starts during market hours.

Runtime state is stored in:

    PreloadService.RUNTIME_STATE

Important behavior:

    PreloadService does not require Upstox token for runtime initialization.
    Intraday recovery does not require Upstox token.

services/intraday_recovery_service.py
-------------------------------------
Used when the application starts or restarts during active market hours.

Responsibilities:
- Fetch today's intraday candles from UPSTOX HistoryApi.
- Compare with last processed candle timestamp.
- Replay only missing candles.
- Recalculate EMA values.
- Detect missed crossovers.
- Save recovered EMA state and crossovers to MongoDB.

Important behavior:

    api = upstox_client.HistoryApi()

No access token is passed for intraday candle recovery.

services/upstox_stream.py
-------------------------
Handles UPSTOX market WebSocket feed.

Responsibilities:
- Validate Upstox access token.
- Create UPSTOX MarketDataStreamerV3.
- Subscribe all runtime instruments.
- Receive live feed messages.
- Extract LTP, timestamp, and volume.
- Update dashboard state.
- Broadcast LTP to frontend WebSocket clients.
- Send ticks to CandleBuilder.
- Send completed candles to CrossoverEngine.
- Handle reconnect and shutdown.

Important behavior:

    This is the only core service where Upstox access token is mandatory.

services/candle_builder.py
--------------------------
Converts live ticks into 1-minute OHLCV candles.

Each candle contains:

{
  "timestamp": "2026-07-20T09:15:00+05:30",
  "open": 100.0,
  "high": 101.0,
  "low": 99.0,
  "close": 100.5,
  "volume": 1200
}

When the minute changes, the current candle is completed and passed to the crossover engine.

services/crossover_engine.py
----------------------------
Processes completed candles.

Responsibilities:
- Load current runtime EMA state.
- Calculate live EMA 9 and EMA 21.
- Detect crossover.
- Save candle to MongoDB.
- Update runtime state.
- Update MongoDB EMA status.
- Update dashboard state.
- Save crossover if detected.

indicators/ema.py
-----------------
Contains EMA calculation logic.

Responsibilities:
- Historical EMA calculation.
- Live incremental EMA calculation.
- Latest EMA state extraction.
- Crossover detection.
- Historical crossover extraction.

services/dashboard_state.py
---------------------------
Thread-safe in-memory dashboard state.

Stores:
- WebSocket connection status.
- Market status.
- Scheduler status.
- Current trading date.
- Total ticks.
- Total runtime instruments.
- Total active candles.
- Bullish count.
- Bearish count.
- NIFTY index data.
- Instrument state list.
- Latest crossover events.

The dashboard API reads from this state.

services/websocket_manager.py
-----------------------------
Manages frontend dashboard WebSocket clients.

Supports subscription by:

{
  "strike": "24500",
  "type": "PE"
}

or:

{
  "instrument_key": "NSE_FO|12345"
}

or all ticks:

{
  "send_all": true
}

db/mongo_app.py
---------------
Central MongoDB connection manager.

Responsibilities:
- Connect to MongoDB.
- Return database object.
- Return token collection.
- Return strikes collection.
- Return live EMA collection.
- Close Mongo connection.

db/repositories.py
------------------
MongoDB repository layer.

Responsibilities:
- Load UPSTOX access token.
- Load all strike documents.
- Load all instrument keys.
- Create daily buckets.
- Save candles.
- Save crossovers.
- Update live EMA state.
- Save recovered EMA state.
- Check duplicate crossovers.
- Update last processed timestamp.

Important behavior:

    MongoDB operations do not require Upstox token.
    They only require valid MongoDB connection details.

================================================================================
API ROUTES
================================================================================

The application exposes the following FastAPI routes.

--------------------------------------------------------------------------------
1. Dashboard Page
--------------------------------------------------------------------------------

GET /

Description:
Renders the main dashboard page.

Used by:
Browser users.

Example:

    http://localhost:8000/

Response:

    HTML dashboard page

This page loads frontend assets from:

    /static/css/style.css
    /static/js/script.js

--------------------------------------------------------------------------------
2. Dashboard Snapshot API
--------------------------------------------------------------------------------

GET /api/dashboard

Description:
Returns the full current dashboard state as JSON.

Used by:
Frontend JavaScript for full dashboard refresh.

Example:

    http://localhost:8000/api/dashboard

Sample response:

{
  "app": {
    "name": "UPSTOX_EMA_CROSSOVER_ENGINE",
    "version": "1.0.0",
    "timezone": "Asia/Kolkata"
  },
  "status": {
    "websocket_connected": true,
    "market_status": "OPEN",
    "scheduler_status": "MARKET_FEED_STARTED",
    "current_trading_date": "2026-07-20",
    "preloaded_today": true,
    "market_started": true,
    "market_closed_today": false,
    "last_feed_time": "2026-07-20T09:20:10+05:30",
    "last_update_time": "2026-07-20T09:20:11+05:30"
  },
  "summary": {
    "total_ticks": 1200,
    "total_runtime_instruments": 100,
    "total_active_candles": 100,
    "bullish_count": 45,
    "bearish_count": 55
  },
  "nifty_index": {
    "instrument_key": "NSE_INDEX|Nifty 50",
    "ltp": 24500.25,
    "change": 50.25,
    "change_percent": 0.21,
    "last_tick_time": "2026-07-20T09:20:10+05:30"
  },
  "instruments": [],
  "latest_crossovers": []
}

Main fields:
- app: Application details.
- status: Market, scheduler, and WebSocket status.
- summary: Runtime count summary.
- nifty_index: Optional NIFTY index display data.
- instruments: List of all monitored instruments.
- latest_crossovers: Recent crossover events.

--------------------------------------------------------------------------------
3. Health Check API
--------------------------------------------------------------------------------

GET /api/health

Description:
Lightweight health endpoint.

Useful for:
- Browser check.
- Deployment platform health check.
- Monitoring dashboard availability.
- Verifying feed and scheduler status.

Example:

    http://localhost:8000/api/health

Sample response:

{
  "status": "ok",
  "dashboard": "running",
  "upstox_websocket_connected": true,
  "frontend_socket_clients": 1,
  "market_status": "OPEN",
  "scheduler_status": "MARKET_FEED_STARTED",
  "total_runtime_instruments": 100,
  "total_ticks": 1500,
  "last_feed_time": "2026-07-20T09:25:00+05:30"
}

--------------------------------------------------------------------------------
4. Frontend WebSocket Client Debug API
--------------------------------------------------------------------------------

GET /api/socket/clients

Description:
Returns connected frontend WebSocket client count and their active subscriptions.

Example:

    http://localhost:8000/api/socket/clients

Sample response:

{
  "status": "ok",
  "client_count": 2,
  "subscriptions": [
    {
      "strike": null,
      "type": null,
      "instrument_key": null,
      "send_all": true
    },
    {
      "strike": "24500",
      "type": "PE",
      "instrument_key": null,
      "send_all": false
    }
  ]
}

This endpoint is useful for debugging live dashboard socket clients.

--------------------------------------------------------------------------------
5. Frontend LTP WebSocket
--------------------------------------------------------------------------------

WS /ws/ltp

Description:
WebSocket endpoint used by frontend browser clients to receive live LTP updates.

Example local URL:

    ws://localhost:8000/ws/ltp

If running over HTTPS:

    wss://your-domain.com/ws/ltp

Connection message from backend:

{
  "event": "connected",
  "message": "WebSocket connected successfully."
}

Subscribe to all ticks:

{
  "send_all": true
}

Subscribe by strike and option type:

{
  "strike": "24500",
  "type": "PE"
}

Alternative option type field:

{
  "strike": "24500",
  "option_type": "CE"
}

Subscribe by instrument key:

{
  "instrument_key": "NSE_FO|12345"
}

Subscription update response:

{
  "event": "subscription_updated",
  "strike": "24500",
  "type": "PE",
  "instrument_key": null,
  "send_all": false
}

Live LTP update message:

{
  "event": "ltp_update",
  "instrument_key": "NSE_FO|12345",
  "strike": "24500",
  "type": "PE",
  "option_type": "PE",
  "trading_symbol": "NIFTY24500PE",
  "ltp": 12.45,
  "volume": 100,
  "timestamp": "2026-07-20T09:15:00+05:30"
}

Error message for invalid JSON:

{
  "event": "error",
  "message": "Invalid JSON message."
}

Generic WebSocket error response:

{
  "event": "error",
  "message": "error details"
}

================================================================================
ENVIRONMENT VARIABLES
================================================================================

The application uses .env values loaded by python-dotenv.

Create a .env file in the root directory.

Example:

MONGO_URL=mongodb+srv://username:password@cluster.mongodb.net/
UPSTOX_DB=upstox

UPSTOX_TOKEN_COLL=tokens
UPSTOX_STRIKES_COLL=option_strikes
UPSTOX_EMA_COLL=live_ema_analysis

UPSTOX_API_VERSION=2.0

EMA_SHORT_PERIOD=9
EMA_LONG_PERIOD=21

PRELOAD_HOUR=9
PRELOAD_MINUTE=0

MARKET_START_HOUR=9
MARKET_START_MINUTE=15

MARKET_END_HOUR=15
MARKET_END_MINUTE=30

CANDLE_INTERVAL=1minute

ENABLE_INTRADAY_RECOVERY=true
RECOVERY_INTERVAL=1minute
RECOVERY_MAX_WORKERS=10

UPSTOX_FEED_MODE=ltpc

SUBSCRIBE_BATCH_SIZE=100
SUBSCRIBE_BATCH_SLEEP=0.5

DASHBOARD_HOST=0.0.0.0
DASHBOARD_PORT=8000
ENABLE_DASHBOARD=true
DASHBOARD_REFRESH_SECONDS=2

TIMEZONE=Asia/Kolkata

NIFTY_INDEX_INSTRUMENT_KEY=NSE_INDEX|Nifty 50

TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
TELE_FLAG=false

STORE_CROSSES=true
STORE_TODAY_CANDLES=true
STORE_MASTER_CANDLES=true

SCHEDULER_SLEEP_SECONDS=15
STATS_INTERVAL_SECONDS=300

LOG_LEVEL=INFO
LOG_RETENTION_DAYS=30

APP_NAME=UPSTOX_EMA_CROSSOVER_ENGINE
APP_VERSION=1.0.0

ENABLE_HEALTH_CHECK=true
HEALTH_CHECK_INTERVAL_SECONDS=60

================================================================================
MONGODB COLLECTIONS
================================================================================

Token Collection
----------------
Default collection:

    tokens

Expected document:

{
  "_id": "upstox_access_token",
  "access_token": "your_upstox_access_token"
}

Important:

    This token is required only when starting the live Upstox WebSocket feed.
    Preload and intraday candle recovery can still run without this token.

Strike Master Collection
------------------------
Default collection:

    option_strikes

Expected fields:

{
  "instrument_key": "NSE_FO|12345",
  "strike": "24500",
  "type": "PE",
  "trading_symbol": "NIFTY24500PE"
}

Live EMA Collection
-------------------
Default collection:

    live_ema_analysis

This collection stores:
- Live instrument documents.
- Daily EMA buckets.
- Today candles.
- Crossovers.
- Latest crossovers.
- Last updated timestamps.

Example structure:

{
  "instrument_key": "NSE_FO|12345",
  "strike": "24500",
  "type": "PE",
  "trading_symbol": "NIFTY24500PE",
  "daily": {
    "2026-07-20": {
      "signal": null,
      "signal_status": "NO_CROSSOVER",
      "crosses_today": [],
      "today_candles": [],
      "ema_short": 12.431,
      "ema_long": 11.921,
      "last_price": 12.45,
      "candle_timestamp": "2026-07-20T09:15:00+05:30"
    }
  },
  "latest_crosses": [],
  "latest_crosses_date": "2026-07-20",
  "last_updated_date": "2026-07-20"
}

================================================================================
INSTALLATION
================================================================================

1. Go to project directory:

    cd t_system_v1-point-5

2. Create virtual environment:

    python -m venv venv

3. Activate virtual environment on Windows:

    venv\Scripts\activate

4. Activate virtual environment on Linux/macOS:

    source venv/bin/activate

5. Install dependencies:

    pip install -r requirements.txt

6. Configure .env in the root folder.

7. Run the application:

    python main.py

Or run using uvicorn directly:

    uvicorn main:app --host 0.0.0.0 --port 8000

Or on Windows:

    run.bat

================================================================================
DEPLOYMENT
================================================================================

The project contains a Procfile:

    web: python main.py --host 0.0.0.0 --port $PORT

The application internally reads PORT from environment variable.

If PORT is not available, it uses 8000.

Recommended Procfile options:

Option 1:

    web: python main.py

Option 2:

    web: uvicorn main:app --host 0.0.0.0 --port $PORT

================================================================================
DASHBOARD USAGE
================================================================================

Open browser:

    http://localhost:8000/

The dashboard shows:
- Market status.
- UPSTOX WebSocket status.
- NIFTY index value, if configured.
- Total loaded instruments.
- Bullish instruments count.
- Bearish instruments count.
- Active candle count.
- Last feed time.
- Last update time.
- Instrument table.
- EMA 9.
- EMA 21.
- Relation.
- Signal status.
- Latest crossovers.

================================================================================
FRONTEND REFRESH BEHAVIOR
================================================================================

The dashboard frontend uses two update mechanisms.

1. Full Snapshot Refresh
------------------------
Every 30 seconds:

    GET /api/dashboard

This refreshes:
- Market status.
- Scheduler status.
- EMA values.
- Crossovers.
- Summary cards.

2. Live LTP WebSocket
---------------------
Near real-time updates through:

    /ws/ltp

This updates:
- LTP.
- Volume.
- Last tick time.
- Total ticks.

================================================================================
APPLICATION LIFECYCLE
================================================================================

Startup Flow
------------

Application starts
    |
FastAPI startup event
    |
Application initializes
    |
MongoDB connects
    |
Scheduler starts in background thread
    |
Scheduler waits for trading day/preload time

Preload Flow
------------

Preload time reached
    |
Try loading UPSTOX token for later live feed use
    |
Load all strike documents from MongoDB
    |
Create today's daily buckets
    |
Load latest EMA state from MongoDB
    |
Run intraday recovery if market is already open
    |
Build runtime state
    |
Update dashboard

Important:

    Preload and intraday recovery can continue without UPSTOX token.
    Token is mandatory only when starting live feed.

Market Open Flow
----------------

Market open time reached
    |
Ensure UPSTOX token is available
    |
Create UPSTOX stream
    |
Connect WebSocket
    |
Subscribe all instruments
    |
Receive live ticks
    |
Build candles
    |
Process EMA and crossovers

Market Close Flow
-----------------

Market close time reached
    |
Flush active candles
    |
Process final candles
    |
Unsubscribe instruments
    |
Disconnect UPSTOX WebSocket
    |
Clear runtime state
    |
Clear active candles
    |
Update dashboard as closed

================================================================================
LOGS
================================================================================

Logs are stored in:

    logs/

Each module writes to its own log file.

Examples:

    logs/main.log
    logs/market_scheduler.log
    logs/upstox_stream.log
    logs/crossover_engine.log
    logs/candle_builder.log
    logs/repositories.log

Log files rotate daily using TimedRotatingFileHandler.

================================================================================
TELEGRAM NOTIFICATIONS
================================================================================

Telegram service supports notifications for:
- Application startup.
- Market skipped.
- Preload complete.
- Intraday recovery complete.
- Market stopped.
- UPSTOX token expiry.
- Critical system errors.

To enable Telegram, configure:

TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
TELE_FLAG=true

Important note:
In the current telegram_service.py, self.tele_flag is hardcoded as False:

    self.tele_flag = False

So even if TELE_FLAG=true is set in .env, messages will not be sent unless this is changed to read from settings or environment variable.

Recommended correction:

    self.tele_flag = os.getenv("TELE_FLAG", "true").strip().lower() == "true"

================================================================================
IMPORTANT NOTES
================================================================================

1. Access token usage
---------------------
The app expects this token document for live feed startup:

{
  "_id": "upstox_access_token",
  "access_token": "valid_token_here"
}

If token is missing or expired:

    Preload can still run.
    Intraday recovery can still run.
    Live market WebSocket feed cannot start.

2. Strike documents must contain instrument key
-----------------------------------------------
Each strike document should contain:

{
  "instrument_key": "NSE_FO|12345"
}

Optional but useful fields:

{
  "strike": "24500",
  "type": "PE",
  "trading_symbol": "NIFTY24500PE"
}

3. Intraday recovery runs only during market hours
--------------------------------------------------
Recovery condition:

    ENABLE_INTRADAY_RECOVERY=true
    and
    MARKET_START_TIME <= current_time < MARKET_END_TIME

4. Intraday recovery does not require token
-------------------------------------------
Intraday recovery uses:

    upstox_client.HistoryApi()

without access token.

5. WebSocket feed mode
----------------------
Default feed mode:

    UPSTOX_FEED_MODE=ltpc

The stream parser supports:
- ltpc
- fullFeed.marketFF.ltpc

6. Dashboard does not query MongoDB directly
--------------------------------------------
Dashboard reads from in-memory DashboardState.

This makes dashboard responses fast and avoids frequent MongoDB reads.

================================================================================
KNOWN IMPROVEMENT AREAS
================================================================================

1. Requirements cleanup
-----------------------
requirements.txt currently contains duplicate package names and unpinned dependencies at the bottom.

Recommended to clean it and keep only required pinned dependencies.

2. Telegram flag issue
----------------------
telegram_service.py currently disables Telegram permanently because:

    self.tele_flag = False

Recommended to read from .env.

3. Procfile arguments
---------------------
Current Procfile:

    web: python main.py --host 0.0.0.0 --port $PORT

But main.py does not parse CLI arguments. It reads host and port from Settings.

Recommended Procfile:

    web: python main.py

or:

    web: uvicorn main:app --host 0.0.0.0 --port $PORT

4. Console logging whitelist
----------------------------
Console logs are shown only for selected modules:

SHOW_LOG_FILE_NAMES = {
    "candle_builder",
    "repositories",
    "crossover_engine",
}

If you need scheduler or stream logs in console, add:

    "market_scheduler",
    "upstox_stream",
    "main"

5. Frontend JavaScript minor issue
----------------------------------
In static/js/script.js, this line has no effect:

    console.warning;

It can be removed or changed to:

    console.warn("Frontend LTP WebSocket closed.");

================================================================================
USEFUL LOCAL URLS
================================================================================

Dashboard:
    http://localhost:8000/

Dashboard JSON:
    http://localhost:8000/api/dashboard

Health Check:
    http://localhost:8000/api/health

Socket Clients:
    http://localhost:8000/api/socket/clients

Frontend WebSocket:
    ws://localhost:8000/ws/ltp

================================================================================
EXAMPLE END-TO-END FLOW
================================================================================

09:00 AM
    Preload starts.
    App tries to load access token for later live feed use.
    Strike documents are loaded from MongoDB.
    Runtime EMA state is created.
    If market is already open, intraday recovery runs without token.

09:15 AM
    Market feed starts.
    UPSTOX token is required here.
    UPSTOX WebSocket connects.
    All instruments are subscribed.

During market
    Incoming ticks update dashboard LTP.
    Ticks form 1-minute candles.
    Completed candles update EMA values.
    Crossovers are detected and saved.

03:30 PM
    Market close process starts.
    Active candles are force closed.
    WebSocket is disconnected.
    Runtime state is cleared.
    Dashboard status becomes CLOSED.

================================================================================
FINAL TOKEN RESPONSIBILITY SUMMARY
================================================================================

MongoDB fetch/save:
    No Upstox token required.

Intraday candle recovery:
    No Upstox token required.

Runtime preload:
    No Upstox token required.

Live Upstox WebSocket feed:
    Upstox token required.

================================================================================
ONE-LINE SUMMARY
================================================================================

This project is a real-time UPSTOX NIFTY options EMA crossover monitoring engine with MongoDB persistence, token-free intraday recovery, Telegram alerts, and a live FastAPI dashboard using REST APIs and WebSocket updates.
