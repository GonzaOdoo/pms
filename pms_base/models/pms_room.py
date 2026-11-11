# Copyright 2017  Alexandre Díaz
# Copyright 2017  Dario Lodeiros
# Copyright 2018  Pablo Quesada
# Copyright (c) 2021 Open Source Integrators
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class PmsRoom(models.Model):
    _name = "pms.room"
    _description = "Property Room"
    _order = "sequence, type_id, name"

    name = fields.Char(string="Room Name", help="Room Name", required=True)
    active = fields.Boolean(help="Determines if room is active", default=True)
    sequence = fields.Integer(
        help="Field used to change the position of the rooms in tree view."
        "Changing the position changes the sequence",
        default=0,
    )
    property_id = fields.Many2one(
        string="Property",
        required=True,
        comodel_name="pms.property",
        ondelete="restrict",
    )
    type_id = fields.Many2one(
        string="Space Type",
        help="Classification of this physical space, separate from its "
        "bookable accommodation type.",
        required=True,
        comodel_name="pms.room.type",
        ondelete="restrict",
    )
    accommodation_type_id = fields.Many2one(
        "pms.accommodation.type",
        string="Accommodation Type",
        help="Bookable category this physical room belongs to.",
        ondelete="restrict",
        index=True,
        domain="[('property_id', '=', property_id)]",
    )
    capacity = fields.Integer(
        help="The maximum number of people that can occupy a room"
    )
    area = fields.Float()
    floor = fields.Integer()
    amenity_ids = fields.Many2many(
        "pms.amenity",
        string="Amenities",
        relation="pms_room_amenity_rel",
        column1="room_id",
        column2="amenity_id",
    )
    _sql_room_property_unique = models.Constraint(
        "unique(name, property_id)",
        "You cannot have more 2 rooms with the same name in the same property.",
    )

    @api.constrains("property_id", "accommodation_type_id")
    def _check_accommodation_type_property(self):
        for room in self:
            if (
                room.accommodation_type_id
                and room.accommodation_type_id.property_id != room.property_id
            ):
                raise ValidationError(
                    self.env._(
                        "The accommodation type must belong to the same property "
                        "as the physical room."
                    )
                )
