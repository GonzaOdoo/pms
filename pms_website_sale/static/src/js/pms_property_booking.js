// Copyright (c) 2021 Gray Matter Logic
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
/** @odoo-module **/
import {_t} from "@web/core/l10n/translation";

(function () {
    "use strict";

    function init() {
        var bookingModal = document.getElementById("pmsBookingModal");
        if (!bookingModal) {
            return;
        }

        var addGuestBtn = document.getElementById("pms_add_guest");
        var propertyId = bookingModal && bookingModal.dataset.propertyId;
        var isHotelFlow = bookingModal.dataset.bookingFlow === "hotel";
        var guestList = document.getElementById("pms_guest_list");
        var hotelTypeRows = Array.from(
            document.querySelectorAll("[data-hotel-type-row]")
        );
        var startInput = document.getElementById("date_start");
        var endInput = document.getElementById("date_end");
        var reservationTypeEl = document.getElementById("reservation_type_id");
        var availStatus = document.getElementById("pms_availability_status");
        var addToCartBtn = document.getElementById("pmsAddToCart");

        function selectedAccommodationTypeId() {
            if (!reservationTypeEl || !reservationTypeEl.value) {
                return false;
            }
            var selectedOption =
                reservationTypeEl.options[reservationTypeEl.selectedIndex];
            return selectedOption && selectedOption.dataset.accommodationTypeId
                ? parseInt(selectedOption.dataset.accommodationTypeId, 10)
                : false;
        }

        // Set minimum date to today
        var today = new Date().toISOString().split("T")[0];
        if (startInput) {
            startInput.min = today;
        }
        if (endInput) {
            endInput.min = today;
        }

        function jsonRpc(url, params) {
            return fetch(url, {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({jsonrpc: "2.0", method: "call", params: params}),
            })
                .then(function (r) {
                    return r.json();
                })
                .then(function (data) {
                    return data.result;
                });
        }

        function checkAvailability() {
            var start = startInput && startInput.value;
            var end = endInput && endInput.value;
            if (!start || !end || !propertyId || !availStatus) {
                return;
            }
            if (start >= end) {
                availStatus.innerHTML =
                    '<span class="text-danger">' +
                    _t("La salida debe ser posterior a la entrada") +
                    "</span>";
                return;
            }
            availStatus.innerHTML =
                '<span class="text-muted">' + _t("Consultando disponibilidad…") + "</span>";
            var params = {
                date_start: start,
                date_end: end,
            };
            if (isHotelFlow) {
                params.accommodations = hotelTypeRows
                    .map(function (row) {
                        var quantity = parseInt(
                            row.querySelector("[data-hotel-room-quantity]").value,
                            10
                        );
                        return {
                            accommodation_type_id: parseInt(row.dataset.typeId, 10),
                            reservation_type_id: parseInt(row.dataset.offerId, 10),
                            quantity: quantity || 0,
                        };
                    })
                    .filter(function (selection) {
                        return selection.quantity > 0;
                    });
                if (!params.accommodations.length) {
                    availStatus.innerHTML =
                        '<span class="text-muted">' +
                        _t("Elegí al menos una habitación") +
                        "</span>";
                    return;
                }
            } else {
                params.reservation_type_id =
                    reservationTypeEl && reservationTypeEl.value
                        ? parseInt(reservationTypeEl.value, 10)
                        : false;
                params.accommodation_type_id = selectedAccommodationTypeId();
            }
            jsonRpc(
                "/property/" + propertyId + "/check_availability",
                params
            )
                .then(function (result) {
                    if (result && result.available) {
                        availStatus.innerHTML =
                            '<span class="text-success">' +
                            '<i class="fa fa-check-circle"></i> ' +
                            _t("Disponible") +
                            "</span>";
                    } else {
                        var message =
                            result && result.error
                                ? result.error
                                : _t("No disponible para esas fechas");
                        availStatus.innerHTML =
                            '<span class="text-danger">' +
                            '<i class="fa fa-times-circle"></i> ' +
                            message +
                            "</span>";
                    }
                })
                .catch(function () {
                    availStatus.innerHTML =
                        '<span class="text-muted">' +
                        _t("No se pudo consultar la disponibilidad") +
                        "</span>";
                });
        }

        if (startInput) {
            startInput.addEventListener("change", function () {
                if (endInput && endInput.value && endInput.value <= startInput.value) {
                    endInput.value = "";
                }
                if (endInput) {
                    endInput.min = startInput.value;
                }
                checkAvailability();
            });
        }
        if (endInput) {
            endInput.addEventListener("change", checkAvailability);
        }
        if (reservationTypeEl) {
            reservationTypeEl.addEventListener("change", function () {
                var selectedOption =
                    reservationTypeEl.options[reservationTypeEl.selectedIndex];
                var maxGuests = parseInt(
                    (selectedOption && selectedOption.dataset.maxGuests) ||
                        (addGuestBtn && addGuestBtn.dataset.propertyMax) ||
                        "0",
                    10
                );
                if (addGuestBtn) {
                    addGuestBtn.dataset.max = String(maxGuests);
                }
                checkAvailability();
            });
        }

        function reindexGuests() {
            var rows = guestList.querySelectorAll(".pms-guest-row");
            rows.forEach(function (row, i) {
                var nameInput = row.querySelector("input[data-guest-field='name']");
                var phoneInput = row.querySelector("input[data-guest-field='phone']");
                var emailInput = row.querySelector("input[data-guest-field='email']");
                if (nameInput) {
                    nameInput.name = "guest_name_" + i;
                }
                if (phoneInput) {
                    phoneInput.name = "guest_phone_" + i;
                }
                if (emailInput) {
                    emailInput.name = "guest_email_" + i;
                }
            });
        }

        function collectGuests() {
            var guests = [];
            guestList.querySelectorAll(".pms-guest-row").forEach(function (row) {
                var nameInput = row.querySelector("input[data-guest-field='name']");
                var phoneInput = row.querySelector("input[data-guest-field='phone']");
                var emailInput = row.querySelector("input[data-guest-field='email']");
                var name = (nameInput && nameInput.value.trim()) || "";
                if (name) {
                    guests.push({
                        name: name,
                        phone: (phoneInput && phoneInput.value.trim()) || "",
                        email: (emailInput && emailInput.value.trim()) || "",
                    });
                }
            });
            return guests;
        }

        function createHotelGuestRow(roomCard, index) {
            var guestRow = document.createElement("div");
            guestRow.className = "amu-hotel-guest";
            var nameInput = document.createElement("input");
            nameInput.type = "text";
            nameInput.className = "form-control";
            nameInput.placeholder = _t("Nombre completo");
            nameInput.required = true;
            nameInput.dataset.guestField = "name";
            var phoneInput = document.createElement("input");
            phoneInput.type = "tel";
            phoneInput.className = "form-control";
            phoneInput.placeholder = _t("Teléfono");
            phoneInput.dataset.guestField = "phone";
            var emailInput = document.createElement("input");
            emailInput.type = "email";
            emailInput.className = "form-control";
            emailInput.placeholder = _t("Correo electrónico");
            emailInput.dataset.guestField = "email";
            guestRow.appendChild(nameInput);
            guestRow.appendChild(phoneInput);
            guestRow.appendChild(emailInput);
            if (index > 0) {
                var removeButton = document.createElement("button");
                removeButton.type = "button";
                removeButton.className = "amu-hotel-guest-remove";
                removeButton.title = _t("Quitar huésped");
                removeButton.textContent = "×";
                removeButton.addEventListener("click", function () {
                    guestRow.remove();
                    updateHotelGuestControls(roomCard);
                });
                guestRow.appendChild(removeButton);
            }
            return guestRow;
        }

        function updateHotelGuestControls(roomCard) {
            var guestRows = roomCard.querySelectorAll(".amu-hotel-guest");
            var addButton = roomCard.querySelector("[data-hotel-add-guest]");
            var maxGuests = parseInt(roomCard.dataset.maxGuests || "0", 10);
            addButton.disabled = maxGuests > 0 && guestRows.length >= maxGuests;
        }

        function addHotelGuest(roomCard) {
            var guestList = roomCard.querySelector("[data-hotel-guests]");
            var guestRows = guestList.querySelectorAll(".amu-hotel-guest");
            var maxGuests = parseInt(roomCard.dataset.maxGuests || "0", 10);
            if (maxGuests > 0 && guestRows.length >= maxGuests) {
                window.alert(
                    _t("Este tipo permite hasta %s huésped(es) por habitación.").replace(
                        "%s",
                        maxGuests
                    )
                );
                return;
            }
            guestList.appendChild(createHotelGuestRow(roomCard, guestRows.length));
            updateHotelGuestControls(roomCard);
        }

        function createHotelRoomCard(row, index) {
            var roomCard = document.createElement("section");
            roomCard.className = "amu-hotel-room-guest-card";
            roomCard.dataset.maxGuests = row.dataset.maxGuests || "0";
            var heading = document.createElement("h6");
            heading.textContent = _t("Habitación %s").replace("%s", index + 1);
            roomCard.appendChild(heading);
            var guestList = document.createElement("div");
            guestList.dataset.hotelGuests = "";
            roomCard.appendChild(guestList);
            var addButton = document.createElement("button");
            addButton.type = "button";
            addButton.className = "amu-hotel-add-guest";
            addButton.dataset.hotelAddGuest = "";
            addButton.textContent = _t("Agregar huésped");
            addButton.addEventListener("click", function () {
                addHotelGuest(roomCard);
            });
            roomCard.appendChild(addButton);
            addHotelGuest(roomCard);
            return roomCard;
        }

        function renderHotelRooms(row) {
            var quantityInput = row.querySelector("[data-hotel-room-quantity]");
            var quantity = parseInt(quantityInput.value, 10) || 0;
            var roomContainer = row.querySelector(
                "[data-hotel-room-assignments]"
            );
            var roomCards = roomContainer.querySelectorAll(
                ".amu-hotel-room-guest-card"
            );
            while (roomCards.length > quantity) {
                roomCards[roomCards.length - 1].remove();
                roomCards = roomContainer.querySelectorAll(
                    ".amu-hotel-room-guest-card"
                );
            }
            while (roomCards.length < quantity) {
                roomContainer.appendChild(
                    createHotelRoomCard(row, roomCards.length)
                );
                roomCards = roomContainer.querySelectorAll(
                    ".amu-hotel-room-guest-card"
                );
            }
            roomContainer.hidden = quantity === 0;
        }

        function collectHotelBookings() {
            var accommodations = [];
            var invalid = false;
            hotelTypeRows.forEach(function (row) {
                var quantity = parseInt(
                    row.querySelector("[data-hotel-room-quantity]").value,
                    10
                );
                if (!quantity) {
                    return;
                }
                var rooms = [];
                row.querySelectorAll(".amu-hotel-room-guest-card").forEach(
                    function (roomCard) {
                        var guests = [];
                        roomCard.querySelectorAll(".amu-hotel-guest").forEach(
                            function (guestRow) {
                                var name =
                                    guestRow.querySelector(
                                        "[data-guest-field='name']"
                                    ).value || "";
                                if (name.trim()) {
                                    guests.push({
                                        name: name.trim(),
                                        phone:
                                            guestRow.querySelector(
                                                "[data-guest-field='phone']"
                                            ).value || "",
                                        email:
                                            guestRow.querySelector(
                                                "[data-guest-field='email']"
                                            ).value || "",
                                    });
                                } else {
                                    invalid = true;
                                }
                            }
                        );
                        rooms.push({guests: guests});
                    }
                );
                accommodations.push({
                    accommodation_type_id: parseInt(row.dataset.typeId, 10),
                    reservation_type_id: parseInt(row.dataset.offerId, 10),
                    rooms: rooms,
                });
            });
            if (invalid) {
                return {error: _t("Completá el nombre de cada huésped.")};
            }
            if (!accommodations.length) {
                return {error: _t("Elegí al menos una habitación.")};
            }
            return {accommodations: accommodations};
        }

        if (isHotelFlow) {
            hotelTypeRows.forEach(function (row) {
                var quantityInput = row.querySelector(
                    "[data-hotel-room-quantity]"
                );
                quantityInput.addEventListener("change", function () {
                    renderHotelRooms(row);
                    checkAvailability();
                });
            });
        }

        if (addGuestBtn && guestList) {
            addGuestBtn.addEventListener("click", function () {
                var maxGuests = parseInt(addGuestBtn.dataset.max || "0", 10);
                var currentRows = guestList.querySelectorAll(".pms-guest-row").length;
                if (maxGuests > 0 && currentRows >= maxGuests) {
                    window.alert(
                        _t("Este alojamiento permite hasta %s huésped(es).").replace(
                            "%s",
                            maxGuests
                        )
                    );
                    return;
                }
                var idx = currentRows;
                var row = document.createElement("div");
                row.className = "pms-guest-row row mb-2 align-items-center";
                row.innerHTML =
                    '<div class="col-md-4">' +
                    '<input type="text" class="form-control"' +
                    ' name="guest_name_' +
                    idx +
                    '" data-guest-field="name" required />' +
                    "</div>" +
                    '<div class="col-md-3">' +
                    '<input type="tel" class="form-control"' +
                    ' name="guest_phone_' +
                    idx +
                    '" data-guest-field="phone" />' +
                    "</div>" +
                    '<div class="col-md-4">' +
                    '<input type="email" class="form-control"' +
                    ' name="guest_email_' +
                    idx +
                    '" data-guest-field="email" />' +
                    "</div>" +
                    '<div class="col-md-1">' +
                    '<button type="button" class="btn btn-outline-danger btn-sm pms-remove-guest"' +
                    ">" +
                    '<i class="fa fa-times"></i>' +
                    "</button>" +
                    "</div>";
                row.querySelector("[data-guest-field='name']").placeholder =
                    _t("Nombre completo");
                row.querySelector("[data-guest-field='phone']").placeholder =
                    _t("Teléfono");
                row.querySelector("[data-guest-field='email']").placeholder =
                    _t("Correo electrónico");
                row.querySelector(".pms-remove-guest").title = _t(
                    "Quitar huésped"
                );
                row.querySelector(".pms-remove-guest").addEventListener(
                    "click",
                    function () {
                        row.remove();
                        reindexGuests();
                    }
                );
                guestList.appendChild(row);
            });
        }

        if (addToCartBtn && propertyId) {
            addToCartBtn.addEventListener("click", function () {
                var form = document.getElementById("pmsBookingForm");
                if (form && !form.reportValidity()) {
                    return;
                }
                var params = {
                    date_start: startInput && startInput.value,
                    date_end: endInput && endInput.value,
                };
                if (isHotelFlow) {
                    var hotelBooking = collectHotelBookings();
                    if (hotelBooking.error) {
                        window.alert(hotelBooking.error);
                        return;
                    }
                    params.accommodations = hotelBooking.accommodations;
                } else {
                    var guests = collectGuests();
                    if (!guests.length) {
                        window.alert(_t("Agregá al menos un huésped."));
                        return;
                    }
                    params.reservation_type_id =
                        reservationTypeEl && parseInt(reservationTypeEl.value, 10);
                    params.accommodation_type_id = selectedAccommodationTypeId();
                    params.guests = guests;
                }
                addToCartBtn.disabled = true;
                jsonRpc("/property/" + propertyId + "/add_to_cart", params)
                    .then(function (result) {
                        if (result && result.redirect) {
                            window.location.href = result.redirect;
                        } else {
                            window.alert(
                                (result && result.error) || _t("Ocurrió un error.")
                            );
                            addToCartBtn.disabled = false;
                        }
                    })
                    .catch(function () {
                        window.alert(
                            _t("No se pudo continuar con la reserva. Intentá nuevamente.")
                        );
                        addToCartBtn.disabled = false;
                    });
            });
        }
    }

    // Execute init whether DOM is still loading or already ready
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
