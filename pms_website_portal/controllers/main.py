import logging
import math
from datetime import timedelta

from odoo import fields, http
from odoo.exceptions import AccessError
from odoo.http import request

from odoo.addons.portal.controllers.portal import CustomerPortal

_logger = logging.getLogger(__name__)
GROUP = "pms_website_portal.group_provider"
WIZARD_STEPS = ("address", "amenities", "inventory", "rate", "review")

# Acciones de reserva que el proveedor puede disparar desde el panel.
RESERVATION_ACTIONS = {
    "book": ("action_book", "Reserva marcada como reservada"),
    "confirm": ("action_confirm", "Reserva confirmada"),
    "check_in": ("action_check_in", "Check-in registrado"),
    "check_out": ("action_check_out", "Check-out registrado"),
    "cancel": ("action_cancel", "Reserva cancelada"),
}
FLASH = {
    "saved": "Cambios guardados",
    "created": "Registro creado",
    "completed": "La propiedad quedó configurada y lista para revisión.",
    "error": "Revisá los datos: falta un campo obligatorio o hay un valor inválido",
    "rate_in_use": "No se puede quitar una tarifa que ya está asociada a reservas.",
}


def _is_provider():
    return True


def _to_float(value):
    if value in (None, ""):
        return 0.0
    try:
        result = float(str(value).replace(",", "."))
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _to_int(value):
    if value in (None, ""):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class ProviderPortalHome(CustomerPortal):
    """Reemplaza /my por el panel del proveedor.

    Los usuarios portal que no son proveedores siguen viendo el portal
    estándar. Para reemplazarlo para todos, quitar el chequeo `_is_provider`.
    """

    @http.route(
        ["/my", "/my/home"], type="http", auth="user", website=True, readonly=True
    )
    def home(self, **kw):
        _logger.info("Probando controlador!")
        if not _is_provider():
            return super().home(**kw)
        return ProviderPanel()._dashboard()


class ProviderPanel(http.Controller):
    # ---------------------------------------------------------------- helpers
    def _values(self, active, title, **extra):
        values = {
            "ts_active": active,
            "ts_title": title,
            "ts_msg": FLASH.get(request.params.get("msg")),
            "ts_fullscreen": False,
        }
        values.update(extra)
        return values

    def _own(self, model, record_id, operation="read"):
        """Devuelve el registro solo si ir.access deja al usuario operar
        sobre él (el aislamiento entre mutuales lo da ir.access, no este código).

        Para pms.property se usa "read": al heredar de res.partner (_inherits),
        Odoo 20 exige también permiso de escritura sobre res.partner, que el
        proveedor no tiene. La lectura ya está limitada a sus propiedades."""
        record = request.env[model].browse(record_id).exists()
        if not record:
            return None
        try:
            record.check_access(operation)
        except AccessError:
            return None
        return record

    def _redirect(self, path, msg):
        return request.redirect(f"{path}?msg={msg}")

    def _wizard_path(self, prop, step=None):
        return f"/my/properties/{prop.id}/wizard/{step or prop.setup_step}"

    def _provider_properties(self):
        return request.env["pms.property"].sudo().search(
            [("owner_id", "child_of", request.env.user.commercial_partner_id.id)],
            order="name",
        )

    def _wizard_property(self, property_id, step):
        if step not in WIZARD_STEPS:
            return None
        prop = self._own("pms.property", property_id)
        if not prop or prop.setup_state != "draft":
            return None
        return prop

    def _wizard_values(self, prop, step, **extra):
        current_index = WIZARD_STEPS.index(prop.setup_step or WIZARD_STEPS[0])
        values = self._values(
            "properties",
            "Configurar propiedad",
            ts_fullscreen=True,
            prop=prop,
            wizard_step=step,
            wizard_steps=[
                {
                    "key": key,
                    "label": label,
                    "url": self._wizard_path(prop, key),
                    "active": key == step,
                    "complete": index < current_index,
                    "disabled": index > current_index,
                }
                for index, (key, label) in enumerate(
                    zip(
                        WIZARD_STEPS,
                        (
                            "Dirección",
                            "Servicios",
                            "Habitaciones",
                            "Tarifas",
                            "Revisión",
                        ),
                    )
                )
            ],
        )
        values.update(extra)
        return values

    # -------------------------------------------------------------- dashboard
    def _dashboard(self):
        env = request.env
        Reservation = env["pms.reservation"].sudo()
        today = fields.Datetime.now()
        open_domain = [("stage_id.is_closed", "=", False)]
        pending = Reservation.search_count(
            open_domain + [("stage_id.sequence", "<=", 20)]
        )
        soon = Reservation.search_count(
            open_domain
            + [("start", ">=", today), ("start", "<=", today + timedelta(days=7))]
        )
        values = self._values(
            "dashboard",
            "Panel",
            n_properties=env["pms.property"].search_count([]),
            n_rooms=env["pms.room"].search_count([]),
            n_pending=pending,
            n_soon=soon,
            upcoming=Reservation.search(open_domain, limit=8),
        )
        return request.render("pms_website_portal.page_dashboard", values)

    # ------------------------------------------------------------- propiedades
    @http.route("/my/properties", type="http", auth="user", website=True)
    def properties(self, q="", **kw):
        if not _is_provider():
            return request.not_found()
    
        partner = request.env.user.commercial_partner_id

        domain = [("owner_id", "child_of", partner.id)]
    
        if q:
            domain.append(("name", "ilike", q))
    
        props = request.env["pms.property"].sudo().search(
            domain, order="id desc", limit=80
        )
    
        return request.render(
            "pms_website_portal.page_properties",
            self._values("properties", "Propiedades", properties=props, q=q),
        )
        
    @http.route("/my/properties/new", type="http", auth="user", website=True)
    def property_new(self, **kw):
        if not _is_provider():
            return request.not_found()
        return request.render(
            "pms_website_portal.page_property_wizard_type",
            self._values(
                "properties", "Nueva propiedad", ts_fullscreen=True
            ),
        )

    @http.route(
        "/my/properties/wizard/start",
        type="http",
        auth="user",
        website=True,
        methods=["POST"],
    )
    def property_wizard_start(self, **post):
        if not _is_provider():
            return request.not_found()
        name = (post.get("name") or "").strip()
        property_type = post.get("property_type")
        if not name or property_type not in ("house", "hotel", "camping"):
            return self._redirect("/my/properties/new", "error")
        user = request.env.user
        prop = request.env["pms.property"].sudo().create(
            {
                "name": name,
                "owner_id": user.commercial_partner_id.id,
                "company_id": request.env.company.id,
                "tz": user.tz or "America/Argentina/Buenos_Aires",
                "property_type": property_type,
                "setup_state": "draft",
                "setup_step": "address",
                "max_nights": 30,
                "is_published": False,
            }
        )
        return request.redirect(self._wizard_path(prop))

    @http.route(
        "/my/properties/<int:property_id>/wizard/<string:step>",
        type="http",
        auth="user",
        website=True,
    )
    def property_wizard_step(self, property_id, step, **kw):
        if not _is_provider():
            return request.not_found()
        prop = self._wizard_property(property_id, step)
        if not prop:
            return request.not_found()
        current_index = WIZARD_STEPS.index(prop.setup_step or WIZARD_STEPS[0])
        if WIZARD_STEPS.index(step) > current_index:
            return request.redirect(self._wizard_path(prop))
        accommodation_type = prop.sudo().accommodation_type_ids[:1]
        values = self._wizard_values(
            prop,
            step,
            accommodation_type=accommodation_type,
            accommodation_types=prop.sudo().accommodation_type_ids
            if prop.property_type == "hotel"
            else request.env["pms.accommodation.type"],
            reservation_offer=prop.reservation_ids.filtered(
                lambda offer: (
                    offer.accommodation_type_id
                    == accommodation_type
                    if prop.property_type == "hotel"
                    else not offer.accommodation_type_id
                )
            )[:1],
        )
        if step == "amenities":
            values["amenities"] = request.env["pms.amenity"].search(
                [("active", "=", True)], order="name"
            )
        elif step == "inventory" and prop.property_type == "hotel":
            values["room_amenities"] = request.env["pms.amenity"].search(
                [("active", "=", True)], order="name"
            )
            values["accommodation_types"] = prop.sudo().accommodation_type_ids
        return request.render(
            "pms_website_portal.page_property_wizard_step",
            values,
        )

    @http.route(
        "/my/properties/<int:property_id>/wizard/<string:step>/save",
        type="http",
        auth="user",
        website=True,
        methods=["POST"],
    )
    def property_wizard_save(self, property_id, step, **post):
        _logger.info("Start save!")
        if not _is_provider():
            return request.not_found()
        prop = self._wizard_property(property_id, step)
        if not prop:
            return request.not_found()
        current_index = WIZARD_STEPS.index(prop.setup_step or WIZARD_STEPS[0])
        step_index = WIZARD_STEPS.index(step)
        if step_index > current_index:
            return request.redirect(self._wizard_path(prop))
        vals = {}
        if step == "address":
            _logger.info("Step address")
            vals = {
                "street": (post.get("street") or "").strip(),
                "street2": (post.get("street2") or "").strip(),
                "city": (post.get("city") or "").strip(),
                "zip": (post.get("zip") or "").strip(),
            }
            _logger.info(vals)
            if not vals["street"] or not vals["city"]:
                return self._redirect(self._wizard_path(prop, step), "error")
        elif step == "amenities":
            area = _to_float(post.get("area"))
            no_of_guests = _to_int(post.get("no_of_guests"))
            min_nights = _to_int(post.get("min_nights"))
            max_nights = _to_int(post.get("max_nights"))
            max_nights = 30 if max_nights in (None, 0) else max_nights
            if (
                area is None
                or no_of_guests is None
                or min_nights is None
                or area < 0
                or no_of_guests <= 0
                or min_nights < 0
                or max_nights < 1
                or min_nights > max_nights
            ):
                return self._redirect(self._wizard_path(prop, step), "error")
            vals = {
                "area": area,
                "no_of_guests": no_of_guests,
                "min_nights": min_nights,
                "max_nights": max_nights,
                "amenity_ids": [
                    (
                        6,
                        0,
                        request.env["pms.amenity"]
                        .sudo()
                        .search(
                            [
                                ("active", "=", True),
                                (
                                    "id",
                                    "in",
                                    [
                                        _to_int(value)
                                        for value in request.httprequest.form.getlist(
                                            "amenity_ids"
                                        )
                                    ],
                                ),
                            ]
                        )
                        .ids,
                    )
                ],
            }
        elif step == "inventory":
            if prop.property_type in ("house", "camping"):
                bedroom_count = _to_int(post.get("bedroom_count"))
                bathroom_count = _to_int(post.get("bathroom_count"))
                if (
                    bedroom_count is None
                    or bathroom_count is None
                    or bedroom_count < 0
                    or bathroom_count < 0
                ):
                    return self._redirect(self._wizard_path(prop, step), "error")
                vals = {
                    "bedroom_count": bedroom_count,
                    "bathroom_count": bathroom_count,
                }
            else:
                name = (post.get("accommodation_name") or "").strip()
                capacity = _to_int(post.get("capacity"))
                bedroom_count = _to_int(post.get("bedroom_count"))
                bathroom_count = _to_int(post.get("bathroom_count"))
                area = _to_float(post.get("area"))
                if (
                    not name
                    or capacity is None
                    or bedroom_count is None
                    or bathroom_count is None
                    or area is None
                    or capacity <= 0
                    or bedroom_count < 0
                    or bathroom_count < 0
                    or area < 0
                ):
                    return self._redirect(self._wizard_path(prop, step), "error")
                amenities = request.env["pms.amenity"].sudo().search(
                    [
                        ("active", "=", True),
                        (
                            "id",
                            "in",
                            [
                                _to_int(value)
                                for value in request.httprequest.form.getlist(
                                    "room_amenity_ids"
                                )
                            ],
                        ),
                    ]
                )
                accommodation_type = prop.sudo().accommodation_type_ids[:1]
                accommodation_vals = {
                    "name": name,
                    "capacity": capacity,
                    "bedroom_count": bedroom_count,
                    "bathroom_count": bathroom_count,
                    "area": area,
                    "amenity_ids": [(6, 0, amenities.ids)],
                }
                if accommodation_type:
                    accommodation_type.write(accommodation_vals)
                else:
                    accommodation_type = request.env[
                        "pms.accommodation.type"
                    ].sudo().create(
                        dict(accommodation_vals, property_id=prop.id)
                    )
        elif step == "rate":
            name = (post.get("reservation_name") or "").strip()
            price_value = post.get("price")
            price = _to_float(price_value) if price_value not in (None, "") else None
            if (
                (price_value not in (None, "") and (price is None or price < 0))
                or (prop.property_type != "hotel" and price is None)
            ):
                return self._redirect(self._wizard_path(prop, step), "error")
            accommodation_type = (
                prop.sudo().accommodation_type_ids[:1]
                if prop.property_type == "hotel"
                else request.env["pms.accommodation.type"]
            )
            if price is not None:
                if not name:
                    return self._redirect(self._wizard_path(prop, step), "error")
                product = request.env.ref(
                    "pms_sale.product_product_reservation",
                    raise_if_not_found=False,
                )
                if not product:
                    return self._redirect(self._wizard_path(prop, step), "error")
                offer_domain = [
                    ("property_id", "=", prop.id),
                    ("accommodation_type_id", "=", accommodation_type.id or False),
                ]
                offer = request.env["pms.property.reservation"].sudo().search(
                    offer_domain, limit=1
                )
                offer_vals = {
                    "name": name,
                    "product_id": product.id,
                    "property_id": prop.id,
                    "accommodation_type_id": accommodation_type.id or False,
                    "price": price,
                }
                if offer:
                    offer.write(offer_vals)
                else:
                    request.env["pms.property.reservation"].sudo().create(offer_vals)
            elif prop.property_type == "hotel" and accommodation_type:
                offer = request.env["pms.property.reservation"].sudo().search(
                    [
                        ("property_id", "=", prop.id),
                        ("accommodation_type_id", "=", accommodation_type.id),
                    ],
                    limit=1,
                )
                if offer:
                    used_by_reservations = request.env[
                        "pms.reservation"
                    ].sudo().search_count([("reservation_type_id", "=", offer.id)])
                    if used_by_reservations:
                        return self._redirect(
                            self._wizard_path(prop, step), "rate_in_use"
                        )
                    offer.unlink()
        if vals:
            prop.sudo().write(vals)
        next_index = max(current_index, step_index + 1)
        next_step = WIZARD_STEPS[next_index]
        prop.sudo().write({"setup_step": next_step})
        return request.redirect(self._wizard_path(prop, next_step))

    @http.route(
        "/my/properties/<int:property_id>/wizard/complete",
        type="http",
        auth="user",
        website=True,
        methods=["POST"],
    )
    def property_wizard_complete(self, property_id, **post):
        if not _is_provider():
            return request.not_found()
        prop = self._own("pms.property", property_id)
        if not prop or prop.setup_state != "draft":
            return request.not_found()
        if prop.setup_step != "review" or not prop.street or not prop.city:
            return request.redirect(self._wizard_path(prop))
        if prop.property_type == "hotel":
            accommodation_types = prop.sudo().accommodation_type_ids.filtered(
                lambda item: item.active and item.room_ids.filtered("active")
            )
            if not accommodation_types:
                return request.redirect(self._wizard_path(prop, "inventory"))
        elif not prop.reservation_ids.filtered(
            lambda offer: not offer.accommodation_type_id
        ):
            return request.redirect(self._wizard_path(prop, "rate"))
        prop.sudo().write({"setup_state": "ready"})
        return request.redirect(f"/my/properties/{prop.id}?msg=completed")

    @http.route("/my/properties/<int:property_id>", type="http", auth="user", website=True)
    def property_edit(self, property_id, **kw):
        prop = self._own("pms.property", property_id) if _is_provider() else None
        if not prop:
            return request.not_found()
        if prop.setup_state == "draft":
            return request.redirect(self._wizard_path(prop))
        return request.render(
            "pms_website_portal.page_property_form",
            self._values("properties", prop.name, prop=prop),
        )

    @http.route(
        "/my/properties/save",
        type="http", auth="user", website=True, methods=["POST"],
    )
    def property_save(self, property_id=0, **post):
        if not _is_provider():
            return request.not_found()
        name = (post.get("name") or "").strip()
        max_nights = _to_int(post.get("max_nights"))
        if max_nights is None:
            return self._redirect("/my/properties", "error")
        vals = {
            "name": name,
            "street": (post.get("street") or "").strip(),
            "city": (post.get("city") or "").strip(),
            "zip": (post.get("zip") or "").strip(),
            "area": _to_float(post.get("area")),
            "no_of_guests": _to_int(post.get("no_of_guests")),
            "min_nights": _to_int(post.get("min_nights")),
            # pms_sale rechaza toda reserva si max_nights es 0 (valor por defecto)
            "max_nights": max_nights or 30,
        }
        if not name or any(value is None for value in vals.values()):
            return self._redirect("/my/properties", "error")
        property_id = _to_int(property_id)
        if property_id:
            prop = self._own("pms.property", property_id)
            if not prop:
                return request.not_found()
            # Validado con el usuario; se escribe con sudo porque la
            # propiedad delega nombre y dirección en res.partner.
            prop.sudo().write(vals)
            return self._redirect(f"/my/properties/{prop.id}", "saved")
        return request.redirect("/my/properties/new")

    # ------------------------------------------------------------ habitaciones
    @http.route("/my/accommodation-types", type="http", auth="user", website=True)
    def accommodation_types(self, property_id=0, **kw):
        if not _is_provider():
            return request.not_found()
        properties = self._provider_properties()
        property_id = _to_int(property_id)
        prop = properties.filtered(lambda item: item.id == property_id)[:1]
        domain = [("property_id", "in", properties.ids)]
        if prop:
            domain.append(("property_id", "=", prop.id))
        types = request.env["pms.accommodation.type"].sudo().search(
            domain, order="property_id, sequence, name"
        )
        return request.render(
            "pms_website_portal.page_accommodation_types",
            self._values(
                "accommodation_types",
                "Tipos de alojamiento",
                accommodation_types=types,
                properties=properties,
                filter_property=prop.id if prop else 0,
            ),
        )

    @http.route(
        "/my/accommodation-types/new",
        type="http",
        auth="user",
        website=True,
    )
    def accommodation_type_new(self, property_id=0, **kw):
        if not _is_provider():
            return request.not_found()
        properties = self._provider_properties()
        property_id = _to_int(property_id)
        prop = properties.filtered(lambda item: item.id == property_id)[:1]
        return request.render(
            "pms_website_portal.page_accommodation_type_form",
            self._values(
                "accommodation_types",
                "Nuevo tipo de alojamiento",
                accommodation_type=None,
                property=prop,
                properties=properties,
                amenities=request.env["pms.amenity"].search(
                    [("active", "=", True)], order="name"
                ),
            ),
        )

    @http.route(
        "/my/accommodation-types/save",
        type="http",
        auth="user",
        website=True,
        methods=["POST"],
    )
    def accommodation_type_save(self, **post):
        if not _is_provider():
            return request.not_found()
        prop_id = _to_int(post.get("property_id"))
        prop = self._provider_properties().filtered(
            lambda item: item.id == prop_id
        )[:1]
        name = (post.get("name") or "").strip()
        capacity = _to_int(post.get("capacity"))
        bedroom_count = _to_int(post.get("bedroom_count"))
        bathroom_count = _to_int(post.get("bathroom_count"))
        area = _to_float(post.get("area"))
        price_raw = post.get("price")
        price = _to_float(price_raw) if price_raw not in (None, "") else None
        if (
            not prop
            or not name
            or capacity is None
            or capacity < 1
            or bedroom_count is None
            or bedroom_count < 0
            or bathroom_count is None
            or bathroom_count < 0
            or area is None
            or area < 0
            or (price_raw not in (None, "") and (price is None or price < 0))
        ):
            return self._redirect("/my/accommodation-types", "error")
        if request.env["pms.accommodation.type"].sudo().search_count(
            [("property_id", "=", prop.id), ("name", "=", name)]
        ):
            return self._redirect(
                f"/my/accommodation-types?property_id={prop.id}", "error"
            )
        product = False
        if price is not None:
            product = request.env.ref(
                "pms_sale.product_product_reservation", raise_if_not_found=False
            )
            if not product:
                return self._redirect("/my/accommodation-types", "error")
        amenity_ids = [
            _to_int(value)
            for value in request.httprequest.form.getlist("amenity_ids")
        ]
        amenities = request.env["pms.amenity"].sudo().search(
            [("active", "=", True), ("id", "in", amenity_ids)]
        )
        accommodation_type = request.env["pms.accommodation.type"].sudo().create(
            {
                "name": name,
                "property_id": prop.id,
                "capacity": capacity,
                "bedroom_count": bedroom_count,
                "bathroom_count": bathroom_count,
                "area": area,
                "amenity_ids": [(6, 0, amenities.ids)],
            }
        )
        if price is not None:
            request.env["pms.property.reservation"].sudo().create(
                {
                    "name": (post.get("reservation_name") or "").strip()
                    or f"Tarifa {name}",
                    "product_id": product.id,
                    "property_id": prop.id,
                    "accommodation_type_id": accommodation_type.id,
                    "price": price,
                }
            )
        return self._redirect(
            f"/my/accommodation-types?property_id={prop.id}", "created"
        )

    @http.route("/my/rooms", type="http", auth="user", website=True)
    def rooms(self, property_id=0, **kw):
        if not _is_provider():
            return request.not_found()
        domain = []
        property_id = _to_int(property_id)
        if property_id:
            domain.append(("property_id", "=", property_id))
        rooms = request.env["pms.room"].search(domain, limit=200)
        return request.render(
            "pms_website_portal.page_rooms",
            self._values(
                "rooms", "Habitaciones", rooms=rooms,
                properties=request.env["pms.property"].search([]),
                filter_property=property_id,
            ),
        )

    @http.route("/my/rooms/new", type="http", auth="user", website=True)
    def room_new(self, **kw):
        if not _is_provider():
            return request.not_found()
        env = request.env
        properties = self._provider_properties()
        property_id = _to_int(kw.get("property_id"))
        prop = properties.filtered(lambda item: item.id == property_id)[:1]
        accommodation_types = request.env["pms.accommodation.type"].sudo().search(
            [("property_id", "=", prop.id)] if prop else [("id", "=", 0)]
        )
        selected_type_id = _to_int(kw.get("accommodation_type_id"))
        selected_type = accommodation_types.filtered(
            lambda item: item.id == selected_type_id
        )[:1]
        return request.render(
            "pms_website_portal.page_room_form",
            self._values(
                "rooms", "Nueva habitación", room=None,
                properties=properties,
                room_types=env["pms.room.type"].search([]),
                accommodation_types=accommodation_types,
                selected_accommodation_type=selected_type,
                property=prop,
            ),
        )

    @http.route("/my/rooms/<int:room_id>", type="http", auth="user", website=True)
    def room_edit(self, room_id, **kw):
        room = self._own("pms.room", room_id) if _is_provider() else None
        if not room:
            return request.not_found()
        env = request.env
        properties = self._provider_properties()
        return request.render(
            "pms_website_portal.page_room_form",
            self._values(
                "rooms", room.name, room=room,
                properties=properties,
                room_types=env["pms.room.type"].search([]),
                accommodation_types=env["pms.accommodation.type"].sudo().search(
                    [("property_id", "=", room.property_id.id)]
                ),
                property=room.property_id,
            ),
        )

    @http.route("/my/rooms/save", type="http", auth="user", website=True, methods=["POST"])
    def room_save(self, room_id=0, **post):
        if not _is_provider():
            return request.not_found()
        name = (post.get("name") or "").strip()
        prop = self._own("pms.property", _to_int(post.get("property_id")))
        room_type = request.env["pms.room.type"].browse(_to_int(post.get("type_id"))).exists()
        accommodation_type = request.env["pms.accommodation.type"].sudo().browse(
            _to_int(post.get("accommodation_type_id"))
        ).exists()
        if (
            not name
            or not prop
            or not room_type
            or (
                accommodation_type
                and accommodation_type.property_id != prop
            )
            or (prop.property_type == "hotel" and not accommodation_type)
        ):
            return self._redirect("/my/rooms", "error")
        vals = {
            "name": name,
            "property_id": prop.id,
            "type_id": room_type.id,
            "accommodation_type_id": accommodation_type.id or False,
            "capacity": accommodation_type.capacity
            if accommodation_type
            else _to_int(post.get("capacity")),
            "area": accommodation_type.area
            if accommodation_type
            else _to_float(post.get("area")),
            "amenity_ids": [(6, 0, accommodation_type.amenity_ids.ids)]
            if accommodation_type
            else False,
        }
        if vals["amenity_ids"] is False:
            vals.pop("amenity_ids")
        if any(value is None for value in vals.values()) or vals["capacity"] < 0:
            return self._redirect("/my/rooms", "error")
        room_id = _to_int(room_id)
        if room_id:
            room = self._own("pms.room", room_id, "write")
            if not room:
                return request.not_found()
            room.sudo().write(vals)
            return self._redirect(f"/my/rooms/{room.id}", "saved")
        room = request.env["pms.room"].sudo().create(vals)
        return self._redirect(f"/my/rooms/{room.id}", "created")

    # ---------------------------------------------------------------- reservas
    @http.route("/my/reservations", type="http", auth="user", website=True)
    def reservations(self, stage=0, q="", **kw):
        if not _is_provider():
            return request.not_found()
        env = request.env
        domain = []
        stage = _to_int(stage)
        if stage:
            domain.append(("stage_id", "=", stage))
        if q:
            domain.append(("name", "ilike", q))
        return request.render(
            "pms_website_portal.page_reservations",
            self._values(
                "reservations", "Administrar reservas",
                reservations=env["pms.reservation"].search(domain, limit=100),
                stages=env["pms.stage"].search([("stage_type", "=", "reservation")]),
                filter_stage=stage, q=q,
            ),
        )

    @http.route("/my/reservations/<int:reservation_id>", type="http", auth="user", website=True)
    def reservation(self, reservation_id, **kw):
        res = self._own("pms.reservation", reservation_id) if _is_provider() else None
        if not res:
            return request.not_found()
        return request.render(
            "pms_website_portal.page_reservation",
            self._values("reservations", res.name, res=res, actions=RESERVATION_ACTIONS),
        )

    @http.route(
        "/my/reservations/<int:reservation_id>/<string:action>",
        type="http", auth="user", website=True, methods=["POST"],
    )
    def reservation_action(self, reservation_id, action, **post):
        res = self._own("pms.reservation", reservation_id, "write") if _is_provider() else None
        if not res or action not in RESERVATION_ACTIONS:
            return request.not_found()
        getattr(res.sudo(), RESERVATION_ACTIONS[action][0])()
        return self._redirect(f"/my/reservations/{res.id}", "saved")
