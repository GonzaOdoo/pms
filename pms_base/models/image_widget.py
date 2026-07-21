from odoo import models, fields

class RealEstatePropertyImage(models.Model):
    _name = "real.estate.property.image"
    _order = "sequence, id"
    property_id = fields.Many2one(
        "pms.property",
        required=False,
        ondelete="cascade",
    )

    sequence = fields.Integer(default=10)

    name = fields.Char()

    image = fields.Image()

    is_cover = fields.Boolean()