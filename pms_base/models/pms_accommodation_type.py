# Copyright (c) 2026
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class PmsAccommodationType(models.Model):
    _name = "pms.accommodation.type"
    _description = "Accommodation Type"
    _order = "sequence, name"

    name = fields.Char(required=True, translate=True)
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    property_id = fields.Many2one(
        "pms.property",
        string="Property",
        required=True,
        ondelete="restrict",
        index=True,
    )
    description = fields.Text()
    capacity = fields.Integer(
        string="Maximum Occupancy",
        help="Maximum number of guests for an accommodation of this type.",
    )
    bedroom_count = fields.Integer(string="Bedrooms")
    bathroom_count = fields.Integer(string="Bathrooms")
    area = fields.Float()
    amenity_ids = fields.Many2many(
        "pms.amenity",
        string="Amenities",
        relation="pms_accommodation_type_amenity_rel",
        column1="accommodation_type_id",
        column2="amenity_id",
    )
    room_ids = fields.One2many(
        "pms.room", "accommodation_type_id", string="Physical Rooms"
    )
    room_count = fields.Integer(compute="_compute_room_count")

    _sql_property_name_unique = models.Constraint(
        "unique(property_id, name)",
        "An accommodation type with this name already exists for this property.",
    )

    @api.depends("room_ids")
    def _compute_room_count(self):
        for accommodation_type in self:
            accommodation_type.room_count = len(accommodation_type.room_ids)

    @api.constrains("property_id")
    def _check_rooms_property(self):
        for accommodation_type in self:
            if accommodation_type.room_ids.filtered(
                lambda room: room.property_id != accommodation_type.property_id
            ):
                raise ValidationError(
                    self.env._(
                        "An accommodation type cannot be moved to another property "
                        "while it has physical rooms assigned."
                    )
                )
