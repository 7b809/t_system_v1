import time
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import NoSuchElementException, WebDriverException

# Import the standalone Telegram communication helper function
from telegram_notifier import send_telegram_notification


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

    def activate_chart_by_element(self, chart_element):
        """Simulates explicit focus switch using an explicit element reference."""
        if not chart_element:
            return
        try:
            pane = chart_element.find_element(By.CSS_SELECTOR, '[data-qa-id="pane"]')
        except NoSuchElementException:
            try:
                pane = chart_element.find_element(By.CLASS_NAME, "chart-gui-wrapper")
            except NoSuchElementException:
                pane = chart_element

        # Sequence low-level mouse actions to robustly mimic manual pointer focus shifts
        actions = ActionChains(self.driver)
        actions.move_to_element(pane).click_and_hold().release().perform()

    def activate_chart(self, index: int) -> bool:
        """Activates a chart panel by its index array positions."""
        all_charts = self.get_charts()
        if index >= len(all_charts):
            raise IndexError(
                f"Chart index {index} out of range. Found {len(all_charts)} charts."
            )

        target_chart = all_charts[index]
        self.activate_chart_by_element(target_chart)

        # Dynamic validation loop confirming the active layout CSS focus state toggled
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
            time.sleep(0.6)  # Essential UI window transition loading overlay delay
        except NoSuchElementException:
            raise NoSuchElementException(
                "Change Symbol toolbar button element not found."
            )

    def click_strike(self, strike: str, side: str) -> bool:
        """Locates the option chain element cell, moves it into view, and clicks it."""
        selector = f'td[data-row-id="{strike}"][data-cell-part="{side.lower()}"]'

        for _ in range(20):
            try:
                td_cell = self.driver.find_element(By.CSS_SELECTOR, selector)
                if td_cell.is_displayed():
                    # Move tracking cursor directly over target cell bounds to align and click cleanly
                    actions = ActionChains(self.driver)
                    actions.move_to_element(td_cell).perform()
                    time.sleep(0.1)
                    td_cell.click()
                    return True
            except NoSuchElementException:
                pass
            time.sleep(0.2)

        raise NoSuchElementException(f"Strike cell match not found: {selector}")

    def wait_for_symbol_change(self, old_symbol: str) -> str:
        """Monitors updates until symbol change is detected."""
        for _ in range(40):
            current_symbol = self.get_symbol()
            if current_symbol != old_symbol and current_symbol != "Unknown":
                return current_symbol
            time.sleep(0.25)
        return self.get_symbol()

    def trigger_buy_order_shortcut(self) -> bool:
        """Simulates native Shift + B interaction sequence on the focused chart layer."""
        try:
            actions = ActionChains(self.driver)
            # Presses and holds SHIFT, taps 'b', then releases SHIFT
            actions.key_down(Keys.SHIFT).send_keys("b").key_up(Keys.SHIFT).perform()
            return True
        except Exception as e:
            print(
                f"[Automation Log] ActionChains failed to strike Buy hotkeys: {str(e)}"
            )
            return False

    def change_strike_logic(
        self, chart_index: int, strike: str, side: str, buy_trade: bool = False
    ) -> dict:
        """Executes complete procedural strike conversion routing matching API constraints."""
        result = {
            "success": False,
            "chartIndex": chart_index,
            "strike": strike,
            "side": side,
            "buyTradeExecuted": False,
            "oldSymbol": "",
            "newSymbol": "",
            "changed": False,
            "error": None,
        }

        # 1. Send initial execution trigger info to Telegram
        side_tag = "CALL 🟢" if side.lower() == "call" else "PUT 🔴"
        init_message = (
            f"⚡ <b>Automation Request Received</b>\n"
            f"• Chart Index: {chart_index}\n"
            f"• Strike Targeted: {strike} ({side_tag})\n"
            f"• Trigger Buy Hotkey: {buy_trade}"
        )
        send_telegram_notification(init_message)

        try:
            # Step 1: Select and activate targeted window index pane
            self.activate_chart(chart_index)
            result["oldSymbol"] = self.get_symbol()

            # Step 2: Open structural symbol change interface
            self.open_change_symbol()

            # Step 3: Relocate option sequence target cell matrix matching the strike criteria
            self.click_strike(strike, side)

            # Step 4: Tracking confirmation framework updates loop
            result["newSymbol"] = self.wait_for_symbol_change(result["oldSymbol"])
            result["changed"] = result["oldSymbol"] != result["newSymbol"]

            # Step 5: Conditionally execute buy trade hotkey operations
            if buy_trade:
                print(
                    f"[Automation Log] Strike set to {result['newSymbol']}. Spawning buy order menu..."
                )
                result["buyTradeExecuted"] = self.trigger_buy_order_shortcut()

            result["success"] = result["changed"]

            # 2. Dispatch comprehensive run success details back to the bot channel
            success_message = (
                f"✅ <b>Strike Automation Success</b>\n"
                f"• Target Window: Chart {chart_index}\n"
                f"• Previous Asset: <code>{result['oldSymbol']}</code>\n"
                f"• Current Asset: <code>{result['newSymbol']}</code>\n"
                f"• Order Interface Triggered: {result['buyTradeExecuted']}"
            )
            send_telegram_notification(success_message)

            return result

        except Exception as e:
            result["error"] = str(e)

            # 3. Dispatch execution failure log message to Telegram if processing crashes
            failure_message = (
                f"❌ <b>Strike Automation Failure</b>\n"
                f"• Chart Index: {chart_index}\n"
                f"• Intended Strike: {strike} ({side})\n"
                f"• Failure Details: <code>{result['error']}</code>"
            )
            send_telegram_notification(failure_message)

            return result

    def run_toggle_test(self):
        """Executes the legacy sequential layout toggle test routine."""
        print("\n==========================================")
        print("          STARTING CHART TEST             ")
        print("==========================================")

        charts = self.get_charts()
        if len(charts) < 2:
            print(f"[TEST LOG] Aborted: Layout needs 2 charts. Found: {len(charts)}")
            return

        original_chart = self.get_active_chart()
        if not original_chart:
            print("[TEST LOG] Aborted: No active chart container detected.")
            return

        original_index = charts.index(original_chart)
        original_symbol = self.get_symbol(original_chart)
        print(
            f"[TEST LOG] Original Active Index : {original_index} | Symbol: {original_symbol}"
        )

        next_index = (original_index + 1) % len(charts)
        next_chart = charts[next_index]

        print(f"[TEST LOG] Simulating focus switch to Index: {next_index}...")
        self.activate_chart_by_element(next_chart)
        time.sleep(1)

        current_chart = self.get_active_chart()
        current_index = charts.index(current_chart) if current_chart in charts else -1
        print(
            f"[TEST LOG] After Toggle Index      : {current_index} | Symbol: {self.get_symbol(current_chart)}"
        )

        print(f"[TEST LOG] Returning focus back to Index: {original_index}...")
        self.activate_chart_by_element(original_chart)
        time.sleep(1)

        current_chart = self.get_active_chart()
        current_index = charts.index(current_chart) if current_chart in charts else -1
        print(
            f"[TEST LOG] Back to Original Index  : {current_index} | Symbol: {self.get_symbol(current_chart)}"
        )
        print("==========================================\n")
