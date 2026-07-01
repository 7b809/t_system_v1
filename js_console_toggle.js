(async () => {
    function getCharts() {
        return [...document.querySelectorAll(".chart-container")];
    }

    function getActiveChart() {
        return document.querySelector(".chart-container.active");
    }

    function getSymbol(chart) {
        return (
            chart
                ?.querySelector('button[aria-label="Change symbol"]')
                ?.textContent
                ?.trim() || "Unknown"
        );
    }

    function sleep(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }

    function activateChart(chart) {
        if (!chart) return;

        // Try several events since TradingView sometimes ignores a simple click
        const pane =
            chart.querySelector('[data-qa-id="pane"]') ||
            chart.querySelector(".chart-gui-wrapper") ||
            chart;

        ["pointerdown", "mousedown", "mouseup", "click"].forEach(type => {
            pane.dispatchEvent(
                new MouseEvent(type, {
                    bubbles: true,
                    cancelable: true,
                    view: window
                })
            );
        });
    }

    const charts = getCharts();

    if (charts.length < 2) {
        console.log("Need at least 2 charts.");
        return;
    }

    const original = getActiveChart();

    if (!original) {
        console.log("No active chart found.");
        return;
    }

    const originalIndex = charts.indexOf(original);
    const nextIndex = (originalIndex + 1) % charts.length;
    const nextChart = charts[nextIndex];

    console.log("Original:", originalIndex, getSymbol(original));

    activateChart(nextChart);

    await sleep(1000);

    let current = getActiveChart();
    console.log("After toggle:", charts.indexOf(current), getSymbol(current));

    activateChart(original);

    await sleep(1000);

    current = getActiveChart();
    console.log("Back to original:", charts.indexOf(current), getSymbol(current));

})();