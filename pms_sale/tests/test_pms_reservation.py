# Copyright (c) 2022 Gray Matter Logic
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestPMSReservation(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product = cls.env.ref("pms_sale.product_product_reservation")
        cls.partner_owner = cls.env["res.partner"].create({"name": "Property Owner"})
        cls.partner_property = cls.env["res.partner"].create({"name": "Property"})
        cls.property = cls.env["pms.property"].create(
            {
                "owner_id": cls.partner_owner.id,
                "partner_id": cls.partner_property.id,
                "checkin": 12.0,
                "checkout": 15.0,
            }
        )
        cls.property_reservation = cls.env["pms.property.reservation"].create(
            {
                "name": "PMS property reservation 1",
                "product_id": cls.product.id,
                "property_id": cls.property.id,
            }
        )
        cls.property.write(
            {
                "name": "Property",
                "ref": "test ref",
                "city": "la",
                "no_of_guests": 4,
                "min_nights": 1,
                "max_nights": 30,
                "reservation_ids": [
                    (
                        0,
                        0,
                        {
                            "name": cls.property_reservation.name,
                            "product_id": cls.product.id,
                            "property_id": cls.property.id,
                        },
                    )
                ],
            }
        )
        cls.reservation = cls.env["pms.reservation"].create(
            {
                "name": "Test Reservation",
                "property_id": cls.property.id,
                "start": "2022-06-01",
                "stop": "2022-06-15",
            }
        )

    def test_read_group_stage_ids(self):
        stages = self.env["pms.stage"]
        stages = self.reservation._read_group_stage_ids(stages, [])
        self.assertEqual(len(stages), 6)

    def test_onchange_property_id(self):
        self.reservation.onchange_property_id()
        self.assertEqual(
            self.reservation.start.strftime("%m/%d/%Y %H:%M"), "06/01/2022 12:00"
        )
        self.assertEqual(
            self.reservation.stop.strftime("%m/%d/%Y %H:%M"), "06/15/2022 15:00"
        )

    def test_check_max_no_of_guests(self):
        self.reservation._check_max_no_of_guests()

    def test_check_no_of_reservations(self):
        self.reservation._check_no_of_reservations()

    def test_check_no_of_nights(self):
        self.reservation._check_no_of_nights()

    def test_action_book(self):
        self.reservation.action_book()
        self.assertEqual(
            self.reservation.stage_id.id,
            self.env.ref("pms_sale.pms_stage_booked", raise_if_not_found=False).id,
        )

    def test_action_confirm(self):
        self.reservation.action_confirm()
        self.assertEqual(
            self.reservation.stage_id.id,
            self.env.ref("pms_sale.pms_stage_confirmed", raise_if_not_found=False).id,
        )

    def test_action_check_in(self):
        self.reservation.action_check_in()
        self.assertEqual(
            self.reservation.stage_id.id,
            self.env.ref("pms_sale.pms_stage_checked_in", raise_if_not_found=False).id,
        )

    def test_action_check_out(self):
        self.reservation.action_check_out()
        self.assertEqual(
            self.reservation.stage_id.id,
            self.env.ref("pms_sale.pms_stage_checked_out", raise_if_not_found=False).id,
        )

    def test_action_cancel(self):
        self.reservation.action_cancel()
        self.assertEqual(
            self.reservation.stage_id.id,
            self.env.ref("pms_sale.pms_stage_cancelled", raise_if_not_found=False).id,
        )

    def test_action_view_invoices(self):
        self.reservation.action_view_invoices()

    def test_accommodation_type_availability_uses_room_inventory(self):
        accommodation_type = self.env["pms.accommodation.type"].create(
            {
                "name": "Double Test",
                "property_id": self.property.id,
                "capacity": 2,
            }
        )
        room_values = {
            "property_id": self.property.id,
            "type_id": self.env.ref("pms_base.pms_room_type_bed").id,
            "accommodation_type_id": accommodation_type.id,
        }
        self.env["pms.room"].create(dict(room_values, name="Double 1"))
        self.env["pms.room"].create(dict(room_values, name="Double 2"))
        booking_values = {
            "property_id": self.property.id,
            "accommodation_type_id": accommodation_type.id,
            "start": "2030-06-01 15:00:00",
            "stop": "2030-06-03 11:00:00",
        }

        self.assertTrue(
            self.env["pms.reservation"].is_accommodation_type_available(
                self.property.id,
                accommodation_type.id,
                "2030-06-01 15:00:00",
                "2030-06-03 11:00:00",
            )
        )
        self.env["pms.reservation"].create(booking_values)
        self.assertTrue(
            self.env["pms.reservation"].is_accommodation_type_available(
                self.property.id,
                accommodation_type.id,
                "2030-06-01 15:00:00",
                "2030-06-03 11:00:00",
            )
        )
        self.env["pms.reservation"].create(booking_values)
        self.assertFalse(
            self.env["pms.reservation"].is_accommodation_type_available(
                self.property.id,
                accommodation_type.id,
                "2030-06-01 15:00:00",
                "2030-06-03 11:00:00",
            )
        )

    def test_accommodation_type_rejects_booking_beyond_room_inventory(self):
        accommodation_type = self.env["pms.accommodation.type"].create(
            {"name": "Single Test", "property_id": self.property.id}
        )
        self.env["pms.room"].create(
            {
                "name": "Single 1",
                "property_id": self.property.id,
                "type_id": self.env.ref("pms_base.pms_room_type_bed").id,
                "accommodation_type_id": accommodation_type.id,
            }
        )
        booking_values = {
            "property_id": self.property.id,
            "accommodation_type_id": accommodation_type.id,
            "start": "2030-06-01 15:00:00",
            "stop": "2030-06-03 11:00:00",
        }
        self.env["pms.reservation"].create(booking_values)

        with self.assertRaises(ValidationError):
            with self.env.cr.savepoint():
                self.env["pms.reservation"].create(booking_values)

    def test_inactive_accommodation_type_is_unavailable(self):
        accommodation_type = self.env["pms.accommodation.type"].create(
            {
                "name": "Inactive Test",
                "property_id": self.property.id,
                "active": False,
            }
        )
        self.env["pms.room"].create(
            {
                "name": "Inactive Room",
                "property_id": self.property.id,
                "type_id": self.env.ref("pms_base.pms_room_type_bed").id,
                "accommodation_type_id": accommodation_type.id,
            }
        )

        self.assertFalse(
            self.env["pms.reservation"].is_accommodation_type_available(
                self.property.id,
                accommodation_type.id,
                "2030-06-01 15:00:00",
                "2030-06-03 11:00:00",
            )
        )
