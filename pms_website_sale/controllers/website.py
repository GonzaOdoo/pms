# Copyright (c) 2021 Gray Matter Logic
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
import math
import re
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
    @staticmethod
    def _parse_search_date(value):
        for date_format in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
            try:
                return datetime.strptime(value.strip(), date_format)
            except ValueError:
                continue
        return None

    def _get_property_search_domain(self, search, category, guest, args):
        domain = []
        domain += [("is_published", "=", True)]
        if search:
            domain += [("city", "ilike", search)]
        property_type = args.get("property_type")
        if property_type in ("house", "hotel"):
            domain.append(("property_type", "=", property_type))
        amenity_ids = args.get("amenity_ids", [])
        if not isinstance(amenity_ids, (list, tuple)):
            amenity_ids = [amenity_ids] if amenity_ids else []
        valid_amenity_ids = []
        for amenity_id in amenity_ids:
            try:
                valid_amenity_ids.append(int(amenity_id))
            except (TypeError, ValueError):
                continue
        for amenity_id in valid_amenity_ids:
            domain.extend(
                [
                    "|",
                    "|",
                    ("amenity_ids", "in", [amenity_id]),
                    ("accommodation_type_ids.amenity_ids", "in", [amenity_id]),
                    ("room_ids.amenity_ids", "in", [amenity_id]),
                ]
            )
        if category:
            domain += [("property_category_ids", "child_of", category.id)]
        domain += [("property_child_ids", "=", False)]
        domain += [("setup_state", "=", "ready")]

        has_detailed_occupancy = "adults" in args or "children" in args
        if has_detailed_occupancy:
            try:
                adults = int(args.get("adults", 2) or 0)
                children = int(args.get("children", 0) or 0)
                requested_rooms = int(args.get("rooms", 1) or 1)
            except (TypeError, ValueError):
                return domain + [("id", "=", 0)]
            if adults < 1 or children < 0 or requested_rooms < 1:
                return domain + [("id", "=", 0)]
            guest_count = adults + children
        else:
            try:
                guest_count = int(guest) if guest else 0
                requested_rooms = int(args.get("rooms", 1) or 1)
            except (TypeError, ValueError):
                return domain + [("id", "=", 0)]
            if guest_count < 0 or requested_rooms < 1:
                return domain + [("id", "=", 0)]

        pets_required = str(args.get("pets", "")).lower() in (
            "1",
            "true",
            "on",
        )
        work_required = str(args.get("work", "")).lower() in (
            "1",
            "true",
            "on",
        )
        if pets_required:
            pets_amenity = request.env.ref(
                "pms_base.pms_amenity_pets_allowed"
            )
            domain.extend(
                [
                    "|",
                    "|",
                    ("amenity_ids", "in", [pets_amenity.id]),
                    ("accommodation_type_ids.amenity_ids", "in", [pets_amenity.id]),
                    ("room_ids.amenity_ids", "in", [pets_amenity.id]),
                ]
            )
        if work_required:
            workspace_amenity = request.env.ref(
                "pms_base.pms_amenity_dedicated_workspace"
            )
            domain.extend(
                [
                    "|",
                    "|",
                    ("amenity_ids", "in", [workspace_amenity.id]),
                    (
                        "accommodation_type_ids.amenity_ids",
                        "in",
                        [workspace_amenity.id],
                    ),
                    ("room_ids.amenity_ids", "in", [workspace_amenity.id]),
                ]
            )

        if has_detailed_occupancy:
            adults_for_form = adults
            children_for_form = children
        else:
            adults_for_form = guest_count or 2
            children_for_form = 0
        rooms_for_form = requested_rooms

        start = stop = False
        date_values = []
        if "date_start" in args or "date_end" in args:
            raw_start = args.get("date_start", "").strip()
            raw_stop = args.get("date_end", "").strip()
            if raw_start or raw_stop:
                if not raw_start or not raw_stop:
                    return domain + [("id", "=", 0)]
                date_values = [raw_start, raw_stop]
        elif args.get("date_range"):
            date_range = args["date_range"].split(" - ", 1)
            if len(date_range) != 2:
                date_range = args["date_range"].split(" – ", 1)
            if len(date_range) != 2:
                date_match = re.fullmatch(
                    r"(\d{1,2}/\d{1,2}/\d{4})-(\d{1,2}/\d{1,2}/\d{4})",
                    args["date_range"],
                )
                date_range = list(date_match.groups()) if date_match else []
            if len(date_range) != 2:
                return domain + [("id", "=", 0)]
            date_values = date_range
        if date_values:
            parsed_dates = [
                self._parse_search_date(value) for value in date_values
            ]
            if any(not parsed_date for parsed_date in parsed_dates):
                return domain + [("id", "=", 0)]
            start, stop = parsed_dates
            if start >= stop:
                return domain + [("id", "=", 0)]

        properties = request.env["pms.property"].sudo().search(domain)
        Reservation = request.env["pms.reservation"].sudo()
        available_property_ids = []
        for property_rec in properties:
            if property_rec.property_type == "hotel":
                accommodation_types = property_rec.accommodation_type_ids.filtered(
                    lambda accommodation_type: accommodation_type.active
                    and (
                        not accommodation_type.capacity
                        or accommodation_type.capacity
                        >= math.ceil(guest_count / requested_rooms)
                    )
                )
                is_available = False
                for accommodation_type in accommodation_types:
                    room_domain = [
                        ("property_id", "=", property_rec.id),
                        ("accommodation_type_id", "=", accommodation_type.id),
                        ("active", "=", True),
                    ]
                    physical_room_count = request.env["pms.room"].sudo().search_count(
                        room_domain
                    )
                    available_room_count = physical_room_count
                    if start:
                        if not Reservation.is_accommodation_type_available(
                            property_rec.id,
                            accommodation_type.id,
                            start,
                            stop,
                        ):
                            continue
                        booking_domain = Reservation._get_active_overlap_domain(
                            property_rec.id, start, stop
                        ) + [("accommodation_type_id", "=", accommodation_type.id)]
                        booked_count = Reservation.search_count(booking_domain)
                        available_room_count -= booked_count
                    if available_room_count >= requested_rooms:
                        is_available = True
                        break
            elif property_rec.accommodation_type_ids:
                accommodation_types = property_rec.accommodation_type_ids.filtered(
                    lambda accommodation_type: accommodation_type.active
                    and (
                        not accommodation_type.capacity
                        or accommodation_type.capacity >= guest_count
                    )
                )
                is_available = requested_rooms == 1 and bool(accommodation_types)
                if is_available and start:
                    is_available = any(
                        Reservation.is_accommodation_type_available(
                            property_rec.id,
                            accommodation_type.id,
                            start,
                            stop,
                        )
                        for accommodation_type in accommodation_types
                    )
            else:
                is_available = (
                    requested_rooms == 1
                    and (
                        not property_rec.no_of_guests
                        or property_rec.no_of_guests >= guest_count
                    )
                    and (
                        not start
                        or Reservation.is_accommodation_type_available(
                            property_rec.id, False, start, stop
                        )
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
        website = request.env.website
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
            ppg = website.shop_ppg or 20

        ppr = website.shop_ppr or 4

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

        raw_amenity_ids = request.httprequest.args.getlist("amenity_ids")
        selected_amenity_ids = []
        for raw_id in raw_amenity_ids or (
            post.get("amenity_ids", [])
            if isinstance(post.get("amenity_ids", []), (list, tuple))
            else [post.get("amenity_ids")]
        ):
            try:
                selected_amenity_ids.append(int(raw_id))
            except (TypeError, ValueError):
                continue

        if category:
            url = f"/property/category/{request.env['ir.http']._slug(category)}"

        product_count = len(search_property)
        url_args = dict(post)
        if search:
            url_args["search"] = search
        if guest_select:
            url_args["guest_select"] = guest_select
        if category:
            url_args["category"] = category.id
        if raw_amenity_ids:
            url_args["amenity_ids"] = selected_amenity_ids
        pager = website.pager(
            url=url,
            total=product_count,
            page=page,
            step=ppg,
            scope=7,
            url_args=url_args,
        )
        offset = pager["offset"]
        properties = search_property[offset : offset + ppg]

        layout_mode = "grid"

        values = self._update_property_values(Property=Property, post=post)
        amenity_options = request.env["pms.amenity"].sudo().search(
            [("active", "=", True)], order="type_id, name"
        )
        amenity_filter_groups = [
            {
                "name": amenity_type.name,
                "amenities": amenity_options.filtered(
                    lambda amenity, item=amenity_type: amenity.type_id == item
                ),
            }
            for amenity_type in amenity_options.mapped("type_id")
        ]
        ungrouped_amenities = amenity_options.filtered(
            lambda amenity: not amenity.type_id
        )
        if ungrouped_amenities:
            amenity_filter_groups.append(
                {"name": "Otros", "amenities": ungrouped_amenities}
            )
        search_date_start = post.get("date_start", "")
        search_date_end = post.get("date_end", "")
        if not search_date_start and not search_date_end and post.get("date_range"):
            date_range = post["date_range"].split(" - ", 1)
            if len(date_range) != 2:
                date_range = post["date_range"].split(" – ", 1)
            if len(date_range) != 2:
                date_match = re.fullmatch(
                    r"(\d{1,2}/\d{1,2}/\d{4})-(\d{1,2}/\d{1,2}/\d{4})",
                    post["date_range"],
                )
                date_range = list(date_match.groups()) if date_match else []
            if len(date_range) == 2:
                parsed_dates = [
                    self._parse_search_date(value) for value in date_range
                ]
                if all(parsed_dates):
                    search_date_start, search_date_end = [
                        parsed_date.strftime("%Y-%m-%d")
                        for parsed_date in parsed_dates
                    ]
        has_detailed_occupancy = "adults" in post or "children" in post
        try:
            if has_detailed_occupancy:
                adults_for_form = int(post.get("adults", 2) or 0)
                children_for_form = int(post.get("children", 0) or 0)
            else:
                adults_for_form = int(guest_select) if guest_select else 2
                children_for_form = 0
            rooms_for_form = int(post.get("rooms", 1) or 1)
        except (TypeError, ValueError):
            adults_for_form, children_for_form, rooms_for_form = 2, 0, 1
        work_required = str(post.get("work", "")).lower() in (
            "1",
            "true",
            "on",
        )
        pets_required = str(post.get("pets", "")).lower() in (
            "1",
            "true",
            "on",
        )
        # properties
        values.update(
            {
                "category": category,
                "search_city": search,
                "search_guest": (
                    adults_for_form + children_for_form
                    if has_detailed_occupancy
                    else guest_select
                ),
                "search_raneg": post.get("date_range"),
                "search_date_start": search_date_start,
                "search_date_end": search_date_end,
                "search_adults": adults_for_form,
                "search_children": children_for_form,
                "search_rooms": rooms_for_form,
                "search_work": work_required,
                "search_pets": pets_required,
                "search_occupancy": (
                    f"{adults_for_form} adultos · {children_for_form} niños · "
                    f"{rooms_for_form} habitaciones"
                ),
                "selected_property_type": post.get("property_type", ""),
                "selected_amenity_ids": selected_amenity_ids,
                "amenity_filter_groups": amenity_filter_groups,
                "property_types": [
                    ("house", "Casa o apartamento"),
                    ("hotel", "Hotel"),
                ],
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
    def _effective_reservation_types(self, property_rec):
        Offer = request.env["pms.property.reservation"].sudo()
        property_scope = [("property_id", "in", [False, property_rec.id])]

        def scoped_offers(domain):
            return Offer.search(property_scope + domain, order="property_id desc, id")

        if property_rec.property_type != "hotel":
            general_offer_domain = [("accommodation_type_id", "=", False)]
            property_offers = scoped_offers(
                general_offer_domain + [("property_id", "=", property_rec.id)]
            )
            offers = property_offers or scoped_offers(
                general_offer_domain + [("property_id", "=", False)]
            )
            return [
                {
                    "offer": offer,
                    "accommodation_type": request.env["pms.accommodation.type"],
                    "is_fallback": False,
                }
                for offer in offers
            ]

        accommodation_types = property_rec.sudo().accommodation_type_ids.filtered(
            "active"
        )
        options = []
        if accommodation_types:
            general_offers = scoped_offers([("accommodation_type_id", "=", False)])
            for accommodation_type in accommodation_types:
                offers = scoped_offers(
                    [("accommodation_type_id", "=", accommodation_type.id)]
                )
                is_fallback = not offers
                for offer in offers or general_offers:
                    options.append(
                        {
                            "offer": offer,
                            "accommodation_type": accommodation_type,
                            "is_fallback": is_fallback,
                        }
                    )
            return options
        return options

    def _resolve_reservation_offer(
        self, property_rec, reservation_type_id, accommodation_type_id=None
    ):
        offer = (
            request.env["pms.property.reservation"]
            .sudo()
            .browse(reservation_type_id)
            .exists()
        )
        if not offer or (offer.property_id and offer.property_id != property_rec):
            return None, None

        if (
            property_rec.property_type != "hotel"
            and offer.accommodation_type_id
        ):
            return None, None

        if offer.accommodation_type_id:
            accommodation_type = offer.accommodation_type_id
            if (
                not accommodation_type.active
                or (
                    accommodation_type_id
                    and accommodation_type.id != accommodation_type_id
                )
            ):
                return None, None
        elif property_rec.property_type == "hotel":
            accommodation_type = (
                request.env["pms.accommodation.type"]
                .sudo()
                .browse(accommodation_type_id)
                .exists()
            )
            if (
                not accommodation_type
                or not accommodation_type.active
                or accommodation_type.property_id != property_rec
            ):
                return None, None
            specific_offer = request.env["pms.property.reservation"].sudo().search(
                [
                    ("property_id", "in", [False, property_rec.id]),
                    ("accommodation_type_id", "=", accommodation_type.id),
                ],
                limit=1,
            )
            if specific_offer:
                return None, None
        else:
            accommodation_type = request.env["pms.accommodation.type"]

        if (
            accommodation_type
            and accommodation_type.property_id != property_rec
        ):
            return None, None
        return offer, accommodation_type

    def _prepare_property_values(self, pms_property, category, search, **kwargs):
        values = super()._prepare_property_values(
            pms_property, category, search, **kwargs
        )
        values["reservation_types"] = self._effective_reservation_types(pms_property)
        values["hotel_room_options"] = self._get_hotel_room_options(
            pms_property, values["reservation_types"]
        )
        values["is_public_user"] = request.env.user._is_public()
        return values

    def _get_hotel_room_options(self, property_rec, reservation_types=None):
        if property_rec.property_type != "hotel":
            return []
        reservation_types = reservation_types or self._effective_reservation_types(
            property_rec
        )
        options = []
        for accommodation_type in property_rec.sudo().accommodation_type_ids.filtered(
            "active"
        ):
            matching_rates = [
                item
                for item in reservation_types
                if item["accommodation_type"] == accommodation_type
            ]
            if not matching_rates:
                continue
            room_count = len(accommodation_type.room_ids.filtered("active"))
            if not room_count:
                continue
            offer = matching_rates[0]["offer"]
            has_custom_price = accommodation_type.has_custom_price
            options.append(
                {
                    "accommodation_type": accommodation_type,
                    "offer": offer,
                    "price": (
                        accommodation_type.price
                        if has_custom_price
                        else offer.price
                    ),
                    "currency": (
                        accommodation_type.currency_id
                        if has_custom_price
                        else offer.currency_id
                    ),
                    "room_count": room_count,
                    "max_guests": (
                        accommodation_type.capacity or property_rec.no_of_guests
                    ),
                    "is_fallback": (
                        matching_rates[0]["is_fallback"] and not has_custom_price
                    ),
                }
            )
        return options

    def _get_hotel_room_availability(
        self, property_rec, accommodation_type, start, end
    ):
        Reservation = request.env["pms.reservation"].sudo()
        if not Reservation.is_accommodation_type_available(
            property_rec.id, accommodation_type.id, start, end
        ):
            return 0
        physical_room_count = request.env["pms.room"].sudo().search_count(
            [
                ("property_id", "=", property_rec.id),
                ("accommodation_type_id", "=", accommodation_type.id),
                ("active", "=", True),
            ]
        )
        booked_room_count = Reservation.search_count(
            Reservation._get_active_overlap_domain(property_rec.id, start, end)
            + [("accommodation_type_id", "=", accommodation_type.id)]
        )
        return max(physical_room_count - booked_room_count, 0)

    def _resolve_hotel_room_selection(
        self, property_rec, accommodation_type_id, reservation_type_id=None
    ):
        try:
            accommodation_type_id = int(accommodation_type_id)
        except (TypeError, ValueError):
            return None
        room_option = next(
            (
                option
                for option in self._get_hotel_room_options(property_rec)
                if option["accommodation_type"].id == accommodation_type_id
            ),
            None,
        )
        if not room_option:
            return None
        if reservation_type_id:
            try:
                reservation_type_id = int(reservation_type_id)
            except (TypeError, ValueError):
                return None
            if room_option["offer"].id != reservation_type_id:
                return None
        return room_option

    def _check_hotel_availability(self, property_rec, accommodations, start, end):
        if not isinstance(accommodations, list) or not accommodations:
            return {"available": False, "error": _("Select at least one room type")}
        seen_types = set()
        for selection in accommodations:
            if not isinstance(selection, dict):
                return {"available": False, "error": _("Invalid room selection")}
            option = self._resolve_hotel_room_selection(
                property_rec,
                selection.get("accommodation_type_id"),
                selection.get("reservation_type_id"),
            )
            try:
                quantity = int(selection.get("quantity") or 0)
            except (TypeError, ValueError):
                return {"available": False, "error": _("Invalid room quantity")}
            if (
                not option
                or quantity < 1
                or option["accommodation_type"].id in seen_types
            ):
                return {"available": False, "error": _("Invalid room selection")}
            seen_types.add(option["accommodation_type"].id)
            available_count = self._get_hotel_room_availability(
                property_rec, option["accommodation_type"], start, end
            )
            if available_count < quantity:
                return {"available": False}
        return {"available": True}

    def _create_hotel_booking(self, property_rec, accommodations, start, end):
        if not isinstance(accommodations, list) or not accommodations:
            return {"error": _("Select at least one room type")}
        booking_plan = []
        seen_types = set()
        for selection in accommodations:
            if not isinstance(selection, dict):
                return {"error": _("Invalid room selection")}
            room_option = self._resolve_hotel_room_selection(
                property_rec,
                selection.get("accommodation_type_id"),
                selection.get("reservation_type_id"),
            )
            rooms = selection.get("rooms")
            if (
                not room_option
                or not isinstance(rooms, list)
                or not rooms
                or room_option["accommodation_type"].id in seen_types
            ):
                return {"error": _("Invalid room selection")}
            if len(rooms) > room_option["room_count"]:
                return {"error": _("Not enough rooms are available for those dates")}
            seen_types.add(room_option["accommodation_type"].id)
            accommodation_type = room_option["accommodation_type"]
            available_count = self._get_hotel_room_availability(
                property_rec, accommodation_type, start, end
            )
            if available_count < len(rooms):
                return {"error": _("Not enough rooms are available for those dates")}
            max_guests = room_option["max_guests"]
            for room in rooms:
                if not isinstance(room, dict):
                    return {"error": _("Invalid guest details")}
                room_guests = room.get("guests")
                if not isinstance(room_guests, list):
                    return {"error": _("Invalid guest details")}
                guests = []
                for guest in room_guests:
                    if not (
                        isinstance(guest, dict)
                        and isinstance(guest.get("name"), str)
                        and guest["name"].strip()
                    ):
                        continue
                    guests.append(
                        {
                            "name": guest["name"].strip(),
                            "phone": (
                                guest.get("phone")
                                if isinstance(guest.get("phone"), str)
                                else False
                            ),
                            "email": (
                                guest.get("email")
                                if isinstance(guest.get("email"), str)
                                else False
                            ),
                        }
                    )
                if not guests:
                    return {"error": _("At least one guest is required per room")}
                if max_guests and len(guests) > max_guests:
                    return {"error": _("Too many guests for this room type")}
                booking_plan.append(
                    {
                        "option": room_option,
                        "guests": guests,
                    }
                )

        Reservation = request.env["pms.reservation"].sudo()
        stage_booked = request.env.ref("pms_sale.pms_stage_booked")
        reservations = []
        duration = (end - start).days
        for booking in booking_plan:
            room_option = booking["option"]
            reservation = Reservation.create(
                {
                    "property_id": property_rec.id,
                    "reservation_type_id": room_option["offer"].id,
                    "accommodation_type_id": room_option["accommodation_type"].id,
                    "start": start,
                    "stop": end,
                    "stage_id": stage_booked.id,
                    "guest_ids": [(0, 0, guest) for guest in booking["guests"]],
                    "partner_id": request.env.user.partner_id.id,
                }
            )
            reservations.append((reservation, room_option, duration))

        website = request.env.website
        order = request.cart or website._create_cart()
        for reservation, room_option, nights in reservations:
            request.env["sale.order.line"].sudo().create(
                {
                    "order_id": order.id,
                    "product_id": room_option["offer"].product_id.id,
                    "product_uom_qty": nights,
                    "price_unit": room_option["price"],
                    "pms_reservation_id": reservation.id,
                }
            )
        return {"redirect": "/shop/checkout"}

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
        accommodation_type_id=None,
        accommodations=None,
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
        if property_rec.setup_state != "ready":
            return {"available": False, "error": _("Property setup is not complete")}

        duration = (end - start).days
        if property_rec.min_nights and duration < property_rec.min_nights:
            return {
                "available": False,
                "error": _("Reservation does not meet the minimum stay"),
            }
        if property_rec.max_nights and duration > property_rec.max_nights:
            return {
                "available": False,
                "error": _("Reservation exceeds the maximum stay"),
            }
        if property_rec.property_type == "hotel" and accommodations is not None:
            return self._check_hotel_availability(
                property_rec, accommodations, start, end
            )

        Reservation = request.env["pms.reservation"].sudo()
        if reservation_type_id:
            try:
                reservation_type_id = int(reservation_type_id)
            except (TypeError, ValueError):
                return {
                    "available": False,
                    "error": _("Invalid reservation type"),
                }
            try:
                accommodation_type_id = int(accommodation_type_id or 0) or None
            except (TypeError, ValueError):
                return {"available": False, "error": _("Invalid accommodation type")}
            reservation_type, accommodation_type = self._resolve_reservation_offer(
                property_rec, reservation_type_id, accommodation_type_id
            )
            if not reservation_type:
                return {
                    "available": False,
                    "error": _("Invalid reservation type"),
                }
            available = Reservation.is_accommodation_type_available(
                property_rec.id,
                accommodation_type.id if accommodation_type else False,
                start,
                end,
            )
        elif property_rec.property_type == "hotel":
            available = False
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
        accommodation_type_id=None,
        guests=None,
        accommodations=None,
        **kwargs,
    ):
        pms_property = request.env["pms.property"].sudo().browse(property_id)
        if (
            not pms_property.exists()
            or pms_property.setup_state != "ready"
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

        duration = (end - start).days
        if pms_property.min_nights and duration < pms_property.min_nights:
            return {"error": _("Reservation does not meet the minimum stay")}
        if pms_property.max_nights and duration > pms_property.max_nights:
            return {"error": _("Reservation exceeds the maximum stay")}
        if pms_property.property_type == "hotel" and accommodations is not None:
            return self._create_hotel_booking(
                pms_property, accommodations, start, end
            )

        try:
            reservation_type_id = int(reservation_type_id or 0)
        except (TypeError, ValueError):
            return {"error": _("Invalid reservation type")}
        try:
            accommodation_type_id = int(accommodation_type_id or 0) or None
        except (TypeError, ValueError):
            return {"error": _("Invalid accommodation type")}
        reservation_type, accommodation_type = self._resolve_reservation_offer(
            pms_property, reservation_type_id, accommodation_type_id
        )
        if not reservation_type:
            return {"error": _("Invalid reservation type")}

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
        Reservation = request.env["pms.reservation"].sudo()
        if not Reservation.is_accommodation_type_available(
            pms_property.id,
            accommodation_type.id if accommodation_type else False,
            start,
            end,
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
                    "accommodation_type_id": accommodation_type.id
                    if accommodation_type
                    else False,
                    "start": start,
                    "stop": end,
                    "stage_id": request.env.ref("pms_sale.pms_stage_booked").id,
                    "guest_ids": [(0, 0, g) for g in guests],
                    "partner_id": request.env.user.partner_id.id,
                }
            )
        )
        website = request.env.website
        order = request.cart or website._create_cart()
        request.env["sale.order.line"].sudo().create(
            {
                "order_id": order.id,
                "product_id": reservation_type.product_id.id,
                "product_uom_qty": duration,
                "price_unit": reservation_type.price,
                "pms_reservation_id": reservation.id,
            }
        )
        return {"redirect": "/shop/checkout"}
