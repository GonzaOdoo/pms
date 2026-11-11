# Copyright (c) 2021 Gray Matter Logic
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
from datetime import datetime, timedelta

import pytz

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT


class PMSConfigurator(models.TransientModel):
    _name = "pms.configurator"
    _description = "PMS Configurator"

    def _get_duration(self, start, stop):
        """Get the duration value between the 2 given dates."""
        if not start or not stop:
            return 0
        duration = (stop - start).total_seconds() / (24 * 3600)
        return round(duration, 0)

    @api.depends("stop", "start")
    def _compute_duration(self):
        for reservation in self.with_context(dont_notify=True):
            reservation.duration = self._get_duration(
                reservation.start, reservation.stop
            )

    @api.depends("start", "duration")
    def _compute_stop(self):
        # stop and duration fields both depends on the start field.
        # But they also depends on each other.
        # When start is updated, we want to update the stop datetime based on
        # the *current* duration.
        # In other words, we want: change start => keep the duration fixed and
        # recompute stop accordingly.
        # However, while computing stop, duration is marked to be recomputed.
        # Calling `reservation.duration` would trigger its recomputation.
        # To avoid this we manually mark the field as computed.
        duration_field = self._fields["duration"]
        self.env.remove_to_compute(duration_field, self)
        for reservation in self:
            date_stop = reservation.start + timedelta(days=reservation.duration)
            reservation.stop = datetime.combine(date_stop, reservation.stop.time())

    @api.depends("guest_ids")
    def _compute_no_of_guests(self):
        self.no_of_guests = 0
        if self.guest_ids:
            self.no_of_guests = len(self.guest_ids)

    product_id = fields.Many2one("product.product", string="Product", readonly=True)
    property_id = fields.Many2one("pms.property", string="Property")
    reservation_id = fields.Many2one(
        "pms.property.reservation", string="Reservation Type"
    )
    accommodation_type_id = fields.Many2one(
        "pms.accommodation.type",
        string="Accommodation Type",
        domain="[('property_id', '=', property_id)]",
    )
    room_id = fields.Many2one(
        "pms.room",
        string="Room",
        domain="[('property_id', '=', property_id), ('accommodation_type_id', '=', accommodation_type_id)]",
    )
    start = fields.Datetime(
        "From",
        required=True,
        help="Start date of the reservation",
    )
    stop = fields.Datetime(
        "To",
        required=True,
        compute="_compute_stop",
        readonly=False,
        store=True,
        help="Stop date of the reservation",
    )
    duration = fields.Integer(
        "Nights", compute="_compute_duration", store=True, readonly=False
    )
    no_of_guests = fields.Integer(
        "Number of Guests", compute="_compute_no_of_guests", store=True
    )
    guest_ids = fields.One2many(
        "pms.reservation.guest.wizard", "configurator_id", string="Guests"
    )
    price = fields.Float(related="reservation_id.price", readonly=True)
    currency_id = fields.Many2one("res.currency", string="Currency")
    existing_reservation_id = fields.Integer()
    reservation_ids = fields.Many2many("pms.reservation")
    timeline_html = fields.Html("Timeline HTML", readonly=True)
    partner_id = fields.Many2one("res.partner", string="Booked by")

    def _update_bookings_tab(self):
        if not self.property_id:
            self.reservation_ids = [(5,)]
            return
        domain = [
            ("property_id", "=", self.property_id.id),
            ("stage_id.is_closed", "=", False),
        ]
        if self.start and self.stop:
            domain += [("start", "<", self.stop), ("stop", ">", self.start)]
        else:
            domain += [("stop", ">", fields.Datetime.now())]
        if self.existing_reservation_id:
            domain += [("id", "!=", self.existing_reservation_id)]
        self.reservation_ids = [(6, 0, self.env["pms.reservation"].search(domain).ids)]

    @api.onchange("property_id")
    def onchange_property_id(self):
        if (
            self.reservation_id
            and self.reservation_id.property_id
            and self.reservation_id.property_id != self.property_id
        ):
            self.reservation_id = False
            self.room_id = False
        if (
            self.accommodation_type_id
            and self.accommodation_type_id.property_id != self.property_id
        ):
            self.accommodation_type_id = False
        user_tz = self.env.user.tz or "UTC"
        utc = pytz.timezone("UTC")
        timezone = pytz.timezone(user_tz)
        if (
            self.property_id
            and self.start
            and self.stop
            and self.property_id.checkin
            and self.property_id.checkout
        ):
            if (
                str(self.start) != (self.env.context.get("default_start") or "")
            ) or self.property_id.id != self.env.context.get("default_property_id"):
                start_datetime = (
                    str(self.start.date())
                    + " "
                    + str(timedelta(hours=self.property_id.checkin))
                )
                with_timezone = timezone.localize(
                    datetime.strptime(start_datetime, DEFAULT_SERVER_DATETIME_FORMAT)
                )
                start_datetime = with_timezone.astimezone(utc)
                self.start = start_datetime.strftime(DEFAULT_SERVER_DATETIME_FORMAT)
            if (
                str(self.stop) != (self.env.context.get("default_stop") or "")
            ) or self.property_id.id != self.env.context.get("default_property_id"):
                end_datetime = (
                    str(self.stop.date())
                    + " "
                    + str(timedelta(hours=self.property_id.checkout))
                )
                with_timezone = timezone.localize(
                    datetime.strptime(end_datetime, DEFAULT_SERVER_DATETIME_FORMAT)
                )
                end_datetime = with_timezone.astimezone(utc)
                self.stop = end_datetime.strftime(DEFAULT_SERVER_DATETIME_FORMAT)
        self._update_bookings_tab()

    @api.onchange("reservation_id")
    def onchange_reservation_id(self):
        self.accommodation_type_id = (
            self.reservation_id.accommodation_type_id
            if self.reservation_id
            else False
        )
        self.room_id = False

    @api.onchange("start", "stop")
    def onchange_dates(self):
        self._update_bookings_tab()

    @api.constrains(
        "property_id",
        "reservation_id",
        "accommodation_type_id",
        "room_id",
        "start",
        "stop",
    )
    def _check_no_overlapping_reservation(self):
        Reservation = self.env["pms.reservation"]
        for configurator in self:
            if not (
                configurator.property_id and configurator.start and configurator.stop
            ):
                continue
            if configurator.existing_reservation_id:
                existing_id = configurator.existing_reservation_id
            else:
                existing_id = False
            if (
                configurator.reservation_id.property_id
                and configurator.reservation_id.property_id != configurator.property_id
            ):
                raise ValidationError(
                    self.env._("The reservation offer belongs to another property.")
                )
            if (
                configurator.accommodation_type_id
                and configurator.accommodation_type_id.property_id
                != configurator.property_id
            ):
                raise ValidationError(
                    self.env._(
                        "The accommodation type belongs to another property."
                    )
                )
            if (
                configurator.reservation_id.accommodation_type_id
                and configurator.reservation_id.accommodation_type_id
                != configurator.accommodation_type_id
            ):
                raise ValidationError(
                    self.env._(
                        "The accommodation type must match the selected reservation "
                        "offer."
                    )
                )
            if configurator.room_id and (
                configurator.room_id.property_id != configurator.property_id
                or configurator.room_id.accommodation_type_id
                != configurator.accommodation_type_id
            ):
                raise ValidationError(
                    self.env._(
                        "The room must belong to the selected property and "
                        "accommodation type."
                    )
                )
            if configurator.room_id:
                room_conflict = Reservation.search_count(
                    Reservation._get_active_overlap_domain(
                        configurator.property_id.id,
                        configurator.start,
                        configurator.stop,
                    )
                    + [
                        ("room_id", "=", configurator.room_id.id),
                        ("id", "!=", existing_id),
                    ]
                )
                if room_conflict:
                    raise ValidationError(
                        self.env._(
                            "The selected room is already reserved for these dates."
                        )
                    )
            is_available = Reservation.is_accommodation_type_available(
                configurator.property_id.id,
                configurator.accommodation_type_id.id,
                configurator.start,
                configurator.stop,
                exclude_id=existing_id,
            )
            if not is_available:
                raise ValidationError(
                    self.env._(
                        "%(property)s has no availability for the selected "
                        "accommodation type between %(start)s and %(stop)s.",
                        property=configurator.property_id.display_name,
                        start=configurator.start.strftime("%b %d, %Y"),
                        stop=configurator.stop.strftime("%b %d, %Y"),
                    )
                )

    @api.constrains(
        "property_id", "reservation_id", "accommodation_type_id", "no_of_guests"
    )
    def _check_max_no_of_guests(self):
        for configurator in self:
            max_guests = (
                configurator.accommodation_type_id.capacity
                or configurator.property_id.no_of_guests
            )
            if max_guests and configurator.no_of_guests > max_guests:
                raise ValidationError(
                    self.env._(  # pylint: disable=W8301
                        "%(guests)s of guests is lower than"
                        " the %(max)s of the property."
                    )
                    % {
                        "guests": configurator.no_of_guests,
                        "max": max_guests,
                    }
                )

    @api.model
    def default_get(self, fields_vals):
        result = super().default_get(fields_vals)
        existing_reservation_id = self.env.context.get(
            "default_existing_reservation_id"
        )
        if existing_reservation_id:
            reservation = self.env["pms.reservation"].browse(existing_reservation_id)
            if reservation.exists():
                result["existing_reservation_id"] = reservation.id
                result["property_id"] = reservation.property_id.id
                result["partner_id"] = reservation.partner_id.id
                result["start"] = reservation.start
                result["stop"] = reservation.stop
                if reservation.start and reservation.stop:
                    result["duration"] = int(
                        self._get_duration(reservation.start, reservation.stop)
                    )
                if reservation.reservation_type_id:
                    result["reservation_id"] = reservation.reservation_type_id.id
                if reservation.accommodation_type_id:
                    result["accommodation_type_id"] = (
                        reservation.accommodation_type_id.id
                    )
                if reservation.room_id:
                    result["room_id"] = reservation.room_id.id
                result["guest_ids"] = [
                    (
                        0,
                        0,
                        {
                            "partner_id": g.partner_id.id,
                            "name": g.name,
                            "email": g.email or False,
                            "phone": g.phone or False,
                        },
                    )
                    for g in reservation.guest_ids
                ]
        if not result.get("start"):
            result["start"] = fields.Date.today()
        if not result.get("stop"):
            result["stop"] = fields.Date.today()
        if self.env.context.get("web_partner_id") and not result.get("partner_id"):
            result["partner_id"] = self.env.context["web_partner_id"]
        if self.env.context.get("web_partner_id") and not result.get("guest_ids"):
            partner_rec = self.env["res.partner"].browse(
                self.env.context.get("web_partner_id")
            )
            if partner_rec:
                result["guest_ids"] = [
                    (
                        0,
                        0,
                        {
                            "partner_id": partner_rec.id,
                            "name": partner_rec.name,
                            "email": partner_rec.email,
                            "phone": partner_rec.phone,
                        },
                    )
                ]
        property_id = result.get("property_id")
        if property_id:
            domain = [
                ("property_id", "=", property_id),
                ("stage_id.is_closed", "=", False),
                ("stop", ">", fields.Datetime.now()),
            ]
            if existing_reservation_id:
                domain += [("id", "!=", existing_reservation_id)]
            result["reservation_ids"] = [
                (6, 0, self.env["pms.reservation"].search(domain).ids)
            ]
        ref_id = self.env.ref("pms_sale.action_sale_reservation")
        timeline_url = (
            "{}/web?#action={}&model=pms.reservation&view_type=schedule".format(
                self.env["ir.config_parameter"].sudo().get_param("web.base.url"),
                ref_id and str(ref_id.id) or "",
            )
        )
        result["timeline_html"] = (
            f"<a class='btn btn-primary' href='{timeline_url}'"
            " alt='Timeline View' target='_blank'"
            " >Timeline</a>"
        )
        return result


class PMSReservationGuestWizard(models.TransientModel):
    _name = "pms.reservation.guest.wizard"
    _description = "PMS Reservation guest"

    name = fields.Char(required=True)
    phone = fields.Char()
    email = fields.Char()
    configurator_id = fields.Many2one("pms.configurator", string="Configurator")
    partner_id = fields.Many2one("res.partner", string="Partner")

    @api.onchange("partner_id")
    def _onchange_partner_id(self):
        if self.partner_id:
            self.name = self.partner_id.name
            self.phone = self.partner_id.phone
            self.email = self.partner_id.email
