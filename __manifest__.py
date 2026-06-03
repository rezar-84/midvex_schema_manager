{
    'name': 'Midvex Schema Manager',
    'version': '19.0.1.0.0',
    'summary': 'Manage JSON-LD structured data across Odoo websites',
    'description': """
Midvex Schema Manager
=====================
A reusable Odoo 19 module for managing JSON-LD structured data across Odoo websites.
Complements Odoo native SEO (meta title, description, keywords) with JSON-LD injection.

Features:
- Global Organization / WebSite schema per website
- Page-specific and URL-specific schema records
- Language-specific schema records with one-click bulk language wizard
- Schema template library with 12 built-in types + custom template support
- Manual JSON override for admins (validated on save)
- Auto-fill from page SEO metadata
- Internal JSON-LD validation with Google Rich Results Test link
- Duplicate schema detection and warnings
- QWeb injection into website <head> via website.layout inheritance
- Scheduled daily regeneration of all active schemas
- Chatter / activity tracking on schema records
    """,
    'author': 'Midvex.com / Reza Rezaei',
    'website': 'https://midvex.com',
    'license': 'LGPL-3',
    'category': 'Website/SEO',
    'depends': [
        'website',
        'web',
        'mail',
    ],
    'data': [
        # 1. Groups must be defined before ACL
        'security/groups.xml',
        'security/ir.model.access.csv',
        # 2. Seed data
        'data/schema_template_data.xml',
        'data/schema_cron.xml',
        # 3. Backend views (actions before menus)
        'views/schema_settings_views.xml',
        'views/schema_template_views.xml',
        'views/schema_record_views.xml',
        'views/schema_lang_wizard_views.xml',
        'views/schema_menu.xml',
        # 4. Website frontend injection (last — extends website.layout)
        'views/schema_website_injection.xml',
    ],
    'assets': {
        'web.assets_backend': [],
        'website.assets_frontend': [],
    },
    'images': ['static/description/icon.png'],
    'installable': True,
    'application': False,
    'auto_install': False,
}
