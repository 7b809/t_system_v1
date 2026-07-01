import time
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import NoSuchElementException, WebDriverException


class ChartTester:
    def __init__(self, driver):
        self.driver = driver

    def get_charts(self):
        """Finds all chart container elements on the screen."""
        return self.driver.find_elements(By.CLASS_NAME, "chart-container")

    def get_active_chart(self):
        """Finds the currently active chart container."""
        try:
            return self.driver.find_element(By.CSS_SELECTOR, ".chart-container.active")
        except NoSuchElementException:
            return None

    def get_symbol(self, chart_element=None):
        """Extracts the ticker symbol text from a specific or active chart container."""
        target = chart_element if chart_element else self.get_active_chart()
        if not target:
            return "Unknown"
        try:
            symbol_btn = target.find_element(
                By.CSS_SELECTOR, 'button[aria-label="Change symbol"]'
            )
            return symbol_btn.text.strip()
        except NoSuchElementException:
            return "Unknown"

    def activate_chart(self, index: int) -> bool:
        """
        Activates a chart panel by its index using native ActionChains.
        Mimics pointer down, up, and focus changes over canvas frames.
        """
        all_charts = self.get_charts()
        if index >= len(all_charts):
            raise IndexError(
                f"Chart index {index} out of range. Found {len(all_charts)} charts."
            )

        target_chart = all_charts[index]

        try:
            pane = target_chart.find_element(By.CSS_SELECTOR, '[data-qa-id="pane"]')
        except NoSuchElementException:
            try:
                pane = target_chart.find_element(By.CLASS_NAME, "chart-gui-wrapper")
            except NoSuchElementException:
                pane = target_chart

        # Sequence hardware-level interaction signals across complex canvas bounds
        actions = ActionChains(self.driver)
        actions.move_to_element(pane).click_and_hold().release().perform()

        # Monitor loop ensuring the UI framework shifts focus status
        for _ in range(20):
            if self.get_active_chart() == target_chart:
                return True
            time.sleep(0.1)

        raise WebDriverException(f"Failed to activate chart index: {index}")

    def open_change_symbol(self):
        """Clicks the header toolbar symbol search element."""
        try:
            btn = self.driver.find_element(By.ID, "header-toolbar-symbol-search")
            btn.click()
            time.sleep(0.6)  # Layout overlay animation rendering buffer
        except NoSuchElementException:
            raise NoSuchElementException(
                "Change Symbol toolbar button element not found."
            )

    def click_strike(self, strike: str, side: str) -> bool:
        """
        Locates the option chain element cell, moves it into view,
        and executes an explicit selection event chain.
        """
        selector = f'td[data-row-id="{strike}"][data-cell-part="{side.lower()}"]'

        for _ in range(20):
            try:
                td_cell = self.driver.find_element(By.CSS_SELECTOR, selector)
                if td_cell.is_displayed():
                    # Native scrolling emulation to align element targets
                    actions = ActionChains(self.driver)
                    actions.move_to_element(td_cell).perform()
                    time.sleep(0.1)

                    td_cell.click()
                    return True
            except NoSuchElementException:
                pass
            time.sleep(0.2)

        raise NoSuchElementException(
            f"Strike target option chain row cell not found: {selector}"
        )

    def wait_for_symbol_change(self, old_symbol: str) -> str:
        """Monitors DOM tracking until a new symbol name is detected."""
        for _ in range(40):
            current_symbol = self.get_symbol()
            if current_symbol != old_symbol and current_symbol != "Unknown":
                return current_symbol
            time.sleep(0.25)
        return self.get_symbol()

    def change_strike_logic(self, chart_index: int, strike: str, side: str) -> dict:
        """Executes the complete action sequence step-by-step."""
        result = {
            "success": False,
            "chartIndex": chart_index,
            "strike": strike,
            "side": side,
            "oldSymbol": "",
            "newSymbol": "",
            "changed": False,
            "error": None,
        }

        try:
            # Step 1: Select and activate target chart window panel
            self.activate_chart(chart_index)
            result["oldSymbol"] = self.get_symbol()

            # Step 2: Open symbol modal dialog window
            self.open_change_symbol()

            # Step 3: Scroll and select target option string parameters
            self.click_strike(strike, side)

            # Step 4: Verify element updates matching transaction changes
            result["newSymbol"] = self.wait_for_symbol_change(result["oldSymbol"])
            result["changed"] = result["oldSymbol"] != result["newSymbol"]
            result["success"] = result["changed"]

            return result

        except Exception as e:
            result["error"] = str(e)
            return result
