/* =====================================================
   MyVoice · Admin Dashboard Interactivity
   - Animated number counters with easeOutCubic
   - Chart.js charts (activity, status, candidates, dept)
   - Server clock
   - Theme toggle (persisted to localStorage)
   ===================================================== */

(function () {
    "use strict";

    /* ---------- Animated Counters ---------- */
    function animateCounter(el, target, duration) {
        if (!target) { el.textContent = "0"; return; }
        duration = duration || 1300;
        var start = 0;
        var startTime = null;
        function step(timestamp) {
            if (!startTime) startTime = timestamp;
            var progress = Math.min((timestamp - startTime) / duration, 1);
            var eased = 1 - Math.pow(1 - progress, 3);
            var value = Math.floor(start + (target - start) * eased);
            el.textContent = value.toLocaleString();
            if (progress < 1) {
                requestAnimationFrame(step);
            } else {
                el.textContent = target.toLocaleString();
            }
        }
        requestAnimationFrame(step);
    }

    function initCounters() {
        var els = document.querySelectorAll(".mv-kpi-value [data-count]");
        els.forEach(function (el) {
            var target = parseInt(el.getAttribute("data-count"), 10) || 0;
            animateCounter(el, target);
        });
    }

    /* ---------- Server Clock ---------- */
    function initClock() {
        var el = document.getElementById("mvClock");
        if (!el) return;
        function tick() {
            var d = new Date();
            var pad = function (n) { return n < 10 ? "0" + n : "" + n; };
            var dateLabel = d.toLocaleDateString(undefined, {
                weekday: "short", day: "2-digit", month: "short"
            });
            el.textContent = dateLabel + " · " + pad(d.getHours()) + ":" + pad(d.getMinutes()) + ":" + pad(d.getSeconds());
        }
        tick();
        setInterval(tick, 1000);
    }

    /* ---------- Theme Toggle ---------- */
    function applyTheme(theme) {
        document.documentElement.setAttribute("data-mv-theme", theme);
        try { localStorage.setItem("mv-theme", theme); } catch (e) {}
        // Re-render charts if they exist so colors update
        if (window.mvCharts) {
            Object.values(window.mvCharts).forEach(function (c) {
                if (c && c.update) c.update();
            });
        }
    }

    function initTheme() {
        var stored = null;
        try { stored = localStorage.getItem("mv-theme"); } catch (e) {}
        if (stored) {
            applyTheme(stored);
        } else if (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches) {
            applyTheme("dark");
        }

        var buttons = document.querySelectorAll("[data-mv-theme-toggle]");
        buttons.forEach(function (btn) {
            btn.addEventListener("click", function () {
                var current = document.documentElement.getAttribute("data-mv-theme") || "light";
                applyTheme(current === "dark" ? "light" : "dark");
            });
        });
    }

    /* ---------- Chart.js helpers ---------- */
    function readThemeColors() {
        var cs = getComputedStyle(document.documentElement);
        function v(name, fallback) {
            var val = (cs.getPropertyValue(name) || "").trim();
            return val || fallback;
        }
        return {
            text: v("--mv-text", "#0b1220"),
            text2: v("--mv-text-2", "#1e293b"),
            muted: v("--mv-text-muted", "#64748b"),
            border: v("--mv-border", "rgba(15,23,42,0.08)"),
            primary: v("--mv-primary", "#1d4ed8"),
            primary2: v("--mv-primary-2", "#2563eb"),
            primary3: v("--mv-primary-3", "#3b82f6"),
            accent: v("--mv-accent", "#0ea5e9"),
            success: v("--mv-success", "#059669"),
            success2: v("--mv-success-2", "#10b981"),
            warning: v("--mv-warning", "#d97706"),
            warning2: v("--mv-warning-2", "#f59e0b"),
            danger: v("--mv-danger", "#dc2626"),
            purple: v("--mv-purple", "#7c3aed"),
            surface: v("--mv-surface", "#ffffff"),
            surface2: v("--mv-surface-2", "#f8fafc"),
        };
    }

    function baseChartOptions(c) {
        return {
            responsive: true,
            maintainAspectRatio: false,
            animation: {
                duration: 900,
                easing: "easeOutQuart"
            },
            interaction: { mode: "index", intersect: false },
            plugins: {
                legend: {
                    labels: {
                        color: c.muted,
                        font: { size: 12, weight: "500", family: "system-ui, -apple-system, sans-serif" },
                        usePointStyle: true,
                        pointStyle: "circle",
                        padding: 14,
                        boxWidth: 8,
                        boxHeight: 8
                    }
                },
                tooltip: {
                    backgroundColor: "rgba(15, 23, 42, 0.94)",
                    titleColor: "#ffffff",
                    bodyColor: "#e2e8f0",
                    padding: 12,
                    cornerRadius: 10,
                    borderColor: "rgba(255,255,255,0.10)",
                    borderWidth: 1,
                    displayColors: true,
                    boxPadding: 4,
                    titleFont: { weight: "600", size: 12 },
                    bodyFont: { size: 12 }
                }
            },
            scales: {
                x: {
                    ticks: { color: c.muted, font: { size: 11, family: "system-ui, -apple-system, sans-serif" } },
                    grid: { color: c.border, drawBorder: false, display: false }
                },
                y: {
                    ticks: { color: c.muted, font: { size: 11, family: "system-ui, -apple-system, sans-serif" } },
                    grid: { color: c.border, drawBorder: false },
                    beginAtZero: true
                }
            }
        };
    }

    function initVotingActivity() {
        var el = document.getElementById("mvVotingActivityChart");
        if (!el || !window.Chart) return;
        var labels = JSON.parse(el.getAttribute("data-labels") || "[]");
        var values = JSON.parse(el.getAttribute("data-values") || "[]");
        var c = readThemeColors();

        // Build a soft gradient
        var ctx = el.getContext("2d");
        var gradient = ctx.createLinearGradient(0, 0, 0, 280);
        gradient.addColorStop(0, "rgba(37, 99, 235, 0.28)");
        gradient.addColorStop(1, "rgba(14, 165, 233, 0.02)");

        var chart = new Chart(el, {
            type: "line",
            data: {
                labels: labels,
                datasets: [{
                    label: "Ballots submitted",
                    data: values,
                    borderColor: c.primary,
                    backgroundColor: gradient,
                    borderWidth: 2.5,
                    fill: true,
                    tension: 0.38,
                    pointBackgroundColor: c.primary,
                    pointBorderColor: "#ffffff",
                    pointBorderWidth: 2,
                    pointRadius: 4,
                    pointHoverRadius: 7,
                    pointHoverBackgroundColor: c.primary,
                    pointHoverBorderColor: "#ffffff",
                }]
            },
            options: baseChartOptions(c)
        });
        if (!window.mvCharts) window.mvCharts = {};
        window.mvCharts.activity = chart;
    }

    function initElectionStatus() {
        var el = document.getElementById("mvElectionStatusChart");
        if (!el || !window.Chart) return;
        var d = parseInt(el.getAttribute("data-draft") || "0");
        var r = parseInt(el.getAttribute("data-ready") || "0");
        var a = parseInt(el.getAttribute("data-active") || "0");
        var c = parseInt(el.getAttribute("data-closed") || "0");
        var ar = parseInt(el.getAttribute("data-archived") || "0");
        var colors = readThemeColors();

        var chart = new Chart(el, {
            type: "doughnut",
            data: {
                labels: ["Draft", "Ready", "Active", "Closed", "Archived"],
                datasets: [{
                    data: [d, r, a, c, ar],
                    backgroundColor: [
                        colors.muted,
                        colors.accent,
                        colors.success,
                        colors.warning,
                        colors.purple
                    ],
                    borderColor: colors.surface,
                    borderWidth: 3,
                    hoverOffset: 8
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: "65%",
                animation: { duration: 1000, easing: "easeOutQuart" },
                plugins: {
                    legend: {
                        position: "bottom",
                        labels: {
                            color: colors.text2,
                            font: { size: 11.5, weight: "500" },
                            padding: 14,
                            usePointStyle: true,
                            pointStyle: "circle",
                            boxWidth: 8,
                            boxHeight: 8
                        }
                    },
                    tooltip: {
                        backgroundColor: "rgba(15, 23, 42, 0.94)",
                        titleColor: "#ffffff",
                        bodyColor: "#e2e8f0",
                        padding: 12,
                        cornerRadius: 10
                    }
                }
            }
        });
        if (!window.mvCharts) window.mvCharts = {};
        window.mvCharts.status = chart;
    }

    function initCandidateChart() {
        var el = document.getElementById("mvCandidateChart");
        if (!el || !window.Chart) return;
        var ranking = JSON.parse(el.getAttribute("data-ranking") || "[]");
        if (!ranking.length) return;
        var c = readThemeColors();
        var labels = ranking.map(function (r) { return r.name + " · " + r.position; });
        var data = ranking.map(function (r) { return r.votes; });

        var chart = new Chart(el, {
            type: "bar",
            data: {
                labels: labels,
                datasets: [{
                    label: "Votes",
                    data: data,
                    backgroundColor: function (context) {
                        var chart = context.chart;
                        var ctx = chart.ctx;
                        var gradient = ctx.createLinearGradient(0, 0, 400, 0);
                        gradient.addColorStop(0, c.primary);
                        gradient.addColorStop(1, c.accent);
                        return gradient;
                    },
                    borderRadius: 6,
                    maxBarThickness: 24,
                    borderSkipped: false,
                }]
            },
            options: {
                indexAxis: "y",
                responsive: true,
                maintainAspectRatio: false,
                animation: { duration: 900, easing: "easeOutQuart" },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: "rgba(15, 23, 42, 0.94)",
                        titleColor: "#ffffff",
                        bodyColor: "#e2e8f0",
                        padding: 12,
                        cornerRadius: 10
                    }
                },
                scales: {
                    x: {
                        ticks: { color: c.muted, font: { size: 11 } },
                        grid: { color: c.border, drawBorder: false },
                        beginAtZero: true
                    },
                    y: {
                        ticks: { color: c.text2, font: { size: 11 } },
                        grid: { display: false }
                    }
                }
            }
        });
        if (!window.mvCharts) window.mvCharts = {};
        window.mvCharts.candidates = chart;
    }

    function initDepartmentChart() {
        var el = document.getElementById("mvDepartmentChart");
        if (!el || !window.Chart) return;
        var data = JSON.parse(el.getAttribute("data-breakdown") || "[]");
        if (!data.length) return;
        var c = readThemeColors();
        var labels = data.map(function (d) { return d.name; });
        var voted = data.map(function (d) { return d.voted; });
        var remaining = data.map(function (d) { return Math.max(d.total - d.voted, 0); });

        var chart = new Chart(el, {
            type: "bar",
            data: {
                labels: labels,
                datasets: [
                    {
                        label: "Voted",
                        data: voted,
                        backgroundColor: c.success2,
                        borderRadius: 4,
                        maxBarThickness: 28,
                        borderSkipped: false,
                    },
                    {
                        label: "Pending",
                        data: remaining,
                        backgroundColor: c.muted,
                        borderRadius: 4,
                        maxBarThickness: 28,
                        borderSkipped: false,
                    }
                ]
            },
            options: baseChartOptions(c)
        });
        if (!window.mvCharts) window.mvCharts = {};
        window.mvCharts.department = chart;
    }

    /* ---------- Init ---------- */
    document.addEventListener("DOMContentLoaded", function () {
        initTheme();
        initClock();
        initCounters();
        if (window.Chart) {
            initVotingActivity();
            initElectionStatus();
            initCandidateChart();
            initDepartmentChart();
        }
    });
})();
