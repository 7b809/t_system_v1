import uvicorn
import signal
import sys
import api_server

def catch_system_interrupt(sig, frame):
    print("\n[SYSTEM INTERRUPT] Intercepted shutdown command request...")
    # Prevents orphaned browser processes if the console window is killed unexpectedly
    if api_server.automation_driver_instance:
        try:
            print("[SYSTEM CLEANUP] Clearing active browser context blocks...")
            api_server.automation_driver_instance.quit()
        except Exception:
            pass
    print("[SYSTEM CLEANUP] Server down completely.")
    sys.exit(0)

if __name__ == "__main__":
    # Register OS signals for a clean graceful teardown sequence
    signal.signal(signal.SIGINT, catch_system_interrupt)

    print("\n==================================================================")
    print(" DYNAMIC API WEBDRIVER CONTROLLER ROUTER ENGINE ONLINE")
    print("==================================================================")
    print(" -> TARGET ENDPOINTS:")
    print("    * POST http://127.0.0.1:8000/api/start          (Spins Up Browser)")
    print("    * POST http://127.0.0.1:8000/api/change-strike  (Executes Parameters)")
    print("    * POST http://127.0.0.1:8000/api/stop           (Terminates Context)")
    print("==================================================================\n")

    # Start the API Endpoint Services programmatically via Uvicorn string reference
    uvicorn.run("api_server:app", host="127.0.0.1", port=8000, log_level="info", reload=False)