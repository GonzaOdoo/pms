# Copyright (c) 2026
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
from psycopg2 import IntegrityError

from odoo.exceptions import ValidationError
from odoo.tests.common import mute_logger

from .common import PmsBaseCase


class TestPmsAccommodationType(PmsBaseCase):
    def test_create_accommodation_type_and_assign_rooms(self):
        accommodation_type = self.env["pms.accommodation.type"].create(
            {
                "name": "Double Standard",
                "property_id": self.property.id,
                "capacity": 2,
                "bedroom_count": 1,
                "bathroom_count": 1,
                "area": 24.0,
            }
        )
        amenity = self.env["pms.amenity"].create({"name": "Private bathroom"})
        accommodation_type.amenity_ids = [(4, amenity.id)]
        room = self.env["pms.room"].create(
            {
                "name": "201",
                "property_id": self.property.id,
                "type_id": self.room_type_bed.id,
                "accommodation_type_id": accommodation_type.id,
                "capacity": 2,
                "floor": 2,
                "amenity_ids": [(4, amenity.id)],
            }
        )

        self.assertEqual(accommodation_type.room_count, 1)
        self.assertIn(amenity, accommodation_type.amenity_ids)
        self.assertEqual(room.accommodation_type_id, accommodation_type)
        self.assertEqual(room.floor, 2)
        self.assertIn(amenity, room.amenity_ids)

    def test_room_type_must_belong_to_same_property(self):
        other_property = self.env["pms.property"].create(
            {"name": "Other Property", "owner_id": self.owner.id, "tz": "UTC"}
        )
        accommodation_type = self.env["pms.accommodation.type"].create(
            {"name": "Double", "property_id": other_property.id}
        )

        with self.assertRaises(ValidationError):
            self.env["pms.room"].create(
                {
                    "name": "202",
                    "property_id": self.property.id,
                    "type_id": self.room_type_bed.id,
                    "accommodation_type_id": accommodation_type.id,
                }
            )

    def test_accommodation_type_cannot_move_while_rooms_are_assigned(self):
        other_property = self.env["pms.property"].create(
            {"name": "Other Property", "owner_id": self.owner.id, "tz": "UTC"}
        )
        accommodation_type = self.env["pms.accommodation.type"].create(
            {"name": "Double", "property_id": self.property.id}
        )
        self.env["pms.room"].create(
            {
                "name": "203",
                "property_id": self.property.id,
                "type_id": self.room_type_bed.id,
                "accommodation_type_id": accommodation_type.id,
            }
        )

        with self.assertRaises(ValidationError):
            with self.env.cr.savepoint():
                accommodation_type.property_id = other_property

    def test_accommodation_type_name_unique_per_property(self):
        self.env["pms.accommodation.type"].create(
            {"name": "Double", "property_id": self.property.id}
        )
        with mute_logger("odoo.sql_db"), self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                self.env["pms.accommodation.type"].create(
                    {"name": "Double", "property_id": self.property.id}
                )
