const DASHBOARD_API = "/api/dashboard";

// Slow full snapshot refresh.
// Live LTP will come through WebSocket.
const REFRESH_SECONDS = 30;

// Frontend WebSocket reconnect delay.
const SOCKET_RECONNECT_SECONDS = 3;

let latestSnapshot = null;
let ltpSocket = null;
let ltpSocketConnected = false;
let ltpSocketReconnectTimer = null;
let tableRenderTimer = null;

document.getElementById("refreshIntervalText").innerText = REFRESH_SECONDS;

function safeValue(value, fallback = "--") {
  if (value === null || value === undefined || value === "") {
    return fallback;
  }

  return value;
}

function formatCurrentISTTime12Hour() {
  const now = new Date();

  return now.toLocaleTimeString("en-IN", {
    timeZone: "Asia/Kolkata",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: true,
  });
}

function formatNumber(value, decimals = 2) {
  if (value === null || value === undefined || value === "") {
    return "--";
  }

  const numberValue = Number(value);

  if (Number.isNaN(numberValue)) {
    return "--";
  }

  return numberValue.toFixed(decimals);
}

function formatInteger(value) {
  if (value === null || value === undefined || value === "") {
    return "0";
  }

  const numberValue = Number(value);

  if (Number.isNaN(numberValue)) {
    return "0";
  }

  return numberValue.toLocaleString("en-IN");
}

function formatTime(value) {
  if (!value) {
    return "--";
  }

  try {
    const date = new Date(value);

    if (Number.isNaN(date.getTime())) {
      return value;
    }

    return date.toLocaleString("en-IN", {
      hour12: false,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch (error) {
    return value;
  }
}

function getRelationBadge(relation) {
  const value = relation || "UNKNOWN";

  if (value === "ABOVE") {
    return `<span class="relation-badge relation-above">ABOVE</span>`;
  }

  if (value === "BELOW") {
    return `<span class="relation-badge relation-below">BELOW</span>`;
  }

  return `<span class="relation-badge relation-unknown">${value}</span>`;
}

function getSignalClass(signal) {
  if (signal === "BULLISH") {
    return "signal-bullish";
  }

  if (signal === "BEARISH") {
    return "signal-bearish";
  }

  return "signal-normal";
}

function getLtpSocketUrl() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws/ltp`;
}

function updateOptionalElement(id, value) {
  const element = document.getElementById(id);

  if (element) {
    element.innerText = value;
  }
}

function setFrontendSocketStatus(statusText, isConnected) {
  /*
    Optional:
    If you add these elements in index.html, they will show frontend socket status:

    <span id="frontendSocketStatus"></span>
    <span id="frontendSocketClientStatus"></span>
  */

  updateOptionalElement("frontendSocketStatus", statusText);
  updateOptionalElement("frontendSocketClientStatus", statusText);

  const badge = document.getElementById("frontendSocketBadge");

  if (badge) {
    if (isConnected) {
      badge.className = "status-pill status-connected";
      badge.innerHTML = `<i class="bi bi-broadcast"></i> FRONTEND SOCKET CONNECTED`;
    } else {
      badge.className = "status-pill status-disconnected";
      badge.innerHTML = `<i class="bi bi-broadcast-pin"></i> FRONTEND SOCKET DISCONNECTED`;
    }
  }
}

function updateHeader(snapshot) {
  const app = snapshot.app || {};
  const status = snapshot.status || {};
  const nifty = snapshot.nifty_index || {};

  document.getElementById("appName").innerText = safeValue(
    app.name,
    "UPSTOX EMA CROSSOVER ENGINE",
  );

  const websocketBadge = document.getElementById("websocketBadge");

  if (status.websocket_connected) {
    websocketBadge.className = "status-pill status-connected";
    websocketBadge.innerHTML = `<i class="bi bi-wifi"></i> CONNECTED`;
  } else {
    websocketBadge.className = "status-pill status-disconnected";
    websocketBadge.innerHTML = `<i class="bi bi-wifi-off"></i> DISCONNECTED`;
  }

  const marketStatus = safeValue(status.market_status, "INIT");
  const marketBadge = document.getElementById("marketBadge");

  let marketClass = "market-init";
  let marketIcon = "bi-clock-history";

  if (marketStatus === "OPEN" || marketStatus === "INITIALIZED") {
    marketClass = "market-open";
    marketIcon = "bi-graph-up-arrow";
  } else if (
    marketStatus === "CLOSED" ||
    marketStatus === "STOPPED" ||
    marketStatus === "HOLIDAY"
  ) {
    marketClass = "market-closed";
    marketIcon = "bi-slash-circle";
  }

  marketBadge.className = `status-pill ${marketClass}`;
  marketBadge.innerHTML = `<i class="bi ${marketIcon}"></i> ${marketStatus}`;

  document.getElementById("tradingDate").innerText = safeValue(
    status.current_trading_date,
  );

  document.getElementById("schedulerStatus").innerText = safeValue(
    status.scheduler_status,
  );

  document.getElementById("niftyValue").innerText = formatNumber(nifty.ltp, 2);

  const change = nifty.change;
  const changePercent = nifty.change_percent;

  let changeText = "--";

  if (change !== null && change !== undefined) {
    changeText = `${formatNumber(change, 2)}`;

    if (changePercent !== null && changePercent !== undefined) {
      changeText += ` (${formatNumber(changePercent, 2)}%)`;
    }
  }

  const niftyChange = document.getElementById("niftyChange");
  niftyChange.innerText = changeText;

  if (Number(change) > 0) {
    niftyChange.className = "fw-bold text-success";
  } else if (Number(change) < 0) {
    niftyChange.className = "fw-bold text-danger";
  } else {
    niftyChange.className = "fw-bold text-white-50";
  }

  document.getElementById("niftyTime").innerText =
    `Last tick: ${formatTime(nifty.last_tick_time)}`;

  document.getElementById("niftyInstrument").innerText = safeValue(
    nifty.instrument_key,
  );
}

function updateSummary(snapshot) {
  const summary = snapshot.summary || {};
  const status = snapshot.status || {};

  document.getElementById("totalInstruments").innerText = formatInteger(
    summary.total_runtime_instruments,
  );

  document.getElementById("bullishCount").innerText = formatInteger(
    summary.bullish_count,
  );

  document.getElementById("bearishCount").innerText = formatInteger(
    summary.bearish_count,
  );

  document.getElementById("currentIstTime").innerText =
    formatCurrentISTTime12Hour();

  document.getElementById("activeCandles").innerText = formatInteger(
    summary.total_active_candles,
  );

  document.getElementById("lastFeedTime").innerText = formatTime(
    status.last_feed_time,
  );

  document.getElementById("lastUpdateTime").innerText = formatTime(
    status.last_update_time,
  );
}

function getFilteredInstruments() {
  if (!latestSnapshot) {
    return [];
  }

  const instruments = latestSnapshot.instruments || [];

  const query = document
    .getElementById("searchInput")
    .value.trim()
    .toLowerCase();

  const relationFilter = document.getElementById("relationFilter").value;

  return instruments.filter((item) => {
    const relation = item.relation || "UNKNOWN";

    if (relationFilter !== "ALL" && relation !== relationFilter) {
      return false;
    }

    if (!query) {
      return true;
    }

    const searchable = [
      item.instrument_key,
      item.trading_symbol,
      item.strike,
      item.option_type,
      item.relation,
      item.signal_status,
    ]
      .join(" ")
      .toLowerCase();

    return searchable.includes(query);
  });
}

function renderInstrumentTable() {
  const tbody = document.getElementById("instrumentTableBody");
  const instruments = getFilteredInstruments();

  if (!instruments.length) {
    tbody.innerHTML = `
      <tr>
        <td colspan="12" class="text-center py-5 text-muted">
          No instruments found for selected filter.
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = instruments
    .map((item, index) => {
      const signal = item.signal_status || "NO_CROSSOVER";
      const signalClass = getSignalClass(signal);

      return `
        <tr data-instrument-key="${safeValue(item.instrument_key, "")}">
          <td class="text-muted">${index + 1}</td>

          <td>
            <div class="fw-bold">${safeValue(item.instrument_key)}</div>
          </td>

          <td>${safeValue(item.trading_symbol)}</td>

          <td>
            <span class="fw-bold">${safeValue(item.strike)}</span>
          </td>

          <td>
            <span class="badge text-bg-light border">
              ${safeValue(item.option_type)}
            </span>
          </td>

          <td class="text-end fw-bold">
            ${formatNumber(item.ltp, 2)}
          </td>

          <td class="text-end">
            ${formatNumber(item.ema_short, 4)}
          </td>

          <td class="text-end">
            ${formatNumber(item.ema_long, 4)}
          </td>

          <td>
            ${getRelationBadge(item.relation)}
          </td>

          <td class="${signalClass}">
            ${safeValue(signal)}
          </td>

          <td>${formatTime(item.last_tick_time)}</td>

          <td>${formatTime(item.last_candle_time)}</td>
        </tr>
      `;
    })
    .join("");
}

function renderCrossovers(snapshot) {
  const list = document.getElementById("crossoverList");
  const crossovers = snapshot.latest_crossovers || [];

  if (!crossovers.length) {
    list.innerHTML = `
      <div class="text-center text-muted py-5">
        No crossover events yet.
      </div>
    `;
    return;
  }

  list.innerHTML = crossovers
    .map((item) => {
      const signal = item.signal || "UNKNOWN";
      const signalClass = getSignalClass(signal);

      return `
        <div class="crossover-item">
          <div class="d-flex justify-content-between align-items-center">
            <div class="${signalClass}">
              <i class="bi bi-lightning-charge-fill me-1"></i>
              ${signal}
            </div>

            <div class="small-muted">
              ${formatTime(item.timestamp)}
            </div>
          </div>

          <div class="fw-bold mt-2">
            ${safeValue(item.trading_symbol, item.instrument_key)}
          </div>

          <div class="small-muted">
            Strike: ${safeValue(item.strike)}
          </div>

          <div class="row mt-2 small">
            <div class="col-4">
              <span class="text-muted">Price</span>
              <div class="fw-bold">${formatNumber(item.price, 2)}</div>
            </div>

            <div class="col-4">
              <span class="text-muted">EMA9</span>
              <div class="fw-bold">${formatNumber(item.ema_short, 4)}</div>
            </div>

            <div class="col-4">
              <span class="text-muted">EMA21</span>
              <div class="fw-bold">${formatNumber(item.ema_long, 4)}</div>
            </div>
          </div>
        </div>
      `;
    })
    .join("");
}

function scheduleTableRender() {
  if (tableRenderTimer) {
    return;
  }

  tableRenderTimer = setTimeout(() => {
    renderInstrumentTable();
    tableRenderTimer = null;
  }, 250);
}

function applyLiveLtpUpdate(data) {
  if (!latestSnapshot) {
    return;
  }

  if (!latestSnapshot.status) {
    latestSnapshot.status = {};
  }

  if (!latestSnapshot.summary) {
    latestSnapshot.summary = {};
  }

  if (!Array.isArray(latestSnapshot.instruments)) {
    latestSnapshot.instruments = [];
  }

  const instrumentKey = data.instrument_key;

  if (!instrumentKey) {
    return;
  }

  let instrument = latestSnapshot.instruments.find(
    (item) => item.instrument_key === instrumentKey,
  );

  if (!instrument) {
    instrument = {
      instrument_key: instrumentKey,
      trading_symbol: data.trading_symbol || "",
      strike: data.strike || "",
      option_type: data.option_type || data.type || "",
      relation: "UNKNOWN",
      signal_status: "NO_CROSSOVER",
    };

    latestSnapshot.instruments.push(instrument);
  }

  instrument.ltp = data.ltp;
  instrument.volume = data.volume;
  instrument.last_tick_time = data.timestamp;
  instrument.last_updated = new Date().toISOString();

  if (data.trading_symbol) {
    instrument.trading_symbol = data.trading_symbol;
  }

  if (data.strike) {
    instrument.strike = data.strike;
  }

  if (data.option_type || data.type) {
    instrument.option_type = data.option_type || data.type;
  }

  latestSnapshot.status.last_feed_time = data.timestamp;
  latestSnapshot.status.last_update_time = new Date().toISOString();

  latestSnapshot.summary.total_ticks =
    Number(latestSnapshot.summary.total_ticks || 0) + 1;

  updateSummary(latestSnapshot);

  // If the tick belongs to configured NIFTY instrument, update header.
  const nifty = latestSnapshot.nifty_index || {};

  if (nifty.instrument_key && nifty.instrument_key === instrumentKey) {
    latestSnapshot.nifty_index.ltp = data.ltp;
    latestSnapshot.nifty_index.last_tick_time = data.timestamp;
    updateHeader(latestSnapshot);
  }

  scheduleTableRender();
}

function handleSocketMessage(event) {
  try {
    const data = JSON.parse(event.data);

    if (data.event === "connected") {
      console.log("Frontend socket connected:", data);
      return;
    }

    if (data.event === "subscription_updated") {
      console.log("Socket subscription updated:", data);
      return;
    }

    if (data.event === "ltp_update") {
      applyLiveLtpUpdate(data);
      return;
    }

    if (data.event === "error") {
      console.error("Socket error message:", data.message);
      return;
    }

    console.log("Socket message:", data);
  } catch (error) {
    console.error("Failed parsing socket message:", error);
  }
}

function subscribeAllLtpTicks() {
  if (!ltpSocket || ltpSocket.readyState !== WebSocket.OPEN) {
    return;
  }

  ltpSocket.send(
    JSON.stringify({
      send_all: true,
    }),
  );
}

function subscribeLtpByStrike(strike, optionType) {
  if (!ltpSocket || ltpSocket.readyState !== WebSocket.OPEN) {
    return;
  }

  ltpSocket.send(
    JSON.stringify({
      strike: String(strike || "").trim(),
      type: String(optionType || "")
        .trim()
        .toUpperCase(),
    }),
  );
}

function subscribeLtpByInstrumentKey(instrumentKey) {
  if (!ltpSocket || ltpSocket.readyState !== WebSocket.OPEN) {
    return;
  }

  ltpSocket.send(
    JSON.stringify({
      instrument_key: String(instrumentKey || "").trim(),
    }),
  );
}

function connectLtpSocket() {
  try {
    if (
      ltpSocket &&
      (ltpSocket.readyState === WebSocket.OPEN ||
        ltpSocket.readyState === WebSocket.CONNECTING)
    ) {
      return;
    }

    const socketUrl = getLtpSocketUrl();

    console.log("Connecting frontend LTP socket:", socketUrl);

    ltpSocket = new WebSocket(socketUrl);

    ltpSocket.onopen = function () {
      ltpSocketConnected = true;

      console.log("Frontend LTP WebSocket connected.");

      setFrontendSocketStatus("CONNECTED", true);

      // Receive all live LTP ticks for dashboard table.
      subscribeAllLtpTicks();
    };

    ltpSocket.onmessage = handleSocketMessage;

    ltpSocket.onerror = function (error) {
      console.error("Frontend LTP WebSocket error:", error);
      setFrontendSocketStatus("ERROR", false);
    };

    ltpSocket.onclose = function () {
      ltpSocketConnected = false;

      console.warning;
      console.log("Frontend LTP WebSocket closed.");

      setFrontendSocketStatus("DISCONNECTED", false);

      if (ltpSocketReconnectTimer) {
        clearTimeout(ltpSocketReconnectTimer);
      }

      ltpSocketReconnectTimer = setTimeout(() => {
        connectLtpSocket();
      }, SOCKET_RECONNECT_SECONDS * 1000);
    };
  } catch (error) {
    console.error("Failed connecting frontend LTP socket:", error);

    setFrontendSocketStatus("CONNECT_FAILED", false);

    if (ltpSocketReconnectTimer) {
      clearTimeout(ltpSocketReconnectTimer);
    }

    ltpSocketReconnectTimer = setTimeout(() => {
      connectLtpSocket();
    }, SOCKET_RECONNECT_SECONDS * 1000);
  }
}

async function loadDashboard() {
  try {
    const response = await fetch(DASHBOARD_API, {
      cache: "no-store",
    });

    if (!response.ok) {
      throw new Error(`Dashboard API failed: HTTP ${response.status}`);
    }

    const snapshot = await response.json();

    latestSnapshot = snapshot;

    updateHeader(snapshot);
    updateSummary(snapshot);
    renderInstrumentTable();
    renderCrossovers(snapshot);

    document.getElementById("loadingOverlay").classList.add("hidden");

    // Start frontend WebSocket after initial snapshot is ready.
    connectLtpSocket();
  } catch (error) {
    console.error(error);

    const websocketBadge = document.getElementById("websocketBadge");
    websocketBadge.className = "status-pill status-disconnected";
    websocketBadge.innerHTML = `<i class="bi bi-exclamation-triangle"></i> API ERROR`;

    document.getElementById("schedulerStatus").innerText =
      "DASHBOARD_API_ERROR";

    document.getElementById("loadingOverlay").classList.add("hidden");

    // Still try socket reconnect.
    connectLtpSocket();
  }
}

document
  .getElementById("searchInput")
  .addEventListener("input", renderInstrumentTable);

document
  .getElementById("relationFilter")
  .addEventListener("change", renderInstrumentTable);

// Initial full dashboard load.
loadDashboard();

// Slow full refresh only for status, crossovers, EMA changes, etc.
// LTP updates are live through WebSocket.
setInterval(loadDashboard, REFRESH_SECONDS * 1000);

// Local IST clock update.
setInterval(() => {
  const timeElement = document.getElementById("currentIstTime");

  if (timeElement) {
    timeElement.innerText = formatCurrentISTTime12Hour();
  }
}, 1000);
