# Copyright (c) 2024 Gray Matter Logic
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
import json
from datetime import datetime, timedelta

from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestWebsiteSaleControllers(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.website = cls.env.ref("website.default_website")
        cls.product = cls.env.ref("pms_sale.product_product_reservation")
        cls.partner_owner = cls.env["res.partner"].create({"name": "Website Owner"})
        cls.property = cls.env["pms.property"].create(
            {
                "name": "Website Sale Property",
                "owner_id": cls.partner_owner.id,
                "website_id": cls.website.id,
                "is_published": True,
                "website_published": True,
                "city": "Boston",
                "no_of_guests": 6,
                "min_nights": 1,
                "max_nights": 14,
            }
        )
        cls.reservation_type = cls.env["pms.property.reservation"].create(
            {
                "name": "Nightly Rate",
                "product_id": cls.product.id,
                "price": 120.0,
                "property_id": cls.property.id,
            }
        )
        cls.global_reservation_type = cls.env["pms.property.reservation"].create(
            {
                "name": "Global Rate",
                "product_id": cls.product.id,
                "price": 99.0,
            }
        )
        cls.category = cls.env["pms.website.category"].create({"name": "City Stays"})
        cls.property.property_category_ids = cls.category
        today = datetime.now()
        cls.dates_free = (
            (today + timedelta(days=60)).strftime("%Y-%m-%d"),
            (today + timedelta(days=65)).strftime("%Y-%m-%d"),
        )
        cls.dates_blocked = (
            (today + timedelta(days=70)).strftime("%Y-%m-%d"),
            (today + timedelta(days=75)).strftime("%Y-%m-%d"),
        )
        cls.dates_cart = (
            (today + timedelta(days=80)).strftime("%Y-%m-%d"),
            (today + timedelta(days=85)).strftime("%Y-%m-%d"),
        )

    def _jsonrpc(self, url, params):
        return self.url_open(
            url,
            data=json.dumps(
                {"jsonrpc": "2.0", "method": "call", "params": params}
            ).encode(),
            headers={"Content-Type": "application/json"},
        )

    def test_property_listing_page(self):
        image = self.env["pms.property.image"].create(
            {
                "name": "Listing image",
                "image_1920": (
                    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwC"
                    "AAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
                ),
                "property_id": self.property.id,
            }
        )
        self.authenticate(None, None)
        response = self.url_open("/property")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Website Sale Property", response.content)
        self.assertIn(
            f"/web/image/pms.property.image/{image.id}/image_1024".encode(),
            response.content,
        )
        self.assertIn(b'data-results-view="list"', response.content)
        self.assertIn(b'data-results-view="grid"', response.content)
        self.assertIn(b"class=\"amu-property-grid\"", response.content)

    def test_property_listing_hides_setup_drafts(self):
        self.env["pms.property"].create(
            {
                "name": "Unfinished Property",
                "owner_id": self.partner_owner.id,
                "website_id": self.website.id,
                "is_published": True,
                "setup_state": "draft",
                "city": "Boston",
            }
        )
        self.authenticate(None, None)
        response = self.url_open("/property")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"Unfinished Property", response.content)

    def test_property_search_by_city(self):
        self.authenticate(None, None)
        response = self.url_open("/property?search=Boston")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Website Sale Property", response.content)

    def test_property_search_by_guest_count(self):
        self.authenticate(None, None)
        response = self.url_open("/property?guest_select=6")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Website Sale Property", response.content)

    def test_property_search_filters_by_property_type(self):
        hotel = self.env["pms.property"].create(
            {
                "name": "Boston Hotel",
                "owner_id": self.partner_owner.id,
                "website_id": self.website.id,
                "is_published": True,
                "city": "Boston",
                "property_type": "hotel",
            }
        )
        self.authenticate(None, None)

        response = self.url_open("/property?search=Boston&property_type=hotel")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Boston Hotel", response.content)
        self.assertNotIn(b"Website Sale Property", response.content)

    def test_property_search_filters_by_amenity(self):
        amenity = self.env["pms.amenity"].create({"name": "Private garden"})
        self.property.amenity_ids = [(4, amenity.id)]
        self.env["pms.property"].create(
            {
                "name": "Boston Without Garden",
                "owner_id": self.partner_owner.id,
                "website_id": self.website.id,
                "is_published": True,
                "city": "Boston",
            }
        )
        self.authenticate(None, None)

        response = self.url_open(
            f"/property?search=Boston&amenity_ids={amenity.id}"
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Website Sale Property", response.content)
        self.assertNotIn(b"Boston Without Garden", response.content)

    def test_property_search_displays_and_preserves_filters(self):
        amenity = self.env["pms.amenity"].create({"name": "Private balcony"})
        self.authenticate(None, None)

        response = self.url_open(
            f"/property?search=Boston&date_start=2026-10-12&date_end=2026-12-15"
            f"&guest_select=3&property_type=house&amenity_ids={amenity.id}"
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'name="search"', response.content)
        self.assertIn(b'name="date_start"', response.content)
        self.assertIn(b'name="date_end"', response.content)
        self.assertIn(b'name="guest_select"', response.content)
        self.assertIn(b'name="amenity_ids"', response.content)
        self.assertIn(b"Private balcony", response.content)

    def test_property_search_hides_parent_with_children(self):
        self.env["pms.property"].create(
            {
                "name": "Child Unit",
                "owner_id": self.partner_owner.id,
                "parent_id": self.property.id,
                "website_id": self.website.id,
                "is_published": True,
                "website_published": True,
                "city": "Boston",
            }
        )
        self.authenticate(None, None)
        response = self.url_open("/property?search=Boston")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"Website Sale Property", response.content)
        self.assertIn(b"Child Unit", response.content)

    def test_property_search_by_category(self):
        self.authenticate(None, None)
        slug = self.env["ir.http"]._slug(self.category)
        response = self.url_open(f"/property/category/{slug}")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Website Sale Property", response.content)

    def test_property_search_excludes_booked_dates(self):
        stage_confirmed = self.env.ref("pms_sale.pms_stage_confirmed")
        self.env["pms.reservation"].create(
            {
                "property_id": self.property.id,
                "start": self.dates_blocked[0],
                "stop": self.dates_blocked[1],
                "stage_id": stage_confirmed.id,
            }
        )
        self.authenticate(None, None)
        start = datetime.strptime(self.dates_blocked[0], "%Y-%m-%d").strftime(
            "%d/%m/%Y"
        )
        end = datetime.strptime(self.dates_blocked[1], "%Y-%m-%d").strftime("%d/%m/%Y")
        response = self.url_open(
            f"/property?date_start={self.dates_blocked[0]}"
            f"&date_end={self.dates_blocked[1]}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"Website Sale Property", response.content)

        legacy_response = self.url_open(f"/property?date_range={start} - {end}")
        self.assertEqual(legacy_response.status_code, 200)
        self.assertNotIn(b"Website Sale Property", legacy_response.content)

    def test_search_filters_rooms_guests_pets_and_work(self):
        hotel = self.env["pms.property"].create(
            {
                "name": "Searchable Hotel",
                "owner_id": self.partner_owner.id,
                "website_id": self.website.id,
                "is_published": True,
                "website_published": True,
                "city": "Boston",
                "property_type": "hotel",
                "no_of_guests": 8,
            }
        )
        accommodation_type = self.env["pms.accommodation.type"].create(
            {
                "name": "Double",
                "property_id": hotel.id,
                "capacity": 2,
            }
        )
        for room_name in ("Search Room 1", "Search Room 2"):
            self.env["pms.room"].create(
                {
                    "name": room_name,
                    "property_id": hotel.id,
                    "type_id": self.env.ref("pms_base.pms_room_type_bed").id,
                    "accommodation_type_id": accommodation_type.id,
                }
            )
        hotel.amenity_ids = [
            (
                6,
                0,
                [
                    self.env.ref("pms_base.pms_amenity_pets_allowed").id,
                    self.env.ref("pms_base.pms_amenity_dedicated_workspace").id,
                ],
            )
        ]
        self.authenticate(None, None)

        response = self.url_open(
            "/property?adults=2&children=2&rooms=2&guest_select=4&work=1&pets=1"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Searchable Hotel", response.content)
        self.assertIn(b"2 adultos", response.content)
        self.assertIn(b"2 ni\xc3\xb1os", response.content)
        self.assertIn(b"2 habitaciones", response.content)
        self.assertIn(b'name="work" value="1"', response.content)
        self.assertIn(b'name="pets" value="1"', response.content)

        too_many_rooms = self.url_open(
            "/property?adults=2&children=2&rooms=3&guest_select=4"
        )
        self.assertNotIn(b"Searchable Hotel", too_many_rooms.content)

    def test_check_availability_missing_dates(self):
        self.authenticate(None, None)
        response = self._jsonrpc(
            f"/property/{self.property.id}/check_availability",
            {"date_start": "", "date_end": ""},
        )
        result = response.json()["result"]
        self.assertFalse(result["available"])
        self.assertEqual(result["error"], "Missing dates")

    def test_check_availability_invalid_dates(self):
        self.authenticate(None, None)
        response = self._jsonrpc(
            f"/property/{self.property.id}/check_availability",
            {"date_start": "invalid", "date_end": "2025-01-01"},
        )
        result = response.json()["result"]
        self.assertFalse(result["available"])
        self.assertEqual(result["error"], "Invalid dates")

    def test_add_to_cart_invalid_dates(self):
        self.authenticate("admin", "admin")
        response = self._jsonrpc(
            f"/property/{self.property.id}/add_to_cart",
            {
                "date_start": "bad-date",
                "date_end": self.dates_cart[1],
                "reservation_type_id": self.reservation_type.id,
                "guests": [{"name": "Guest"}],
            },
        )
        result = response.json()["result"]
        self.assertEqual(result["error"], "Invalid dates")

    def test_add_to_cart_invalid_reservation_type(self):
        self.authenticate("admin", "admin")
        response = self._jsonrpc(
            f"/property/{self.property.id}/add_to_cart",
            {
                "date_start": self.dates_cart[0],
                "date_end": self.dates_cart[1],
                "reservation_type_id": 0,
                "guests": [{"name": "Guest"}],
            },
        )
        result = response.json()["result"]
        self.assertEqual(result["error"], "Invalid reservation type")

    def test_add_to_cart_no_guests(self):
        self.authenticate("admin", "admin")
        response = self._jsonrpc(
            f"/property/{self.property.id}/add_to_cart",
            {
                "date_start": self.dates_cart[0],
                "date_end": self.dates_cart[1],
                "reservation_type_id": self.reservation_type.id,
                "guests": [{"name": "   "}],
            },
        )
        result = response.json()["result"]
        self.assertEqual(result["error"], "At least one guest is required")

    def test_add_to_cart_property_not_found(self):
        self.authenticate("admin", "admin")
        response = self._jsonrpc(
            "/property/999999/add_to_cart",
            {
                "date_start": self.dates_cart[0],
                "date_end": self.dates_cart[1],
                "reservation_type_id": self.reservation_type.id,
                "guests": [{"name": "Guest"}],
            },
        )
        result = response.json()["result"]
        self.assertEqual(result["error"], "Property not found")
        self.assertEqual(result["redirect"], "/property")

    def test_property_detail_includes_reservation_types(self):
        self.authenticate("admin", "admin")
        slug = self.env["ir.http"]._slug(self.property)
        response = self.url_open(f"/property/{slug}")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Nightly Rate", response.content)
        self.assertIn(b"Global Rate", response.content)

    def test_hotel_uses_general_rates_for_types_without_a_specific_rate(self):
        self.property.property_type = "hotel"
        accommodation_type = self.env["pms.accommodation.type"].create(
            {
                "name": "Double Room",
                "property_id": self.property.id,
                "capacity": 2,
            }
        )
        self.env["pms.room"].create(
            {
                "name": "Room 201",
                "property_id": self.property.id,
                "type_id": self.env.ref("pms_base.pms_room_type_bed").id,
                "accommodation_type_id": accommodation_type.id,
            }
        )
        self.authenticate("admin", "admin")
        slug = self.env["ir.http"]._slug(self.property)
        response = self.url_open(f"/property/{slug}")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Double Room - Nightly Rate", response.content)
        self.assertIn(b"Double Room - Global Rate", response.content)
        self.assertIn(b"tarifa general", response.content)
