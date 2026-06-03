# Midvex Schema Manager

**Version:** 19.0.1.0.0 | **License:** LGPL-3 | **Author:** Midvex.com / Reza Rezaei

---

## Overview

Midvex Schema Manager is a reusable, general-purpose Odoo 19 module for managing
[JSON-LD structured data](https://json-ld.org/) across one or multiple Odoo websites.

It **complements** Odoo's native SEO tools (meta title, description, keywords) by injecting
`<script type="application/ld+json">` blocks into every page `<head>` automatically via
`website.layout` QWeb inheritance.

---

## Requirements

- Odoo 19 Enterprise (primary target) or Community (compatible)
- Core dependencies: `website`, `web`, `mail`
- Optional later: `website_sale`, `website_blog`, `product`

---

## Installation

1. Copy the `midvex_schema_manager` folder to your Odoo custom addons directory.
2. Restart the Odoo server.
3. Enable Developer Mode: **Settings → General Settings → Developer Tools → Activate Developer Mode**.
4. Go to **Apps**, search for "Midvex Schema Manager", and click **Install**.

---

## Configuration

### Step 1 — Global Settings (recommended first)

Navigate to **Website → Configuration → Structured Data → Global Settings**.

Create one settings record per website and fill in:

| Section | Fields |
|---|---|
| Organization | Name, Legal Name, Alternate Names, Logo URL, Website URL, Default Image |
| Contact | Email, Phone |
| Address | Street, City, Region, Postal Code, Country Code (ISO 3166-1 alpha-2) |
| Social Links | One URL per line (LinkedIn, Twitter, etc.) → injected as `sameAs` |
| Options | Enable Global Schema, Enable WebSite Schema, Enable SearchAction |

The **Preview** tab shows the JSON-LD that will be injected on every page.

### Step 2 — Security Groups

Assign users to groups via **Settings → Users & Companies → Groups**:

- **Schema User** — read-only access to all schema records
- **Schema Manager** — full create / edit / delete access

> Admin users bypass ACL automatically via `base.group_system`.

---

## Creating Your First Schema Record

1. Go to **Website → Configuration → Structured Data → Schema Records**.
2. Click **New**.
3. Set **Schema Type** (e.g. `Product`) and select a **Schema Template**.
   - The template onchange auto-populates required field rows.
4. Choose **Target Type**:
   - `Global` — injected on every page
   - `Website Page` — select a specific page from the dropdown
   - `Custom URL` — enter a path like `/about`
5. Set **Language Code** (e.g. `en`, `no`, `de`).
6. Fill in the **Fields** tab with values.
7. Click **Validate** to run the internal validator.
8. The record is injected on the next page load when **Active** is checked.

---

## Language Strategy

Midvex Schema Manager uses **separate schema records per language**, not Odoo field
translation. This aligns with Odoo's language URL strategy and `request.lang`.

**Uniqueness key:** `website_id + target_type + target_url + lang_code + schema_type`

### Create for All Languages

Use the **Create for All Languages** button on any schema record to open a wizard that
duplicates the record for each selected active language. Records that already exist for a
given language are skipped automatically.

### Auto-detect Language

The `render_schema_for_request()` method reads `request.lang.code` at render time and
returns only records matching the current language.

---

## Validation and Preview

### Internal Validator (click Validate)

- `@context` and `@type` present
- URL field format (`https://`)
- Language code format (BCP 47)
- **Product**: `name`, `description`, `image` required
- **FAQPage**: at least one active FAQ item required
- **BreadcrumbList**: sequential positions starting at 1
- Duplicate schema detection (same website / target / language / type)

### External Tools

Buttons on the **Validation** tab:
- **Open Schema Markup Validator** → [validator.schema.org](https://validator.schema.org/)
- **Open Google Rich Results Test** → pre-filled with the record's target URL

### Admin JSON Preview

`GET /schema-preview/<record_id>` — returns the raw `generated_json` as
`application/json`. Requires **Schema Manager** group.

---

## Template Library

12 built-in system templates (cannot be deleted, only deactivated):

| # | Schema Type | Use Case |
|---|---|---|
| 1 | Organization | Every website — identifies the organization |
| 2 | WebSite | Enables Sitelinks Searchbox in Google |
| 3 | Product | Product pages with price and availability |
| 4 | FAQPage | FAQ sections — requires FAQ items tab |
| 5 | BreadcrumbList | Breadcrumb trail — requires breadcrumb items tab |
| 6 | Article | News / editorial articles |
| 7 | BlogPosting | Blog posts |
| 8 | Service | Service pages |
| 9 | ContactPage | Contact us page |
| 10 | AboutPage | About / company page |
| 11 | CollectionPage | Category / listing pages |
| 12 | ItemList | Carousel-eligible lists |

### Custom Templates

Go to **Schema Templates** and click **New** or **Duplicate** an existing template.
Custom templates can be freely edited, exported (copy JSON), or deactivated.

---

## Security Notes

- Only users in **Schema Manager** group can create, edit, or publish schemas.
- All JSON output uses `json.dumps()` exclusively — no string concatenation.
- Manual JSON override is parsed and validated before saving (`@api.constrains`).
- Inactive schemas are never rendered.
- Wrong-language schemas are never rendered.
- The schema preview endpoint returns 403 for non-managers.
- `render_schema_for_request()` is always called with `.sudo()` but filters by
  `website_id`, `active`, and `lang_code` before rendering.

---

## Technical Notes

### QWeb Injection

`views/schema_website_injection.xml` inherits `website.layout` and injects into `<head>`:

```xml
<t t-out="request.env['midvex.schema.record'].sudo().render_schema_for_request(request)"/>
```

`t-out` is safe here because `render_schema_for_request()` returns `markupsafe.Markup`.

### render_schema_for_request Logic

1. Resolve current `website` and `lang_code` from `request`.
2. Fetch active global records for this website + language.
3. Match page records by `website.page.url == request.httprequest.path`.
4. Match URL records by `target_url == request.httprequest.path`.
5. Sort all matched records by `priority desc`, call `render_html()` on each.
6. Return concatenated `Markup` string.

### JSON Safety

Every JSON-LD block is built exclusively with `json.dumps()`:
- `generate_organization_json()` / `generate_website_json()` in `schema_settings.py`
- `_build_faqpage_json()` / `_build_breadcrumb_json()` / `_build_json_from_fields()` in `schema_record.py`
- Manual JSON is `json.loads()` validated on save before being stored

### Scheduled Regeneration

An `ir.cron` record runs `regenerate_all_active_schemas()` daily to keep
`generated_json`, `generated_html`, and `last_generated_at` fresh.

---

## Roadmap

### v1.1
- Auto-populate Product schema from `website_sale` product data
- Auto-populate BlogPosting schema from `website_blog` post data
- Bulk schema generation for all pages of a website
- Multi-website management dashboard

### v1.2
- AI-assisted field suggestion (based on page content)
- External validation API integration (Google / Schema.org)
- Advanced request-level caching with cache invalidation hooks
- Import / export full schema sets as JSON archives

---

## Author

**Midvex.com** — [https://midvex.com](https://midvex.com)
**Reza Rezaei**

License: [LGPL-3](https://www.gnu.org/licenses/lgpl-3.0.html)
