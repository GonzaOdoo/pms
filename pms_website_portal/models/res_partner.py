from odoo import api, fields, models


class AccountMove(models.Model):
    _inherit = "res.partner"

    is_house_provider = fields.Boolean(string='Oferente', default=False)
