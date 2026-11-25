// Copyright (c) 2021 Gray Matter Logic
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
(function () {
    "use strict";

    function initPropertyFilter() {
        const dateInputs = document.querySelectorAll(".field_date_range_filtter");
        if (
            window.jQuery &&
            window.jQuery.fn &&
            window.jQuery.fn.daterangepicker &&
            window.moment
        ) {
            dateInputs.forEach((dateInput) => {
                window.jQuery(dateInput).daterangepicker({
                    autoApply: true,
                    autoUpdateInput: true,
                    minDate: window.moment().startOf("day"),
                    locale: {
                        format: "DD/MM/YYYY",
                        separator: " - ",
                        applyLabel: "Aplicar",
                        cancelLabel: "Cancelar",
                        daysOfWeek: [
                            "Do",
                            "Lu",
                            "Ma",
                            "Mi",
                            "Ju",
                            "Vi",
                            "Sá",
                        ],
                        monthNames: [
                            "Enero",
                            "Febrero",
                            "Marzo",
                            "Abril",
                            "Mayo",
                            "Junio",
                            "Julio",
                            "Agosto",
                            "Septiembre",
                            "Octubre",
                            "Noviembre",
                            "Diciembre",
                        ],
                        firstDay: 1,
                    },
                });
            });
        }

        document.querySelectorAll(".amu-date-range").forEach((dateRange) => {
            const startInput = dateRange.querySelector('[name="date_start"]');
            const endInput = dateRange.querySelector('[name="date_end"]');
            if (!startInput || !endInput) {
                return;
            }

            const formatDate = (date) =>
                [
                    date.getFullYear(),
                    String(date.getMonth() + 1).padStart(2, "0"),
                    String(date.getDate()).padStart(2, "0"),
                ].join("-");
            const addDays = (value, days) => {
                const date = value ? new Date(`${value}T00:00:00`) : new Date();
                date.setDate(date.getDate() + days);
                return formatDate(date);
            };
            const updateDateLimits = () => {
                startInput.min = formatDate(new Date());
                endInput.min = addDays(startInput.value, 1);
                startInput.max = endInput.value
                    ? addDays(endInput.value, -1)
                    : "";
            };

            startInput.addEventListener("change", updateDateLimits);
            endInput.addEventListener("change", updateDateLimits);
            updateDateLimits();
        });

        document.querySelectorAll(".amu-search-guests").forEach((occupancy) => {
            const trigger = occupancy.querySelector("[data-occupancy-trigger]");
            const popover = occupancy.querySelector(".amu-occupancy-popover");
            const summary = occupancy.querySelector("[data-occupancy-summary]");
            if (!trigger || !popover || !summary) {
                return;
            }

            const inputFor = (name) =>
                occupancy.querySelector(`[data-occupancy-value="${name}"]`);
            const countFor = (name) =>
                occupancy.querySelector(`[data-occupancy-count="${name}"]`);

            function updateOccupancy() {
                const adults = parseInt(inputFor("adults").value, 10) || 1;
                const children = parseInt(inputFor("children").value, 10) || 0;
                const rooms = parseInt(inputFor("rooms").value, 10) || 1;
                occupancy.querySelector("[data-occupancy-total]").value =
                    String(adults + children);
                countFor("adults").textContent = String(adults);
                countFor("children").textContent = String(children);
                countFor("rooms").textContent = String(rooms);
                summary.textContent =
                    `${adults} ${adults === 1 ? "adulto" : "adultos"} · ` +
                    `${children} ${children === 1 ? "niño" : "niños"} · ` +
                    `${rooms} ${rooms === 1 ? "habitación" : "habitaciones"}`;

                occupancy
                    .querySelectorAll("[data-occupancy-stepper]")
                    .forEach((button) => {
                        const value = parseInt(
                            inputFor(button.dataset.occupancyStepper).value,
                            10
                        );
                        const minimum =
                            button.dataset.occupancyStepper === "children" ? 0 : 1;
                        const maximum =
                            button.dataset.occupancyStepper === "adults" ? 20 : 10;
                        const next = value + parseInt(button.dataset.step, 10);
                        button.disabled = next < minimum || next > maximum;
                    });
            }

            function closePopover() {
                popover.hidden = true;
                trigger.setAttribute("aria-expanded", "false");
            }

            trigger.addEventListener("click", () => {
                const isOpen = trigger.getAttribute("aria-expanded") === "true";
                popover.hidden = isOpen;
                trigger.setAttribute("aria-expanded", String(!isOpen));
            });

            occupancy
                .querySelectorAll("[data-occupancy-stepper]")
                .forEach((button) => {
                    button.addEventListener("click", () => {
                        const input = inputFor(button.dataset.occupancyStepper);
                        const current = parseInt(input.value, 10) || 0;
                        const minimum =
                            button.dataset.occupancyStepper === "children" ? 0 : 1;
                        const maximum =
                            button.dataset.occupancyStepper === "adults" ? 20 : 10;
                        const next =
                            current + parseInt(button.dataset.step, 10);
                        input.value = String(
                            Math.max(minimum, Math.min(maximum, next))
                        );
                        updateOccupancy();
                    });
                });

            occupancy
                .querySelectorAll("[data-occupancy-toggle]")
                .forEach((checkbox) => {
                    checkbox.addEventListener("change", () => {
                        const valueInput = occupancy.querySelector(
                            `[data-occupancy-toggle-value="${checkbox.dataset.occupancyToggle}"]`
                        );
                        valueInput.value = checkbox.checked ? "1" : "0";
                    });
                });

            occupancy
                .querySelector("[data-occupancy-done]")
                .addEventListener("click", closePopover);
            document.addEventListener("click", (event) => {
                if (!occupancy.contains(event.target)) {
                    closePopover();
                }
            });
            document.addEventListener("keydown", (event) => {
                if (event.key === "Escape" && !popover.hidden) {
                    closePopover();
                    trigger.focus();
                }
            });

            updateOccupancy();
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initPropertyFilter);
    } else {
        initPropertyFilter();
    }
})();
