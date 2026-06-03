"""
Shared JSON-LD rendering helpers.

Module-level functions so they can be imported by any model file without
circular-import issues.  They contain no Odoo ORM dependencies.
"""
import json


def _safe_json_dumps(data):
    """
    Serialize data to JSON and escape characters that can break a <script> tag.

    After json.dumps(), three substitutions prevent script-injection:
        <  ->  \\u003c
        >  ->  \\u003e
        &  ->  \\u0026

    The result is still valid JSON / JSON-LD.
    ensure_ascii=False keeps UTF-8 characters readable in the page source.
    """
    raw = json.dumps(data, ensure_ascii=False, indent=2)
    raw = raw.replace('<', '\\u003c')
    raw = raw.replace('>', '\\u003e')
    raw = raw.replace('&', '\\u0026')
    return raw


def _build_jsonld_script(data):
    """
    Wrap a schema data dict in a safe <script type="application/ld+json"> block.

    All values pass through _safe_json_dumps so that nothing in a field value
    can inject arbitrary HTML or break out of the enclosing script tag.
    Manual JSON overrides are json.loads()-parsed before reaching this function,
    so raw string injection is impossible.
    """
    return '<script type="application/ld+json">\n' + _safe_json_dumps(data) + '\n</script>'
