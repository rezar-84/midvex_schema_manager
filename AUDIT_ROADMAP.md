# Midvex Schema Manager Product Audit and Roadmap

This roadmap tracks the public-release readiness assessment for the Odoo 19 module.

## Assessment Summary

The module has a solid core: JSON-LD output is serialized with `json.dumps`, rendering is read-only, schema records are scoped by website/language/active state, and manager-only ACLs protect editing. The most important remaining product constraint is editorial safety: structured data must represent content visible on the target page. The module should help managers avoid hidden FAQ, fake review, stale product, or unrelated local-business markup.

## Implemented In This Audit Branch

- Hardened configuration import with size limits, archive-member limits, known CSV dataset filtering, safer workbook internal path handling, and XML parse errors converted to `ValidationError`.
- Tightened template JSON validation so default structures must be JSON objects, required/optional fields must be arrays, and mapping/rules fields must be objects.
- Updated Article and BlogPosting templates to require nested `author.name` instead of accepting a non-empty `author` object with a blank name.
- Included the existing token/mapping test module in the test package.
- Added focused tests for import limits, malformed workbook handling, and template JSON shape validation.
- Documented language-specific auto-fill fallback, import limits, and visible-content requirements.

## High Priority Roadmap

1. Add record rules for multi-website deployments.
   ACLs currently restrict by group, but record rules are default-allow once ACL access is granted. Add website-scoped record rules if non-admin managers should be limited to selected websites.

2. Add visible-content guardrails.
   Add explicit confirmation fields for FAQPage, Review, Product, and LocalBusiness templates that require managers to confirm matching visible content before activation.

3. Add Review and AggregateRating as deliberate product features.
   Do not auto-generate reviews. Support them only from real Odoo review/rating sources or manually entered visible reviews, with validation warnings when no review source is configured.

4. Improve breadcrumb generation.
   Replace URL-segment capitalization with website menu/category lookup where possible. Keep the current URL fallback only when no menu/category match exists.

5. Add schema composition guidance in UI.
   Make it clearer that multiple schema records can attach to the same page/URL, one per schema type, and that FAQ/Breadcrumb/Product/Article records should remain separate unless a template intentionally models a nested entity.

## Medium Priority Roadmap

1. Add richer validators per schema type.
   Product: price/currency consistency, availability enum, image URL format.
   Article/BlogPosting: headline, image, author.name, datePublished, dateModified.
   LocalBusiness: address, phone, opening hours, geo coordinate numeric ranges.

2. Add preview of final rendered page schema bundle.
   Provide one backend action that shows the complete set of JSON-LD scripts that would render for a page, including global, static, URL, and dynamic mapping output.

3. Add import dry-run.
   Show counts and conflicts before writing settings/templates/mappings.

4. Add coverage report status for custom URLs.
   The report now includes custom URL schemas; next step is surfacing whether the URL resolves successfully and whether a website page exists for it.

5. Add model mapping diagnostics.
   Show unresolved Odoo field names, unknown tokens, and sample output against a selected record.

## Lower Priority Roadmap

1. Add a guided schema creation flow by page type.
   Example: Contact page suggests ContactPage + BreadcrumbList; product page suggests Product + BreadcrumbList; article page suggests Article/BlogPosting + BreadcrumbList.

2. Add documentation screenshots after UI stabilizes.

3. Add migration notes for Odoo 17/18/19 differences in group fields and list view tags.

4. Add optional support for `website_sale` product offer data when the dependency is installed.

## Release Checklist

- Run Odoo module install and upgrade tests on a clean Odoo 19 database.
- Run tagged module tests.
- Validate sample output with Schema Markup Validator and Google Rich Results Test.
- Confirm no public/portal ACL grants exist for manager-only models.
- Review all controller routes for auth, CSRF semantics, and use of `sudo`.
- Test import limits with malformed ZIP/XLSX files.
