import threading
import time
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

from config import TRADINGVIEW_URL, PROFILE_PATH
from session_monitor import SessionMonitor
from chart_tester import ChartTester

app = FastAPI(title="TradingView Automation Controller API")

# Global lifecycle variables managed by the API
automation_driver_instance = None
session_monitor_instance = None
monitor_thread = None
stop_event = threading.Event()


class StrikePayload(BaseModel):
    chart_index: int = Field(
        default=0,
        description="0 for left chart panel, 1 for right panel",
        alias="chartIndex",
    )
    strike: str = Field(..., description="Target strike value, e.g., '24050'")
    side: str = Field(..., description="Option type option: 'call' or 'put'")
    buy_trade: bool = Field(
        default=False,
        description="If true, executes Shift + B buy order hotkey actions",
        alias="buyTrade",
    )

    class Config:
        populate_by_name = True


def background_url_logger(driver):
    """Monitors live URL updates without switching tab focus."""
    previous_url = ""
    while not stop_event.is_set():
        try:
            current_url = driver.current_url
            if current_url != previous_url:
                print(f"\n[BROWSER CONTEXT] -> {current_url}")
                previous_url = current_url
            time.sleep(2)
        except Exception:
            if stop_event.is_set():
                break
            print("[Monitor] Error tracking active browser state elements.")
            break


@app.post("/api/start")
async def start_selenium():
    """
    Spins up the automated Chrome browser profile and background monitors.
    """
    global automation_driver_instance, session_monitor_instance, monitor_thread, stop_event

    if automation_driver_instance is not None:
        return {"success": False, "message": "Browser session is already running."}

    try:
        print("\n[API] Initializing Chrome Driver Session...")
        stop_event.clear()

        options = Options()
        options.add_argument("--start-maximized")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument(f"--user-data-dir={PROFILE_PATH}")
        options.add_argument("--profile-directory=Default")

        service = Service()
        driver = webdriver.Chrome(service=service, options=options)

        # Obfuscate automation fingerprint signatures
        driver.execute_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )

        print(f"[API] Directing instance to: {TRADINGVIEW_URL}")
        driver.get(TRADINGVIEW_URL)

        automation_driver_instance = driver

        # Initialize and kick-off system monitors
        session_monitor_instance = SessionMonitor(driver=driver, interval=2)
        session_monitor_instance.start()

        monitor_thread = threading.Thread(
            target=background_url_logger, args=(driver,), daemon=True
        )
        monitor_thread.start()

        return {
            "success": True,
            "message": "Browser started and initialized successfully.",
        }

    except Exception as e:
        automation_driver_instance = None
        raise HTTPException(
            status_code=500, detail=f"Failed to start Selenium: {str(e)}"
        )


@app.post("/api/stop")
async def stop_selenium():
    """
    Gracefully stops all tracking tasks and closes the Chrome instance.
    """
    global automation_driver_instance, session_monitor_instance, monitor_thread, stop_event

    if automation_driver_instance is None:
        return {
            "success": False,
            "message": "No active browser session found to terminate.",
        }

    try:
        print("\n[API] Initiating graceful teardown sequence...")
        stop_event.set()

        if session_monitor_instance:
            session_monitor_instance.stop()
            session_monitor_instance = None

        if monitor_thread:
            monitor_thread.join(timeout=2)
            monitor_thread = None

        print("[API] Closing browser tabs completely...")
        automation_driver_instance.quit()
        automation_driver_instance = None

        return {"success": True, "message": "Browser session terminated safely."}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error encountered during termination loop: {str(e)}",
        )


@app.post("/api/change-strike")
async def change_strike_endpoint(payload: StrikePayload):
    global automation_driver_instance

    if automation_driver_instance is None:
        raise HTTPException(
            status_code=503,
            detail="Selenium WebDriver instance is offline. Please hit /api/start first.",
        )

    try:
        worker = ChartTester(automation_driver_instance)
        execution_response = worker.change_strike_logic(
            chart_index=payload.chart_index,
            strike=payload.strike,
            side=payload.side,
            buy_trade=payload.buy_trade,
        )

        if not execution_response["success"] and execution_response["error"]:
            raise HTTPException(status_code=400, detail=execution_response["error"])

        return execution_response

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Internal API processing failure: {str(e)}"
        )
