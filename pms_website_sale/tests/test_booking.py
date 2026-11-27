# Copyright (c) 2024 Gray Matter Logic
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
import json
from datetime import datetime, timedelta
from unittest.mock import patch

from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestPropertyBooking(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product = cls.env.ref("pms_sale.product_product_reservation")
        cls.partner_owner = cls.env["res.partner"].create({"name": "Property Owner"})
        cls.property = cls.env["pms.property"].create(
            {
                "name": "Booking Test Property",
                "owner_id": cls.partner_owner.id,
                "no_of_guests": 4,
                "min_nights": 1,
                "max_nights": 30,
                "website_published": True,
            }
        )
        cls.reservation_type = cls.env["pms.property.reservation"].create(
            {
                "name": "Standard Stay",
                "product_id": cls.product.id,
                "property_id": cls.property.id,
            }
        )
        today = datetime.now()
        # Use distinct date ranges per test to avoid cross-test interference
        cls.dates_free = (
            (today + timedelta(days=30)).strftime("%Y-%m-%d"),
            (today + timedelta(days=35)).strftime("%Y-%m-%d"),
        )
        cls.dates_conflict = (
            (today + timedelta(days=40)).strftime("%Y-%m-%d"),
            (today + timedelta(days=45)).strftime("%Y-%m-%d"),
        )
        cls.dates_cart = (
            (today + timedelta(days=50)).strftime("%Y-%m-%d"),
            (today + timedelta(days=55)).strftime("%Y-%m-%d"),
        )

    def _jsonrpc(self, url, params):
        return self.url_open(
            url,
            data=json.dumps(
                {"jsonrpc": "2.0", "method": "call", "params": params}
            ).encode(),
            headers={"Content-Type": "application/json"},
        )

    def test_check_availability_available(self):
        """Property with no reservations reports available for given dates."""
        self.authenticate("admin", "admin")
        resp = self._jsonrpc(
            f"/property/{self.property.id}/check_availability",
            {"date_start": self.dates_free[0], "date_end": self.dates_free[1]},
        )
        result = resp.json()["result"]
        self.assertTrue(result["available"])

    def test_house_availability_with_general_offer(self):
        self.authenticate("admin", "admin")
        response = self._jsonrpc(
            f"/property/{self.property.id}/check_availability",
            {
                "date_start": self.dates_free[0],
                "date_end": self.dates_free[1],
                "reservation_type_id": self.reservation_type.id,
            },
        )
        self.assertTrue(response.json()["result"]["available"])

    def test_non_hotel_booking_uses_only_property_level_offers(self):
        from ..controllers import website as website_module

        accommodation_type = self.env["pms.accommodation.type"].create(
            {
                "name": "Legacy Room Type",
                "property_id": self.property.id,
                "capacity": 2,
            }
        )
        room_type_offer = self.env["pms.property.reservation"].create(
            {
                "name": "Room Type Rate",
                "product_id": self.product.id,
                "property_id": self.property.id,
                "accommodation_type_id": accommodation_type.id,
            }
        )
        controller = website_module.PmsWebsiteSale()
        with patch.object(website_module, "request") as mock_request:
            mock_request.env = self.env
            reservation_types = controller._effective_reservation_types(
                self.property
            )
            invalid_offer, invalid_accommodation_type = (
                controller._resolve_reservation_offer(
                    self.property, room_type_offer.id, accommodation_type.id
                )
            )

        self.assertEqual(len(reservation_types), 1)
        self.assertEqual(reservation_types[0]["offer"], self.reservation_type)
        self.assertFalse(reservation_types[0]["accommodation_type"])
        self.assertFalse(invalid_offer)
        self.assertFalse(invalid_accommodation_type)
        self.authenticate("admin", "admin")
        response = self._jsonrpc(
            f"/property/{self.property.id}/check_availability",
            {
                "date_start": self.dates_free[0],
                "date_end": self.dates_free[1],
                "reservation_type_id": self.reservation_type.id,
            },
        )
        self.assertTrue(response.json()["result"]["available"])

    def test_check_availability_conflict(self):
        """Property with a confirmed reservation reports unavailable for those dates."""
        stage_confirmed = self.env.ref(
            "pms_sale.pms_stage_confirmed", raise_if_not_found=False
        )
        self.env["pms.reservation"].create(
            {
                "name": "Existing Reservation",
                "property_id": self.property.id,
                "start": self.dates_conflict[0],
                "stop": self.dates_conflict[1],
                "stage_id": stage_confirmed.id,
            }
        )
        self.authenticate("admin", "admin")
        resp = self._jsonrpc(
            f"/property/{self.property.id}/check_availability",
            {
                "date_start": self.dates_conflict[0],
                "date_end": self.dates_conflict[1],
            },
        )
        result = resp.json()["result"]
        self.assertFalse(result["available"])

    def test_add_to_cart_creates_order_and_reservation(self):
        """Posting booking details creates a sale order line and linked reservation."""
        self.authenticate("admin", "admin")
        resp = self._jsonrpc(
            f"/property/{self.property.id}/add_to_cart",
            {
                "date_start": self.dates_cart[0],
                "date_end": self.dates_cart[1],
                "reservation_type_id": self.reservation_type.id,
                "guests": [
                    {
                        "name": "Alice",
                        "phone": "555-1234",
                        "email": "alice@test.com",
                    }
                ],
            },
        )
        result = resp.json()["result"]
        self.assertEqual(result.get("redirect"), "/shop/checkout")
        reservation = self.env["pms.reservation"].search(
            [
                ("property_id", "=", self.property.id),
                ("start", "=", self.dates_cart[0]),
            ],
            limit=1,
        )
        self.assertTrue(reservation, "Expected pms.reservation to be created")
        self.assertTrue(reservation.sale_order_id)
        self.assertEqual(reservation.property_id, self.property)

    def test_booking_uses_accommodation_type_inventory(self):
        accommodation_type = self.env["pms.accommodation.type"].create(
            {
                "name": "Website Single",
                "property_id": self.property.id,
                "capacity": 1,
            }
        )
        self.env["pms.room"].create(
            {
                "name": "Website Room 1",
                "property_id": self.property.id,
                "type_id": self.env.ref("pms_base.pms_room_type_bed").id,
                "accommodation_type_id": accommodation_type.id,
            }
        )
        reservation_type = self.env["pms.property.reservation"].create(
            {
                "name": "Single Night",
                "product_id": self.product.id,
                "property_id": self.property.id,
                "accommodation_type_id": accommodation_type.id,
            }
        )
        self.authenticate("admin", "admin")
        params = {
            "date_start": self.dates_cart[0],
            "date_end": self.dates_cart[1],
            "reservation_type_id": reservation_type.id,
            "guests": [{"name": "Alice"}],
        }
        response = self._jsonrpc(
            f"/property/{self.property.id}/add_to_cart", params
        ).json()["result"]

        self.assertEqual(response.get("redirect"), "/shop/checkout")
        reservation = self.env["pms.reservation"].search(
            [
                ("property_id", "=", self.property.id),
                ("start", "=", self.dates_cart[0]),
                ("accommodation_type_id", "=", accommodation_type.id),
            ],
            limit=1,
        )
        self.assertTrue(reservation)
        self.assertFalse(reservation.room_id)
        self.assertEqual(reservation.reservation_type_id, reservation_type)
        self.assertFalse(
            self.env["pms.reservation"].is_accommodation_type_available(
                self.property.id,
                accommodation_type.id,
                datetime.strptime(self.dates_cart[0], "%Y-%m-%d"),
                datetime.strptime(self.dates_cart[1], "%Y-%m-%d"),
            )
        )
        fallback_response = self._jsonrpc(
            f"/property/{self.property.id}/add_to_cart",
            {
                **params,
                "reservation_type_id": self.reservation_type.id,
            },
        ).json()["result"]
        self.assertEqual(fallback_response["error"], "Invalid reservation type")

    def test_booking_uses_general_offer_when_type_has_no_specific_rate(self):
        self.property.property_type = "hotel"
        accommodation_type = self.env["pms.accommodation.type"].create(
            {
                "name": "Website Double",
                "property_id": self.property.id,
                "capacity": 2,
            }
        )
        self.env["pms.room"].create(
            {
                "name": "Website Room 2",
                "property_id": self.property.id,
                "type_id": self.env.ref("pms_base.pms_room_type_bed").id,
                "accommodation_type_id": accommodation_type.id,
            }
        )
        self.authenticate("admin", "admin")
        params = {
            "date_start": self.dates_cart[0],
            "date_end": self.dates_cart[1],
            "reservation_type_id": self.reservation_type.id,
            "accommodation_type_id": accommodation_type.id,
            "guests": [{"name": "Alice"}],
        }
        response = self._jsonrpc(
            f"/property/{self.property.id}/add_to_cart", params
        ).json()["result"]

        self.assertEqual(response.get("redirect"), "/shop/checkout")
        reservation = self.env["pms.reservation"].search(
            [
                ("property_id", "=", self.property.id),
                ("start", "=", self.dates_cart[0]),
                ("accommodation_type_id", "=", accommodation_type.id),
            ],
            limit=1,
        )
        self.assertEqual(reservation.reservation_type_id, self.reservation_type)
        line = self.env["sale.order.line"].search(
            [("pms_reservation_id", "=", reservation.id)], limit=1
        )
        self.assertEqual(line.price_unit, self.reservation_type.price)

    def test_hotel_availability_checks_requested_rooms_per_type(self):
        self.property.property_type = "hotel"
        accommodation_type = self.env["pms.accommodation.type"].create(
            {
                "name": "Hotel Twin",
                "property_id": self.property.id,
                "capacity": 2,
            }
        )
        self.env["pms.room"].create(
            {
                "name": "Twin 101",
                "property_id": self.property.id,
                "type_id": self.env.ref("pms_base.pms_room_type_bed").id,
                "accommodation_type_id": accommodation_type.id,
            }
        )
        self.authenticate("admin", "admin")
        base_params = {
            "date_start": self.dates_free[0],
            "date_end": self.dates_free[1],
            "accommodations": [
                {
                    "accommodation_type_id": accommodation_type.id,
                    "reservation_type_id": self.reservation_type.id,
                    "quantity": 1,
                }
            ],
        }
        available = self._jsonrpc(
            f"/property/{self.property.id}/check_availability", base_params
        ).json()["result"]
        unavailable = self._jsonrpc(
            f"/property/{self.property.id}/check_availability",
            {
                **base_params,
                "accommodations": [
                    {**base_params["accommodations"][0], "quantity": 2}
                ],
            },
        ).json()["result"]
        self.assertTrue(available["available"])
        self.assertFalse(unavailable["available"])

    def test_hotel_booking_creates_multiple_room_reservations_in_one_order(self):
        self.property.property_type = "hotel"
        single_type = self.env["pms.accommodation.type"].create(
            {
                "name": "Hotel Single",
                "property_id": self.property.id,
                "capacity": 2,
                "price": 180,
                "has_custom_price": True,
            }
        )
        double_type = self.env["pms.accommodation.type"].create(
            {
                "name": "Hotel Double",
                "property_id": self.property.id,
                "capacity": 2,
            }
        )
        room_type = self.env.ref("pms_base.pms_room_type_bed")
        self.env["pms.room"].create(
            [
                {
                    "name": "Single 101",
                    "property_id": self.property.id,
                    "type_id": room_type.id,
                    "accommodation_type_id": single_type.id,
                },
                {
                    "name": "Double 201",
                    "property_id": self.property.id,
                    "type_id": room_type.id,
                    "accommodation_type_id": double_type.id,
                },
                {
                    "name": "Double 202",
                    "property_id": self.property.id,
                    "type_id": room_type.id,
                    "accommodation_type_id": double_type.id,
                },
            ]
        )
        single_offer = self.env["pms.property.reservation"].create(
            {
                "name": "Single Nightly",
                "product_id": self.product.id,
                "property_id": self.property.id,
                "accommodation_type_id": single_type.id,
                "price": 180,
            }
        )
        self.reservation_type.price = 100
        self.authenticate("admin", "admin")
        response = self._jsonrpc(
            f"/property/{self.property.id}/add_to_cart",
            {
                "date_start": self.dates_cart[0],
                "date_end": self.dates_cart[1],
                "accommodations": [
                    {
                        "accommodation_type_id": single_type.id,
                        "reservation_type_id": single_offer.id,
                        "rooms": [
                            {
                                "guests": [
                                    {"name": "Alice"},
                                    {"name": "Alex"},
                                ]
                            }
                        ],
                    },
                    {
                        "accommodation_type_id": double_type.id,
                        "reservation_type_id": self.reservation_type.id,
                        "rooms": [
                            {"guests": [{"name": "Bea"}]},
                            {"guests": [{"name": "Charlie"}]},
                        ],
                    },
                ],
            },
        ).json()["result"]

        self.assertEqual(response.get("redirect"), "/shop/checkout")
        reservations = self.env["pms.reservation"].search(
            [
                ("property_id", "=", self.property.id),
                ("start", "=", self.dates_cart[0]),
            ]
        )
        self.assertEqual(len(reservations), 3)
        self.assertEqual(
            len(
                reservations.filtered(
                    lambda item: item.accommodation_type_id == single_type
                )
            ),
            1,
        )
        self.assertEqual(
            len(
                reservations.filtered(
                    lambda item: item.accommodation_type_id == double_type
                )
            ),
            2,
        )
        self.assertEqual(
            reservations.filtered(
                lambda item: item.accommodation_type_id == single_type
            ).guest_ids.mapped("name"),
            ["Alice", "Alex"],
        )
        self.assertEqual(len(reservations.mapped("sale_order_id")), 1)
        lines_by_type = {
            line.pms_reservation_id.accommodation_type_id.id: line
            for line in reservations.mapped("sale_order_line_id")
        }
        self.assertEqual(lines_by_type[single_type.id].price_unit, 180)
        self.assertEqual(lines_by_type[double_type.id].price_unit, 100)

    def test_hotel_booking_validates_guests_for_each_room(self):
        self.property.property_type = "hotel"
        accommodation_type = self.env["pms.accommodation.type"].create(
            {
                "name": "Hotel Single Guest",
                "property_id": self.property.id,
                "capacity": 1,
            }
        )
        self.env["pms.room"].create(
            {
                "name": "Single Guest 101",
                "property_id": self.property.id,
                "type_id": self.env.ref("pms_base.pms_room_type_bed").id,
                "accommodation_type_id": accommodation_type.id,
            }
        )
        self.authenticate("admin", "admin")
        response = self._jsonrpc(
            f"/property/{self.property.id}/add_to_cart",
            {
                "date_start": self.dates_cart[0],
                "date_end": self.dates_cart[1],
                "accommodations": [
                    {
                        "accommodation_type_id": accommodation_type.id,
                        "reservation_type_id": self.reservation_type.id,
                        "rooms": [
                            {
                                "guests": [
                                    {"name": "Alice"},
                                    {"name": "Alex"},
                                ]
                            }
                        ],
                    }
                ],
            },
        ).json()["result"]

        self.assertEqual(response["error"], "Too many guests for this room type")
        self.assertFalse(
            self.env["pms.reservation"].search(
                [
                    ("property_id", "=", self.property.id),
                    ("start", "=", self.dates_cart[0]),
                ]
            )
        )

    def test_add_to_cart_requires_login(self):
        """Public user attempting to add to cart receives a redirect to login."""
        self.authenticate(None, None)
        resp = self._jsonrpc(
            f"/property/{self.property.id}/add_to_cart",
            {
                "date_start": self.dates_cart[0],
                "date_end": self.dates_cart[1],
                "reservation_type_id": self.reservation_type.id,
                "guests": [{"name": "Bob"}],
            },
        )
        result = resp.json()["result"]
        self.assertIn("redirect", result)
        self.assertIn("/web/login", result["redirect"])
