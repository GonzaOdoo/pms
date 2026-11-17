from datetime import timedelta

from odoo import fields, http
from odoo.exceptions import AccessError
from odoo.http import request

from odoo.addons.portal.controllers.portal import CustomerPortal
import logging

_logger = logging.getLogger(__name__)
GROUP = "pms_website_portal.group_provider"

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
    "error": "Revisá los datos: falta un campo obligatorio o hay un valor inválido",
}


def _is_provider():
    return True


def _to_float(value):
    try:
        return float(str(value).replace(",", ".")) if value not in (None, "") else 0.0
    except ValueError:
        return 0.0


def _to_int(value):
    try:
        return int(value) if value not in (None, "") else 0
    except ValueError:
        return 0


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
    
        partner = request.env.user.partner_id
    
        domain = [("owner_id", "=", partner.id)]
    
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
            "pms_website_portal.page_property_form",
            self._values("properties", "Nueva propiedad", prop=None),
        )

    @http.route("/my/properties/<int:property_id>", type="http", auth="user", website=True)
    def property_edit(self, property_id, **kw):
        prop = self._own("pms.property", property_id) if _is_provider() else None
        if not prop:
            return request.not_found()
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
        vals = {
            "name": name,
            "street": (post.get("street") or "").strip(),
            "city": (post.get("city") or "").strip(),
            "zip": (post.get("zip") or "").strip(),
            "area": _to_float(post.get("area")),
            "no_of_guests": _to_int(post.get("no_of_guests")),
            "min_nights": _to_int(post.get("min_nights")),
            # pms_sale rechaza toda reserva si max_nights es 0 (valor por defecto)
            "max_nights": _to_int(post.get("max_nights")) or 30,
        }
        if not name:
            return self._redirect("/my/properties", "error")
        user = request.env.user
        property_id = _to_int(property_id)
        if property_id:
            prop = self._own("pms.property", property_id)
            if not prop:
                return request.not_found()
            # Validado con el usuario; se escribe con sudo porque la
            # propiedad delega nombre y dirección en res.partner.
            prop.sudo().write(vals)
            return self._redirect(f"/my/properties/{prop.id}", "saved")
        prop = request.env["pms.property"].sudo().create(
            dict(
                vals,
                owner_id=user.commercial_partner_id.id,
                company_id=request.env.company.id,
                tz=user.tz or "America/Argentina/Buenos_Aires",
            )
        )
        return self._redirect(f"/my/properties/{prop.id}", "created")

    # ------------------------------------------------------------ habitaciones
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
        return request.render(
            "pms_website_portal.page_room_form",
            self._values(
                "rooms", "Nueva habitación", room=None,
                properties=env["pms.property"].search([]),
                room_types=env["pms.room.type"].search([]),
            ),
        )

    @http.route("/my/rooms/<int:room_id>", type="http", auth="user", website=True)
    def room_edit(self, room_id, **kw):
        room = self._own("pms.room", room_id) if _is_provider() else None
        if not room:
            return request.not_found()
        env = request.env
        return request.render(
            "pms_website_portal.page_room_form",
            self._values(
                "rooms", room.name, room=room,
                properties=env["pms.property"].search([]),
                room_types=env["pms.room.type"].search([]),
            ),
        )

    @http.route("/my/rooms/save", type="http", auth="user", website=True, methods=["POST"])
    def room_save(self, room_id=0, **post):
        if not _is_provider():
            return request.not_found()
        name = (post.get("name") or "").strip()
        prop = self._own("pms.property", _to_int(post.get("property_id")))
        room_type = request.env["pms.room.type"].browse(_to_int(post.get("type_id"))).exists()
        if not name or not prop or not room_type:
            return self._redirect("/my/rooms", "error")
        vals = {
            "name": name,
            "property_id": prop.id,
            "type_id": room_type.id,
            "capacity": _to_int(post.get("capacity")),
            "area": _to_float(post.get("area")),
        }
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
