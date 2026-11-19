# Copyright (c) 2026
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
from .common import PmsBaseCase


class TestPmsAmenity(PmsBaseCase):
    def test_standard_amenities_are_available_without_demo_data(self):
        amenity_ids = (
            "demo_amenity_wifi",
            "demo_amenity_tv",
            "demo_amenity_shampoo",
            "demo_amenity_towels",
            "demo_amenity_microwave",
            "demo_amenity_coffee",
            "pms_amenity_bed_linens",
            "pms_amenity_private_bathroom",
            "pms_amenity_kitchen",
            "pms_amenity_washer",
            "pms_amenity_free_parking",
            "pms_amenity_pets_allowed",
            "pms_amenity_air_conditioning",
            "pms_amenity_pool",
            "pms_amenity_balcony",
            "pms_amenity_crib",
            "pms_amenity_smoke_alarm",
            "pms_amenity_elevator",
        )
        amenities = self.env["pms.amenity"].browse(
            [self.env.ref(f"pms_base.{xml_id}").id for xml_id in amenity_ids]
        )

        self.assertEqual(len(amenities), len(amenity_ids))
        self.assertTrue(all(amenities.mapped("active")))
        self.assertTrue(all(amenities.mapped("default_code")))
        self.assertEqual(
            self.env.ref("pms_base.pms_amenity_air_conditioning").type_id,
            self.env.ref("pms_base.pms_amenity_type_6"),
        )
