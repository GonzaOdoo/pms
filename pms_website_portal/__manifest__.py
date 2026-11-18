{
    "name": "Turismo Social - Panel del proveedor",
    "summary": "Panel propio para que cada mutual administre propiedades, "
    "habitaciones y reservas desde el portal",
    "version": "20.0.1.0.0",
    "category": "Website",
    "author": "Recydes",
    "license": "AGPL-3",
    "depends": ["portal", "website", "pms_base", "pms_sale", "pms_website"],
    "data": [
        "security/res_groups.xml",
        "security/ir.access.csv",
        "views/layout.xml",
        "views/dashboard.xml",
        "views/properties.xml",
        "views/property_wizard.xml",
        "views/rooms.xml",
        "views/reservations.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "pms_website_portal/static/src/css/panel.css",
        ],
    },
    "installable": True,
}
