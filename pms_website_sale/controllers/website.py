# Copyright (c) 2021 Gray Matter Logic
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
from datetime import datetime

from odoo import _, http
from odoo.http import request

from odoo.addons.pms_website.controllers.website import Website as PmsPropertyWebsite
from odoo.addons.website.controllers.main import QueryURL
from odoo.addons.website_sale.controllers.main import WebsiteSale


class PropertyTableCompute:
    def __init__(self):
        self.table = {}

    def _check_place(self, posx, posy, sizex, sizey, ppr):
        res = True
        for y in range(sizey):
            for x in range(sizex):
                if posx + x >= ppr:
                    res = False
                    break
                row = self.table.setdefault(posy + y, {})
                if row.setdefault(posx + x) is not None:
                    res = False
                    break
            for x in range(ppr):
                self.table[posy + y].setdefault(x, None)
        return res

    def process(self, products, ppg=20, ppr=4):
        # Compute products positions on the grid
        minpos = 0
        index = 0
        maxy = 0
        x = 0
        for p in products:
            x = min(1, ppr)
            y = min(1, ppr)
            if index >= ppg:
                x = y = 1

            pos = minpos
            while not self._check_place(pos % ppr, pos // ppr, x, y, ppr):
                pos += 1
            # if 21st product (index 20) and last line is full (ppr products), break
            # (pos + 1.0) / ppr is the line where the product would be inserted
            # maxy is the number of existing lines
            # + 1.0 is because pos begins at 0, thus pos 20 is actually the 21st block
            # and to force python to not round the division operation
            if index >= ppg and ((pos + 1.0) // ppr) > maxy:
                break

            if x == 1 and y == 1:  # simple heuristic for CPU optimization
                minpos = pos // ppr

            for y2 in range(y):
                for x2 in range(x):
                    self.table[(pos // ppr) + y2][(pos % ppr) + x2] = False
            self.table[pos // ppr][pos % ppr] = {"product": p, "x": x, "y": y}
            if index <= ppg:
                maxy = max(maxy, y + (pos // ppr))
            index += 1

        # Format table according to HTML needs
        rows = sorted(self.table.items())
        rows = [r[1] for r in rows]
        for col in range(len(rows)):
            cols = sorted(rows[col].items())
            x += len(cols)
            rows[col] = [r[1] for r in cols if r[1]]

        return rows


class WebsiteSale(WebsiteSale):
    def _get_property_search_domain(self, search, category, guest, args):
        domain = []
        if search:
            domain += [("city", "ilike", search)]
        if category:
            domain += [("property_category_ids", "child_of", category.id)]
        domain += [("property_child_ids", "=", False)]

        try:
            guest_count = int(guest) if guest else 0
        except (TypeError, ValueError):
            return domain + [("id", "=", 0)]

        start = stop = False
        if args.get("date_range"):
            date_range = args["date_range"].split("-")
            if len(date_range) != 2:
                return domain + [("id", "=", 0)]
            try:
                start = datetime.strptime(
                    date_range[0].strip() + " 00:00:00", "%m/%d/%Y %H:%M:%S"
                )
                stop = datetime.strptime(
                    date_range[1].strip() + " 00:00:00", "%m/%d/%Y %H:%M:%S"
                )
            except ValueError:
                return domain + [("id", "=", 0)]
            if start >= stop:
                return domain + [("id", "=", 0)]

        properties = request.env["pms.property"].sudo().search(domain)
        Reservation = request.env["pms.reservation"].sudo()
        available_property_ids = []
        for property_rec in properties:
            if property_rec.accommodation_type_ids:
                accommodation_types = property_rec.accommodation_type_ids.filtered(
                    lambda accommodation_type: accommodation_type.active
                    and (
                        not accommodation_type.capacity
                        or accommodation_type.capacity >= guest_count
                    )
                )
                is_available = bool(accommodation_types) and (
                    not start
                    or any(
                        Reservation.is_accommodation_type_available(
                            property_rec.id,
                            accommodation_type.id,
                            start,
                            stop,
                        )
                        for accommodation_type in accommodation_types
                    )
                )
            else:
                is_available = (
                    not property_rec.no_of_guests
                    or property_rec.no_of_guests >= guest_count
                ) and (
                    not start
                    or Reservation.is_accommodation_type_available(
                        property_rec.id, False, start, stop
                    )
                )
            if is_available:
                available_property_ids.append(property_rec.id)
        domain += [("id", "in", available_property_ids)]
        return domain

    def _get_pricelist_context(self):
        pricelist_context = dict(request.env.context)
        pricelist = request.pricelist
        pricelist_context["pricelist"] = pricelist.id
        return pricelist_context, pricelist

    def _update_property_values(self, Property, post):
        values = {
            "city": list(
                {
                    property_rec.city
                    for property_rec in Property.search([])
                    if property_rec.city
                }
            )
        }
        return values

    @http.route(
        [
            """/property""",
            """/property/page/<int:page>""",
            """/property/category/<model("pms.website.category"):category>""",
        ],
        type="http",
        auth="public",
        website=True,
    )
    def property(
        self, page=0, ppg=False, category=None, search="", guest_select="", **post
    ):
        Category = request.env["pms.website.category"]
        if category:
            category = Category.search([("id", "=", int(category))], limit=1)
        else:
            category = Category

        if ppg:
            try:
                ppg = int(ppg)
                post["ppg"] = ppg
            except ValueError:
                ppg = False
        if not ppg:
            ppg = request.env["website"].get_current_website().shop_ppg or 20

        ppr = request.env["website"].get_current_website().shop_ppr or 4

        domain = self._get_property_search_domain(
            search=search, category=category, guest=guest_select, args=post
        )

        keep = QueryURL("/property", category=category and int(category))

        pricelist_context, pricelist = self._get_pricelist_context()

        request.update_context(
            pricelist=pricelist.id, partner=request.env.user.partner_id
        )

        Property = request.env["pms.property"].with_context(bin_size=True)

        search_property = Property.search(domain, order="name asc")
        url = "/property"

        categs_domain = [("parent_id", "=", False)]
        if search:
            search_categories = Category.search(
                [("property_ids", "in", search_property.ids)]
            ).parents_and_self
            categs_domain.append(("id", "in", search_categories.ids))
        else:
            search_categories = Category
        categs = Category.search(categs_domain)

        if category:
            url = f"/shop/category/{request.env['ir.http']._slug(category)}"

        product_count = len(search_property)
        pager = request.website.pager(
            url=url, total=product_count, page=page, step=ppg, scope=7, url_args=post
        )
        offset = pager["offset"]
        properties = search_property[offset : offset + ppg]

        layout_mode = "grid"

        values = self._update_property_values(Property=Property, post=post)
        # properties
        values.update(
            {
                "category": category,
                "search_city": search,
                "search_guest": guest_select,
                "search_raneg": post.get("date_range"),
                "pager": pager,
                "pricelist": pricelist,
                "properties": properties,
                "search_count": product_count,  # common for all searchbox
                "bins": PropertyTableCompute().process(properties, ppg, ppr),
                "ppg": ppg,
                "ppr": ppr,
                "keep": keep,
                "layout_mode": layout_mode,
                "categories": categs,
                "search_categories_ids": search_categories.ids,
            }
        )

        return request.render("pms_website_sale.properties", values)


class PmsWebsiteSale(PmsPropertyWebsite):
    def _prepare_property_values(self, pms_property, category, search, **kwargs):
        values = super()._prepare_property_values(
            pms_property, category, search, **kwargs
        )
        reservation_types = (
            request.env["pms.property.reservation"]
            .sudo()
            .search(
                [
                    ("property_id", "in", [False, pms_property.id]),
                    "|",
                    ("accommodation_type_id", "=", False),
                    ("accommodation_type_id.property_id", "=", pms_property.id),
                ]
            )
            .filtered(
                lambda reservation_type: (
                    not reservation_type.accommodation_type_id
                    or reservation_type.accommodation_type_id.active
                )
            )
        )
        values["reservation_types"] = reservation_types
        values["is_public_user"] = request.env.user._is_public()
        return values

    @http.route(
        ["/property/<int:property_id>/check_availability"],
        type="jsonrpc",
        auth="public",
        website=True,
        methods=["POST"],
    )
    def check_availability(
        self,
        property_id,
        date_start=None,
        date_end=None,
        reservation_type_id=None,
        **kwargs,
    ):
        if not date_start or not date_end:
            return {"available": False, "error": _("Missing dates")}
        try:
            start = datetime.strptime(date_start, "%Y-%m-%d")
            end = datetime.strptime(date_end, "%Y-%m-%d")
        except ValueError:
            return {"available": False, "error": _("Invalid dates")}
        if start >= end:
            return {
                "available": False,
                "error": _("Check-out must be after check-in"),
            }

        property_rec = request.env["pms.property"].sudo().browse(property_id).exists()
        if not property_rec or not property_rec.can_access_from_current_website():
            return {"available": False, "error": _("Property not found")}

        Reservation = request.env["pms.reservation"].sudo()
        if reservation_type_id:
            try:
                reservation_type_id = int(reservation_type_id)
            except (TypeError, ValueError):
                return {
                    "available": False,
                    "error": _("Invalid reservation type"),
                }
            reservation_type = (
                request.env["pms.property.reservation"]
                .sudo()
                .browse(reservation_type_id)
                .exists()
            )
            if not reservation_type or (
                reservation_type.property_id
                and reservation_type.property_id != property_rec
            ):
                return {
                    "available": False,
                    "error": _("Invalid reservation type"),
                }
            available = Reservation.is_accommodation_type_available(
                property_rec.id,
                reservation_type.accommodation_type_id.id,
                start,
                end,
            )
        elif property_rec.accommodation_type_ids:
            available = any(
                Reservation.is_accommodation_type_available(
                    property_rec.id, accommodation_type.id, start, end
                )
                for accommodation_type in property_rec.accommodation_type_ids
                if accommodation_type.active
            )
        else:
            available = Reservation.is_accommodation_type_available(
                property_rec.id, False, start, end
            )
        return {"available": available}

    @http.route(
        ["/property/<int:property_id>/add_to_cart"],
        type="jsonrpc",
        auth="public",
        website=True,
        methods=["POST"],
    )
    def property_add_to_cart(
        self,
        property_id,
        date_start=None,
        date_end=None,
        reservation_type_id=None,
        guests=None,
        **kwargs,
    ):
        pms_property = request.env["pms.property"].sudo().browse(property_id)
        if (
            not pms_property.exists()
            or not pms_property.can_access_from_current_website()
        ):
            return {"error": _("Property not found"), "redirect": "/property"}

        if request.env.user._is_public():
            return {
                "error": _("Login required"),
                "redirect": f"/web/login?redirect={pms_property.website_url}",
            }

        try:
            start = datetime.strptime(date_start or "", "%Y-%m-%d")
            end = datetime.strptime(date_end or "", "%Y-%m-%d")
        except ValueError:
            return {"error": _("Invalid dates")}
        if start >= end:
            return {"error": _("Check-out must be after check-in")}

        try:
            reservation_type_id = int(reservation_type_id or 0)
        except (TypeError, ValueError):
            return {"error": _("Invalid reservation type")}
        reservation_type = (
            request.env["pms.property.reservation"]
            .sudo()
            .browse(reservation_type_id)
        )
        if not reservation_type.exists():
            return {"error": _("Invalid reservation type")}
        if reservation_type.property_id and reservation_type.property_id != pms_property:
            return {"error": _("Invalid reservation type")}
        accommodation_type = reservation_type.accommodation_type_id
        if (
            accommodation_type
            and accommodation_type.property_id != pms_property
        ):
            return {"error": _("Invalid accommodation type")}

        guests = [
            guest
            for guest in (guests or [])
            if isinstance(guest, dict)
            and isinstance(guest.get("name"), str)
            and guest["name"].strip()
        ]
        if not guests:
            return {"error": _("At least one guest is required")}
        max_guests = (
            accommodation_type.capacity or pms_property.no_of_guests
            if accommodation_type
            else pms_property.no_of_guests
        )
        if max_guests and len(guests) > max_guests:
            return {"error": _("Too many guests for this accommodation")}
        duration = (end - start).days
        if pms_property.min_nights and duration < pms_property.min_nights:
            return {"error": _("Reservation does not meet the minimum stay")}
        if pms_property.max_nights and duration > pms_property.max_nights:
            return {"error": _("Reservation exceeds the maximum stay")}

        Reservation = request.env["pms.reservation"].sudo()
        if not Reservation.is_accommodation_type_available(
            pms_property.id, accommodation_type.id, start, end
        ):
            return {
                "error": _("Accommodation is not available for those dates")
            }

        reservation = (
            Reservation
            .create(
                {
                    "property_id": pms_property.id,
                    "reservation_type_id": reservation_type.id,
                    "accommodation_type_id": accommodation_type.id,
                    "start": start,
                    "stop": end,
                    "stage_id": request.env.ref("pms_sale.pms_stage_booked").id,
                    "guest_ids": [(0, 0, g) for g in guests],
                    "partner_id": request.env.user.partner_id.id,
                }
            )
        )
        order = request.cart or request.website._create_cart()
        request.env["sale.order.line"].sudo().create(
            {
                "order_id": order.id,
                "product_id": reservation_type.product_id.id,
                "product_uom_qty": duration,
                "price_unit": reservation_type.price,
                "pms_reservation_id": reservation.id,
            }
        )
        return {"redirect": "/shop/cart"}
