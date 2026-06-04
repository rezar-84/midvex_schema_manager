# Midvex Schema Manager

**Version:** 19.0.1.1.0 | **License:** LGPL-3 | **Author:** Midvex.com / Reza Rezaei

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

### Step 1 — Global Website Schema (recommended first)

Navigate to **Website → Configuration → Structured Data → Global Website Schema**.

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

## Creating Your First Page Schema

1. Go to **Website → Configuration → Structured Data → Create Page Schema** for the guided wizard, or **Page Schemas** for the full editor.
2. Click **New**.
3. Select **Schema Template** first, for example `Product`, `FAQPage`, `BreadcrumbList`, `Article`, or `Service`.
   - Schema Type is filled automatically from the template.
   - Required field rows are created automatically.
4. Choose **Target Type**:
   - `Global` — rendered on every page. Use rarely; Organization/WebSite is usually handled by Global Website Schema.
   - `Website Page` — select a specific Odoo website page. The target URL is suggested from the page URL.
   - `Custom URL` — enter `/about`, `/tr/about`, or `https://example.com/about`.
5. Set **Language Code** (e.g. `en`, `no`, `de`).
6. Fill in the **Fields** tab with values, or add FAQ/Breadcrumb items when using those templates.
7. Click **Validate** to run the internal validator.
8. The record is injected on the next page load when **Active** is checked.

The form shows a resolved URL preview and a validation banner near the top so you can see where the schema renders and whether it needs attention.

**Render URL / Target URL** controls where the schema is rendered. A field named **Schema URL / Canonical URL** controls the `url` value inside JSON-LD. These are often the same page URL, but they are separate concepts.

Language is set once on the parent Page Schema record. Child field, FAQ, and breadcrumb lines do not show language in the normal UI.

Templates can mark **Load optional fields by default**. This loads useful optional fields automatically, while **Add Optional Fields** still adds missing optional rows later without duplicates. **Reset Fields from Template** rebuilds rows from the selected template.

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

Buttons on the form:
- **Open Schema Markup Validator** → [validator.schema.org](https://validator.schema.org/)
- **Open Google Rich Results Test** → pre-filled with the record's target URL
- **Format JSON** / **Validate JSON** → available in advanced JSON areas

### Admin JSON Preview

`GET /schema-preview/<record_id>` — returns the raw `generated_json` as
`application/json`. Requires **Schema Manager** group.

---

## Template Library

Built-in system templates (cannot be deleted, only deactivated):

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
| 13 | LocalBusiness | Local SEO for physical businesses |
| 14 | ProfessionalService | Service-provider local business schema |
| 15 | Place | Physical place with address and geo |
| 16 | Google Merchant Product Schema | Product checklist template for Merchant readiness |
| 17 | PostalAddress | Address component schema |
| 18 | OpeningHoursSpecification | Opening hours component schema |
| 19 | GeoCoordinates | Latitude/longitude component schema |
| 20 | ContactPoint | Contact type, phone, email and available language schema |
| 21 | MedicalBusiness | Medical provider local business schema |
| 22 | Dentist | Dental clinic/provider schema |

Open **Website → Configuration → Structured Data → Template Library** to browse templates in a kanban library. Each card shows the schema type, description, required field count, and whether the template is system or custom.

Use **Use This Template** to create a new Page Schema with the template preselected. Use **Duplicate Template** to create an editable custom copy.

### Custom Templates

Go to **Template Library** and click **New** or **Duplicate Template** on an existing template.
Custom templates can be freely edited, exported (copy JSON), or deactivated.
System templates show a warning in the editor; duplicate them before making custom changes.

## FAQPage and BreadcrumbList

FAQPage schema is manually managed. Add FAQ items only when the same questions and answers are visible on the target page; validation fails until at least one active FAQ item exists.

BreadcrumbList schema has editable breadcrumb lines. Use **Suggest Breadcrumbs from URL** to create Home plus one item per URL segment, then adjust names and URLs as needed. Validation warns when positions are not sequential.

## Batch Operations

Open **Website → Configuration → Structured Data → Batch Operations** to run safe backend maintenance:

- Validate all active schemas for a website
- Generate previews for all active schemas for a website
- Create translated schema records for all active website languages

These operations update backend validation status and cached previews. They do not change public rendering behavior.

## Coverage Report

Open **Website → Configuration → Structured Data → Coverage Report** to review website pages, attached schema types, validation status, and pages that need attention. Filters highlight pages without schema, pages with validation errors, warnings, and draft schemas.

## Tokens

Schema field values can use safe tokens. Tokens are resolved through a whitelist only; unknown tokens remain unchanged and produce validation warnings.

| Group | Tokens |
|---|---|
| Website | `{{ website.name }}`, `{{ website.domain }}` |
| Company | `{{ company.name }}`, `{{ company.email }}`, `{{ company.phone }}` |
| Page | `{{ page.name }}`, `{{ page.url }}`, `{{ page.meta_title }}`, `{{ page.meta_description }}` |
| Current Request | `{{ current.url }}`, `{{ current.path }}`, `{{ current.lang }}`, `{{ current.canonical_url }}` |
| Product, optional context | `{{ product.name }}`, `{{ product.description }}`, `{{ product.default_code }}`, `{{ product.price }}`, `{{ product.currency }}`, `{{ product.image_url }}`, `{{ product.website_url }}` |
| Blog, optional context | `{{ blog.name }}`, `{{ blog.subtitle }}`, `{{ blog.author }}`, `{{ blog.date_published }}`, `{{ blog.url }}`, `{{ blog.image_url }}` |

No Python expressions are evaluated.

## Model Mappings

Open **Website → Configuration → Structured Data → Model Mappings** to define reusable mappings from an Odoo model to schema dot-paths. Mapping lines support manual fallback values, whitelisted tokens, and direct Odoo field reads from the selected target record. Dot-paths such as `brand.@id` and `offers.priceSpecification.priceCurrency` build nested JSON safely.

---

## Security Notes

- Only users in **Schema Manager** group can create, edit, or publish schemas.
- All JSON output uses `json.dumps()` exclusively — no string concatenation.
- **Advanced JSON Override** is available only to Schema Managers. It fully replaces generated fields, FAQ items, and breadcrumbs when enabled.
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
2. Render Global Website Schema first as one `@graph` script when enabled.
3. Fetch active global Page Schema records for this website + language.
4. Match page records by raw path and language-normalized path, scoped to `website_id` when `website.page` supports it.
5. Match URL records by raw path, normalized path, absolute raw URL, and absolute normalized URL.
6. Sort all matched records by `priority desc`.
7. Call `build_schema_data()` and `_build_jsonld_script()` for each record.
8. Return concatenated `Markup` string.

The public request path never calls `generate_json()` or `render_html()` and does not write to the database.

### Global Website Schema

Global settings render Organization and WebSite nodes first in an `@graph`. The frontend output and backend preview use the same graph builder and include `@id`, `publisher`, and `availableLanguage` where configuration is available.

When SearchAction is enabled, the route is Odoo's website search route:

```text
/website/search?search={search_term_string}
```

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
