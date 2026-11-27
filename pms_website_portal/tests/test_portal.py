from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestProviderPortal(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        group = env.ref("pms_website_portal.group_provider")
        portal = env.ref("base.group_portal")
        cls.rtype = env["pms.room.type"].create({"name": "Doble"})
        cls.mutual = {}
        for key in ("a", "b"):
            partner = env["res.partner"].create({"name": f"Mutual {key.upper()}"})
            user = env["res.users"].with_context(no_reset_password=True).create({
                "name": f"Operador {key.upper()}", "login": f"op_{key}", "password": f"op_{key}",
                "partner_id": partner.id, "group_ids": [(6, 0, [portal.id, group.id])],
            })
            prop = env["pms.property"].create({
                "name": f"Hotel {key.upper()}", "owner_id": partner.id,
                "company_id": env.company.id, "tz": "UTC", "max_nights": 30,
            })
            room = env["pms.room"].create({"name": f"Hab {key.upper()}1", "property_id": prop.id, "type_id": cls.rtype.id})
            res = env["pms.reservation"].create({
                "property_id": prop.id,
                "partner_id": env["res.partner"].create({"name": f"Cliente {key}"}).id,
                "start": "2030-01-10 12:00:00", "stop": "2030-01-12 10:00:00",
            })
            cls.mutual[key] = {"user": user, "partner": partner, "prop": prop, "room": room, "res": res}
        # portal común (no proveedor)
        cls.client_user = env["res.users"].with_context(no_reset_password=True).create({
            "name": "Cliente", "login": "cli", "password": "cli",
            "group_ids": [(6, 0, [portal.id])],
        })

    def _get(self, path, login="op_a"):
        self.authenticate(login, login)
        return self.url_open(path)

    def _post(self, path, data, login="op_a"):
        self.authenticate(login, login)
        data = dict(data, csrf_token=self.csrf_token())
        return self.url_open(path, data=data, allow_redirects=False)

    def _start_wizard(self, name, property_type, login="op_a"):
        response = self._post(
            "/my/properties/wizard/start",
            {"name": name, "property_type": property_type},
            login=login,
        )
        self.assertEqual(response.status_code, 303)
        property_id = int(
            response.headers["Location"]
            .split("/my/properties/")[1]
            .split("/")[0]
        )
        return self.env["pms.property"].browse(property_id)

    def test_wizard_draft_can_be_resumed_and_is_private(self):
        own_draft = self._start_wizard("Borrador A", "house")
        self.assertEqual(
            self._get(f"/my/properties/{own_draft.id}/wizard/address").status_code,
            200,
        )
        foreign_draft = self._start_wizard("Borrador B", "hotel", login="op_b")
        self.assertEqual(
            self._get(f"/my/properties/{foreign_draft.id}/wizard/address").status_code,
            404,
        )

    def test_wizard_property_photos_step_is_optional(self):
        prop = self._start_wizard("Propiedad con fotos", "house")
        self._post(
            f"/my/properties/{prop.id}/wizard/address/save",
            {"street": "Calle 1", "city": "Salta"},
        )
        response = self._get(f"/my/properties/{prop.id}/wizard/photos")
        self.assertEqual(response.status_code, 200)
        self.assertIn('name="images"', response.text)
        self.assertIn('enctype="multipart/form-data"', response.text)

        response = self._post(f"/my/properties/{prop.id}/wizard/photos/save", {})
        self.assertEqual(response.status_code, 303)
        prop.invalidate_recordset()
        self.assertEqual(prop.setup_step, "amenities")

    def test_dashboard_replaces_portal_for_provider(self):
        r = self._get("/my")
        self.assertEqual(r.status_code, 200)
        self.assertIn("ts-app", r.text)
        self.assertIn("Hotel A", r.text + self._get("/my/properties").text)

    def test_non_provider_keeps_default_portal(self):
        r = self._get("/my", login="cli")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("ts-app", r.text)

    def test_isolation_between_mutuals(self):
        a, b = self.mutual["a"], self.mutual["b"]
        listing = self._get("/my/properties").text
        self.assertIn("Hotel A", listing)
        self.assertNotIn("Hotel B", listing)
        self.assertEqual(self._get(f"/my/properties/{b['prop'].id}").status_code, 404)
        self.assertEqual(self._get(f"/my/rooms/{b['room'].id}").status_code, 404)
        self.assertEqual(self._get(f"/my/reservations/{b['res'].id}").status_code, 404)
        self.assertEqual(self._get(f"/my/reservations/{a['res'].id}").status_code, 200)
        self.assertNotIn("Cliente b", self._get("/my/reservations").text)

    def test_create_property_forces_owner(self):
        prop = self._start_wizard("Cabaña Nueva", "house")
        self.assertEqual(prop.setup_state, "draft")
        self.assertFalse(prop.is_published)
        self._post(
            f"/my/properties/{prop.id}/wizard/address/save",
            {"street": "Calle 1", "city": "Salta"},
        )
        self._post(f"/my/properties/{prop.id}/wizard/photos/save", {})
        self._post(
            f"/my/properties/{prop.id}/wizard/amenities/save",
            {
                "area": "55,5",
                "no_of_guests": "4",
                "min_nights": "1",
                "max_nights": "30",
            },
        )
        self._post(
            f"/my/properties/{prop.id}/wizard/inventory/save",
            {"bedroom_count": "2", "bathroom_count": "1"},
        )
        self._post(
            f"/my/properties/{prop.id}/wizard/rate/save",
            {"reservation_name": "Tarifa estándar", "price": "120"},
        )
        self._post(f"/my/properties/{prop.id}/wizard/complete", {})
        prop.invalidate_recordset()
        self.assertEqual(prop.owner_id, self.mutual["a"]["partner"])
        self.assertEqual(prop.area, 55.5)
        self.assertEqual(prop.max_nights, 30)
        self.assertEqual(prop.property_type, "house")
        self.assertEqual(prop.setup_state, "ready")
        self.assertFalse(prop.accommodation_type_ids)
        self.assertFalse(prop.reservation_ids.accommodation_type_id)

    def test_hotel_wizard_creates_type_then_rooms_and_rate(self):
        prop = self._start_wizard("Hotel Nuevo", "hotel")
        self._post(
            f"/my/properties/{prop.id}/wizard/address/save",
            {"street": "Calle 2", "city": "Salta"},
        )
        self._post(f"/my/properties/{prop.id}/wizard/photos/save", {})
        self._post(
            f"/my/properties/{prop.id}/wizard/amenities/save",
            {
                "area": "120",
                "no_of_guests": "30",
                "min_nights": "1",
                "max_nights": "30",
            },
        )
        inventory_page = self._get(
            f"/my/properties/{prop.id}/wizard/inventory"
        )
        self.assertEqual(inventory_page.status_code, 200)
        self.assertIn("Agregar tipo de habitación", inventory_page.text)
        type_form = self._get(
            f"/my/accommodation-types/new?property_id={prop.id}&return_wizard=1"
        )
        self.assertIn('name="quantity"', type_form.text)
        self.assertIn('name="return_wizard" value="1"', type_form.text)
        invalid_response = self._post(
            "/my/accommodation-types/save",
            {
                "property_id": prop.id,
                "return_wizard": "1",
                "name": "Sin habitaciones",
                "capacity": "2",
                "bedroom_count": "1",
                "bathroom_count": "1",
                "area": "25",
                "quantity": "0",
            },
        )
        self.assertIn(
            "return_wizard=1&msg=error",
            invalid_response.headers["Location"],
        )
        self.assertFalse(prop.accommodation_type_ids)
        type_response = self._post(
            "/my/accommodation-types/save",
            {
                "property_id": prop.id,
                "return_wizard": "1",
                "name": "Doble",
                "capacity": "2",
                "bedroom_count": "1",
                "bathroom_count": "1",
                "area": "25",
                "quantity": "2",
            },
        )
        self.assertIn(
            f"/my/properties/{prop.id}/wizard/inventory",
            type_response.headers["Location"],
        )
        prop.invalidate_recordset()
        accommodation_type = prop.accommodation_type_ids.filtered(
            lambda item: item.name == "Doble"
        )
        self.assertEqual(accommodation_type.name, "Doble")
        self.assertEqual(
            accommodation_type.room_ids.filtered("active").mapped("name"),
            ["Doble 1", "Doble 2"],
        )
        inventory_page = self._get(
            f"/my/properties/{prop.id}/wizard/inventory"
        )
        self.assertIn("Doble", inventory_page.text)
        self.assertIn("Doble 1", self._get("/my/rooms?property_id=%s" % prop.id).text)
        second_type_response = self._post(
            "/my/accommodation-types/save",
            {
                "property_id": prop.id,
                "return_wizard": "1",
                "name": "Suite",
                "capacity": "3",
                "bedroom_count": "1",
                "bathroom_count": "1",
                "area": "35",
                "quantity": "1",
            },
        )
        self.assertIn(
            f"/my/properties/{prop.id}/wizard/inventory",
            second_type_response.headers["Location"],
        )
        prop.invalidate_recordset()
        self.assertEqual(
            len(prop.accommodation_type_ids.filtered("active")),
            2,
        )
        self.assertEqual(
            len(prop.room_ids.filtered("active")),
            3,
        )
        self._post(
            f"/my/properties/{prop.id}/wizard/inventory/save",
            {"inventory_action": "continue"},
        )
        self._post(
            f"/my/properties/{prop.id}/wizard/rate/save",
            {"reservation_name": "Tarifa doble", "price": "150"},
        )
        self._post(f"/my/properties/{prop.id}/wizard/complete", {})
        prop.invalidate_recordset()
        self.assertEqual(prop.setup_state, "ready")
        self.assertEqual(prop.property_type, "hotel")
        self.assertEqual(len(accommodation_type.room_ids.filtered("active")), 2)
        self.assertEqual(accommodation_type.room_ids.mapped("capacity"), [2, 2])
        self.assertEqual(accommodation_type.room_ids.mapped("area"), [25, 25])
        self.assertEqual(
            prop.reservation_ids.filtered(
                lambda offer: offer.accommodation_type_id == accommodation_type
            ).price,
            150,
        )

    def test_accommodation_type_creation_has_optional_rate_and_inherits_to_rooms(self):
        prop = self._start_wizard("Hotel Tipo", "hotel")
        amenity = self.env["pms.amenity"].create({"name": "Baño privado"})
        response = self._post(
            "/my/accommodation-types/save",
            {
                "property_id": prop.id,
                "name": "Suite",
                "capacity": "3",
                "bedroom_count": "2",
                "bathroom_count": "1",
                "area": "40",
                "quantity": "1",
                "amenity_ids": [str(amenity.id)],
            },
        )
        self.assertEqual(response.status_code, 303)
        accommodation_type = self.env["pms.accommodation.type"].search(
            [("property_id", "=", prop.id)]
        )
        self.assertFalse(
            prop.reservation_ids.filtered(
                lambda offer: offer.accommodation_type_id == accommodation_type
            )
        )
        room = self.env["pms.room"].search([("name", "=", "Suite 1")])
        self.assertEqual(room.accommodation_type_id, accommodation_type)
        self.assertEqual(room.capacity, 3)
        self.assertEqual(room.area, 40)
        self.assertIn(amenity, room.amenity_ids)

    def test_cannot_edit_or_room_into_foreign_property(self):
        b = self.mutual["b"]
        r = self._post("/my/properties/save", {"property_id": b["prop"].id, "name": "Hackeado"})
        self.assertEqual(r.status_code, 404)
        self.assertEqual(b["prop"].name, "Hotel B")
        r = self._post("/my/rooms/save", {"name": "Intrusa", "property_id": b["prop"].id, "type_id": self.rtype.id})
        self.assertEqual(r.headers["Location"].split("?")[0].rsplit("/", 1)[-1], "rooms")
        self.assertFalse(self.env["pms.room"].search([("name", "=", "Intrusa")]))

    def test_room_create(self):
        a = self.mutual["a"]
        r = self._post("/my/rooms/save", {"name": "Suite", "property_id": a["prop"].id, "type_id": self.rtype.id, "capacity": "4"})
        self.assertEqual(r.status_code, 303)
        room = self.env["pms.room"].search([("name", "=", "Suite")])
        self.assertEqual((room.property_id, room.capacity), (a["prop"], 4))

    def test_reservation_actions(self):
        a, b = self.mutual["a"], self.mutual["b"]
        r = self._post(f"/my/reservations/{a['res'].id}/book", {})
        self.assertEqual(r.status_code, 303)
        self.assertEqual(a["res"].stage_id, self.env.ref("pms_sale.pms_stage_booked"))
        self.assertEqual(self._post(f"/my/reservations/{b['res'].id}/cancel", {}).status_code, 404)
        self.assertEqual(self._post(f"/my/reservations/{a['res'].id}/borrar", {}).status_code, 404)
        self.assertNotEqual(b["res"].stage_id, self.env.ref("pms_sale.pms_stage_cancelled"))
