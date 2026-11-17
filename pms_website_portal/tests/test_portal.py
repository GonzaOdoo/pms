from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestProviderPortal(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        group = env.ref("ts_provider_portal.group_provider")
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
        r = self._post("/my/properties/save", {"name": "Cabaña Nueva", "city": "Salta", "area": "55,5"})
        self.assertEqual(r.status_code, 303)
        prop = self.env["pms.property"].search([("name", "=", "Cabaña Nueva")])
        self.assertEqual(prop.owner_id, self.mutual["a"]["partner"])
        self.assertEqual(prop.area, 55.5)
        self.assertEqual(prop.max_nights, 30)

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
