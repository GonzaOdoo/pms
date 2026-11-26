# Copyright (c) 2021 Gray Matter Logic
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
from odoo import fields, models


class PmsPropertyImage(models.Model):
    _name = "pms.property.image"
    _description = "Property Image"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    name = fields.Char(required=True, default="Imagen")
    image_1920 = fields.Image(
        string="Image",
        required=True,
        max_width=1920,
        max_height=1920,
    )
    property_id = fields.Many2one(
        "pms.property",
        string="Property",
        required=True,
        ondelete="cascade",
        index=True,
    )
