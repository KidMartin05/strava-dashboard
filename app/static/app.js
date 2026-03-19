document.addEventListener("DOMContentLoaded", () => {
    const mainButtons = document.querySelectorAll("[data-tab-target]");
    const mainSections = document.querySelectorAll(".tab-section");
    const tooltip = document.getElementById("heatmap-tooltip");

    mainButtons.forEach((button) => {
        button.addEventListener("click", () => {
            const targetId = button.dataset.tabTarget;

            mainButtons.forEach((btn) => btn.classList.remove("active"));
            mainSections.forEach((section) => section.classList.remove("active"));

            button.classList.add("active");
            document.getElementById(targetId)?.classList.add("active");
        });
    });

    const subButtons = document.querySelectorAll("[data-subtab-target]");
    const subSections = document.querySelectorAll(".subtab-section");

    subButtons.forEach((button) => {
        button.addEventListener("click", () => {
            const targetId = button.dataset.subtabTarget;

            subButtons.forEach((btn) => btn.classList.remove("active"));
            subSections.forEach((section) => section.classList.remove("active"));

            button.classList.add("active");
            document.getElementById(targetId)?.classList.add("active");
        });
    });

    const escapeHtml = (value) => String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");

    const formatMetric = (label, value) => {
        if (value === null || value === undefined || value === "") {
            return "";
        }

        return `<div><strong>${escapeHtml(label)}:</strong> ${escapeHtml(value)}</div>`;
    };

    const renderTooltip = (payload) => {
        const summaryText = payload.run_count === 1 ? "1 run" : `${payload.run_count} runs`;
        const runsMarkup = payload.runs.length
            ? payload.runs.map((run) => `
                <div class="tooltip-run">
                    <div class="tooltip-run-name">${escapeHtml(run.name)}</div>
                    <div class="tooltip-run-date">${escapeHtml(run.date ?? "")}</div>
                    <div class="tooltip-run-metrics">
                        ${formatMetric("Distance", `${run.distance_miles} mi`)}
                        ${formatMetric("Time", run.moving_time)}
                        ${formatMetric("Pace", run.pace ? `${run.pace}/mi` : "N/A")}
                        ${formatMetric("Avg HR", run.average_heartrate ? `${run.average_heartrate} bpm` : "N/A")}
                        ${formatMetric("Max HR", run.max_heartrate ? `${run.max_heartrate} bpm` : "N/A")}
                        ${formatMetric("Elev", `${run.elevation_gain_m} m`)}
                    </div>
                </div>
            `).join("")
            : `<div class="tooltip-empty">No runs logged for this period.</div>`;

        tooltip.innerHTML = `
            <div class="tooltip-header">
                <div class="tooltip-title">${escapeHtml(payload.label)}</div>
                <div class="tooltip-total">${escapeHtml(payload.miles)} mi</div>
            </div>
            <div class="tooltip-summary">${escapeHtml(summaryText)}</div>
            <div class="tooltip-runs">${runsMarkup}</div>
        `;
    };

    const positionTooltip = (event, sourceElement = null) => {
        if (!tooltip || tooltip.hidden) {
            return;
        }

        const offset = 16;
        const tooltipRect = tooltip.getBoundingClientRect();
        let anchorX = event?.clientX;
        let anchorY = event?.clientY;

        if ((anchorX === undefined || anchorY === undefined) && sourceElement) {
            const rect = sourceElement.getBoundingClientRect();
            anchorX = rect.right;
            anchorY = rect.top + (rect.height / 2);
        }

        let left = anchorX + offset;
        let top = anchorY + offset;

        if (left + tooltipRect.width > window.innerWidth - 12) {
            left = anchorX - tooltipRect.width - offset;
        }

        if (top + tooltipRect.height > window.innerHeight - 12) {
            top = anchorY - tooltipRect.height - offset;
        }

        tooltip.style.left = `${Math.max(12, left)}px`;
        tooltip.style.top = `${Math.max(12, top)}px`;
    };

    const showTooltip = (event) => {
        const cell = event.currentTarget;
        const rawPayload = cell.dataset.tooltip;
        if (!rawPayload || !tooltip) {
            return;
        }

        renderTooltip(JSON.parse(rawPayload));
        tooltip.hidden = false;
        positionTooltip(event, cell);
    };

    const hideTooltip = () => {
        if (!tooltip) {
            return;
        }

        tooltip.hidden = true;
    };

    document.querySelectorAll("[data-tooltip]").forEach((cell) => {
        cell.setAttribute("tabindex", "0");
        cell.addEventListener("mouseenter", showTooltip);
        cell.addEventListener("mousemove", (event) => positionTooltip(event, cell));
        cell.addEventListener("mouseleave", hideTooltip);
        cell.addEventListener("focus", showTooltip);
        cell.addEventListener("blur", hideTooltip);
    });
});
