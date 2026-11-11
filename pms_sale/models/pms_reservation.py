# Copyright (c) 2021 Gray Matter Logic
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
from datetime import datetime, timedelta

import pytz

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT

AVAILABLE_PRIORITIES = [("0", "Normal"), ("1", "Low"), ("2", "High"), ("3", "Urgent")]


class PmsReservation(models.Model):
    _name = "pms.reservation"
    _description = "Reservation"
    _order = "start, id"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    def _default_stage_id(self):
        return self.env.ref("pms_sale.pms_stage_new", raise_if_not_found=False)

    def _get_duration(self, start, stop):
        """Get the duration value between the 2 given dates."""
        if not start or not stop:
            return 0
        duration = (stop - start).total_seconds() / (24 * 3600)
        return round(duration, 0)

    @api.depends("guest_ids")
    def _compute_no_of_guests(self):
        self.no_of_guests = 0
        if self.guest_ids:
            self.no_of_guests = len(self.guest_ids)

    name = fields.Char(
        string="Reservation #",
        help="Reservation Number",
        required=True,
        readonly=True,
        index=True,
        copy=False,
        default=lambda self: self.env._("New"),
    )
    start = fields.Datetime(
        "Checkin",
        required=True,
        tracking=True,
        default=fields.Date.today,
        help="Start date of the reservation",
    )
    stop = fields.Datetime(
        "Checkout",
        required=True,
        tracking=True,
        default=fields.Date.today,
        compute="_compute_stop",
        readonly=False,
        store=True,
        help="Stop date of the reservation",
    )
    duration = fields.Integer(
        "Nights", compute="_compute_duration", store=True, readonly=False
    )
    date = fields.Datetime(default=lambda self: fields.Datetime.now())
    stage_id = fields.Many2one(
        "pms.stage",
        string="Stage",
        store=True,
        tracking=True,
        index=True,
        default=lambda self: self._default_stage_id(),
        group_expand="_read_group_stage_ids",
    )
    team_id = fields.Many2one(
        "pms.team", string="Team", related="property_id.team_id", store=True
    )
    property_id = fields.Many2one("pms.property", string="Property")
    reservation_type_id = fields.Many2one(
        "pms.property.reservation",
        string="Reservation Offer",
        ondelete="restrict",
    )
    accommodation_type_id = fields.Many2one(
        "pms.accommodation.type",
        string="Accommodation Type",
        ondelete="restrict",
        index=True,
    )
    room_id = fields.Many2one(
        "pms.room",
        string="Room",
        ondelete="restrict",
        index=True,
        domain="[('property_id', '=', property_id), ('accommodation_type_id', '=', accommodation_type_id)]",
    )
    sale_order_id = fields.Many2one("sale.order", string="Sales Order")
    sale_order_line_id = fields.Many2one("sale.order.line", string="Sales Order Line")
    invoice_status = fields.Selection(
        related="sale_order_id.invoice_status", store=True, index=True
    )
    partner_id = fields.Many2one("res.partner", string="Booked by")
    user_id = fields.Many2one(
        "res.users", string="Responsible", default=lambda self: self.env.user.id
    )
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        default=lambda self: self.env.company.id,
    )
    adults = fields.Integer()
    children = fields.Integer()
    no_of_guests = fields.Integer(
        "Number of Guests", compute="_compute_no_of_guests", store=True
    )
    guest_ids = fields.One2many(
        "pms.reservation.guest", "reservation_id", string="Guests"
    )
    priority = fields.Selection(
        AVAILABLE_PRIORITIES,
        index=True,
        default=AVAILABLE_PRIORITIES[0][0],
    )
    tag_ids = fields.Many2many("pms.tag", string="Tags")
    color = fields.Integer("Color Index", default=0)
    invoice_count = fields.Integer(
        compute="_compute_invoice_count",
        readonly=True,
        copy=False,
    )

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
            reservation.stop = reservation.start + timedelta(days=reservation.duration)

    def _compute_invoice_count(self):
        for reservation in self:
            invoices = (
                self.env["account.move.line"]
                .search([("pms_reservation_id", "=", reservation.id)])
                .mapped("move_id")
                .filtered(lambda r: r.move_type in ("out_invoice", "out_refund"))
            )
            reservation.invoice_count = len(invoices)

    @api.model
    def _read_group_stage_ids(self, stages, domain):
        search_domain = [("stage_type", "=", "reservation")]
        if self.env.context.get("default_team_id"):
            search_domain = [
                "&",
                ("team_ids", "in", self.env.context["default_team_id"]),
            ] + search_domain
        return stages.search(search_domain)

    @api.onchange("reservation_type_id")
    def _onchange_reservation_type_id(self):
        if self.reservation_type_id:
            self.accommodation_type_id = (
                self.reservation_type_id.accommodation_type_id
            )
            self.room_id = False

    @api.onchange("property_id")
    def _onchange_property_for_room_assignment(self):
        if self.room_id and self.room_id.property_id != self.property_id:
            self.room_id = False
        if (
            self.accommodation_type_id
            and self.accommodation_type_id.property_id != self.property_id
        ):
            self.accommodation_type_id = False
            self.reservation_type_id = False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", self.env._("New")) == self.env._("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "pms.reservation"
                ) or self.env._("New")
            if vals.get("reservation_type_id") and not vals.get(
                "accommodation_type_id"
            ):
                reservation_type = self.env["pms.property.reservation"].browse(
                    vals["reservation_type_id"]
                )
                vals["accommodation_type_id"] = (
                    reservation_type.accommodation_type_id.id or False
                )
        return super().create(vals_list)

    def write(self, vals):
        vals = dict(vals)
        if "reservation_type_id" in vals and "accommodation_type_id" not in vals:
            reservation_type = self.env["pms.property.reservation"].browse(
                vals["reservation_type_id"]
            )
            vals["accommodation_type_id"] = (
                reservation_type.accommodation_type_id.id or False
            )
        return super().write(vals)

    @api.onchange("property_id")
    def onchange_property_id(self):
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
        else:
            self.start = self.start.date()
            self.stop = self.stop.date()

    @api.constrains(
        "property_id", "accommodation_type_id", "no_of_guests", "guest_ids"
    )
    def _check_max_no_of_guests(self):
        for reservation in self:
            max_guests = (
                reservation.accommodation_type_id.capacity
                or reservation.property_id.no_of_guests
            )
            if max_guests and reservation.no_of_guests > max_guests:
                raise ValidationError(
                    self.env._(  # pylint: disable=W8301
                        "Too many guests (%(guests)s) on the reservation: "
                        "the property accepts a maximum of %(max)s guests."
                    )
                    % {
                        "guests": reservation.no_of_guests,
                        "max": max_guests,
                    }
                )

    @api.model
    def _get_active_overlap_domain(self, property_id, start, stop):
        return [
            ("property_id", "=", property_id),
            ("stage_id.is_closed", "=", False),
            ("start", "<", stop),
            ("stop", ">", start),
        ]

    @api.model
    def is_accommodation_type_available(
        self, property_id, accommodation_type_id, start, stop, exclude_id=False
    ):
        property_rec = self.env["pms.property"].browse(property_id).exists()
        accommodation_type = self.env["pms.accommodation.type"].browse(
            accommodation_type_id
        ).exists()
        if not property_rec or not start or not stop or start >= stop:
            return False

        domain = self._get_active_overlap_domain(property_rec.id, start, stop)
        if exclude_id:
            domain.append(("id", "!=", exclude_id))

        if not accommodation_type_id:
            return not self.search_count(domain)
        if (
            not accommodation_type
            or not accommodation_type.active
            or accommodation_type.property_id != property_rec
        ):
            return False

        physical_room_count = self.env["pms.room"].search_count(
            [
                ("property_id", "=", property_rec.id),
                ("accommodation_type_id", "=", accommodation_type.id),
                ("active", "=", True),
            ]
        )
        if not physical_room_count:
            return False

        legacy_bookings = self.search_count(
            domain + [("accommodation_type_id", "=", False)]
        )
        if legacy_bookings:
            return False

        type_bookings = self.search_count(
            domain + [("accommodation_type_id", "=", accommodation_type.id)]
        )
        return type_bookings < physical_room_count

    @api.constrains(
        "property_id",
        "reservation_type_id",
        "accommodation_type_id",
        "room_id",
        "stage_id",
        "start",
        "stop",
    )
    def _check_no_of_reservations(self):
        for rec in self:
            if not (rec.property_id and rec.start and rec.stop):
                continue
            if rec.start >= rec.stop:
                raise ValidationError(
                    self.env._("The check-out date must be after the check-in date.")
                )

            self.env.cr.execute(
                "SELECT id FROM pms_property WHERE id = %s FOR UPDATE",
                [rec.property_id.id],
            )
            if (
                rec.reservation_type_id
                and rec.reservation_type_id.property_id
                and rec.reservation_type_id.property_id != rec.property_id
            ):
                raise ValidationError(
                    self.env._(
                        "The reservation offer must belong to the selected property."
                    )
                )
            if (
                rec.reservation_type_id.accommodation_type_id
                and rec.reservation_type_id.accommodation_type_id
                != rec.accommodation_type_id
            ):
                raise ValidationError(
                    self.env._(
                        "The accommodation type must match the selected reservation "
                        "offer."
                    )
                )
            if (
                rec.accommodation_type_id
                and rec.accommodation_type_id.property_id != rec.property_id
            ):
                raise ValidationError(
                    self.env._(
                        "The accommodation type must belong to the selected property."
                    )
                )
            if rec.room_id and rec.room_id.property_id != rec.property_id:
                raise ValidationError(
                    self.env._("The room must belong to the selected property.")
                )
            if (
                rec.room_id
                and rec.accommodation_type_id
                and rec.room_id.accommodation_type_id != rec.accommodation_type_id
            ):
                raise ValidationError(
                    self.env._("The room must belong to the selected accommodation type.")
                )

            overlap_domain = self._get_active_overlap_domain(
                rec.property_id.id, rec.start, rec.stop
            )
            overlap_domain.append(("id", "!=", rec.id))
            if rec.accommodation_type_id:
                if rec.room_id:
                    room_conflict = self.search_count(
                        overlap_domain + [("room_id", "=", rec.room_id.id)]
                    )
                    if room_conflict:
                        raise ValidationError(
                            self.env._(
                                "The selected room is already reserved for these dates."
                            )
                        )
                if self.search_count(
                    overlap_domain + [("accommodation_type_id", "=", False)]
                ):
                    raise ValidationError(
                        self.env._(
                            "An existing property-wide reservation overlaps these dates."
                        )
                    )
                room_count = self.env["pms.room"].search_count(
                    [
                        ("property_id", "=", rec.property_id.id),
                        ("accommodation_type_id", "=", rec.accommodation_type_id.id),
                        ("active", "=", True),
                    ]
                )
                booking_count = self.search_count(
                    overlap_domain
                    + [
                        (
                            "accommodation_type_id",
                            "=",
                            rec.accommodation_type_id.id,
                        )
                    ]
                )
                if not room_count or booking_count >= room_count:
                    raise ValidationError(
                        self.env._(
                            "No rooms of this accommodation type are available "
                            "for these dates."
                        )
                    )
            elif self.search_count(overlap_domain):
                raise ValidationError(
                    self.env._(
                        "You cannot have overlapping reservations for the same property."
                    )
                )

    @api.constrains("property_id", "duration")
    def _check_no_of_nights(self):
        for rec in self:
            if rec.property_id and (
                (rec.property_id.min_nights and rec.duration < rec.property_id.min_nights)
                or (
                    rec.property_id.max_nights
                    and rec.duration > rec.property_id.max_nights
                )
            ):
                raise ValidationError(
                    self.env._(  # pylint: disable=W8301
                        "The number of nights must be between %(min)s and %(max)s."
                    )
                    % {
                        "min": rec.property_id.min_nights,
                        "max": rec.property_id.max_nights,
                    }
                )

    def action_book(self):
        return self.write(
            {
                "stage_id": self.env.ref(
                    "pms_sale.pms_stage_booked", raise_if_not_found=False
                ).id,
            }
        )

    def action_confirm(self):
        return self.write(
            {
                "stage_id": self.env.ref(
                    "pms_sale.pms_stage_confirmed", raise_if_not_found=False
                ).id
            }
        )

    def action_check_in(self):
        return self.write(
            {
                "stage_id": self.env.ref(
                    "pms_sale.pms_stage_checked_in", raise_if_not_found=False
                ).id,
                "start": fields.Datetime.now(),
            }
        )

    def action_check_out(self):
        return self.write(
            {
                "stage_id": self.env.ref(
                    "pms_sale.pms_stage_checked_out", raise_if_not_found=False
                ).id,
                "stop": fields.Datetime.now(),
            }
        )

    def action_cancel(self):
        self.write(
            {
                "stage_id": self.env.ref(
                    "pms_sale.pms_stage_cancelled", raise_if_not_found=False
                ).id
            }
        )

    def action_view_invoices(self):
        for reservation in self:
            action = self.env.ref("account.action_move_out_invoice_type").read()[0]
            invoices = (
                self.env["account.move.line"]
                .search([("pms_reservation_id", "=", reservation.id)])
                .mapped("move_id")
                .filtered(lambda r: r.move_type in ("out_invoice", "out_refund"))
            )
            action["domain"] = [("id", "in", invoices.ids)]
            return action

    @api.model
    def get_selections(self):
        cities = list(
            {rec.city for rec in self.env["pms.property"].search([]) if rec.city}
        )
        cities.sort()
        values = {"city": cities}
        return values
