window.TVAutomation = (() => {

    const sleep = ms => new Promise(r => setTimeout(r, ms));

    function activeChart() {
        return document.querySelector(".chart-container.active");
    }

    function charts() {
        return [...document.querySelectorAll(".chart-container")];
    }

    function symbol(chart = activeChart()) {
        return chart
            ?.querySelector('button[aria-label="Change symbol"]')
            ?.textContent
            ?.trim() || "";
    }

    async function activateChart(index) {

        const all = charts();

        if (index >= all.length)
            throw new Error("Chart index not found");

        const chart = all[index];

        const pane =
            chart.querySelector('[data-qa-id="pane"]') ||
            chart.querySelector(".chart-gui-wrapper") ||
            chart;

        [
            "pointerdown",
            "mousedown",
            "mouseup",
            "click"
        ].forEach(type => {

            pane.dispatchEvent(
                new MouseEvent(type, {
                    bubbles: true,
                    cancelable: true,
                    view: window
                })
            );

        });

        for (let i = 0; i < 20; i++) {

            if (activeChart() === chart)
                return true;

            await sleep(100);

        }

        throw new Error("Failed to activate chart");
    }

    async function openChangeSymbol() {

        const btn = document.querySelector(
            '#header-toolbar-symbol-search'
        );

        if (!btn)
            {throw new Error("Change Symbol button not found");}

        else{
            console.log("header toolbar found")
        btn.click();
        }

        await sleep(600);
        console.log("wait completed..")
    }

    async function clickStrike(strike, side) {

        const selector =
            `td[data-row-id="${strike}"][data-cell-part="${side}"]`;

        for (let i = 0; i < 20; i++) {

            const td = document.querySelector(selector);

            if (td) {

                td.scrollIntoView({
                    block: "center"
                });

                await sleep(100);

                td.click();

                return true;
            }

            await sleep(200);

        }

        throw new Error("Strike not found: " + selector);
    }

    async function waitForSymbolChange(oldSymbol) {

        for (let i = 0; i < 40; i++) {

            const current = symbol();

            if (current !== oldSymbol)
                return current;

            await sleep(250);

        }

        return symbol();
    }

    async function changeStrike({
        chartIndex,
        strike,
        side
    }) {

        const result = {
            success: false,
            chartIndex,
            strike,
            side,
            oldSymbol: "",
            newSymbol: "",
            changed: false,
            error: null
        };

        try {

            console.log("Activating chart...");
            await activateChart(chartIndex);

            result.oldSymbol = symbol();

            console.log("Current:", result.oldSymbol);

            console.log("Opening Change Symbol...");
            await openChangeSymbol();

            console.log("Selecting strike:", strike, side);

            await clickStrike(strike, side);

            console.log("Waiting for update...");

            result.newSymbol =
                await waitForSymbolChange(result.oldSymbol);

            result.changed =
                result.oldSymbol !== result.newSymbol;

            result.success = result.changed;

            console.log("Old:", result.oldSymbol);
            console.log("New:", result.newSymbol);
            console.log(result);

            return result;

        }
        catch (e) {

            result.error = e.message;

            console.error(result);

            return result;

        }

    }

    return {

        changeStrike

    };

})();


await TVAutomation.changeStrike({
    chartIndex: 0,      // 0=left chart, 1=right chart
    strike: "24050",
    side: "call"        // "call" or "put"
});