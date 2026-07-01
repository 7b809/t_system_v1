from selenium.webdriver.common.by import By
from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
)

import threading
import time


class SessionMonitor:

    def __init__(self, driver, interval=2):
        self.driver = driver
        self.interval = interval
        self.running = False
        self.thread = None

    def start(self):
        if self.running:
            return

        self.running = True

        self.thread = threading.Thread(
            target=self._run,
            daemon=True,
        )

        self.thread.start()

        print("[SessionMonitor] Started.")

    def stop(self):
        self.running = False

    def _run(self):

        while self.running:

            try:

                buttons = self.driver.find_elements(
                    By.XPATH, "//button[.//span[text()='Connect']]"
                )

                if buttons:

                    print("[SessionMonitor] Session disconnected detected.")

                    buttons[0].click()

                    print("[SessionMonitor] Connect button clicked.")

                    time.sleep(5)

            except (
                NoSuchElementException,
                StaleElementReferenceException,
            ):
                pass

            except Exception as ex:
                print(
                    "[SessionMonitor] Error:",
                    ex,
                )

            time.sleep(self.interval)
