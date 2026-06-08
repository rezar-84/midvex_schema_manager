import re

from odoo import api, models


TOKEN_RE = re.compile(r'{{\s*([a-zA-Z0-9_.]+)\s*}}')


class MidvexSchemaToken(models.AbstractModel):
    _name = 'midvex.schema.token'
    _description = 'Midvex Schema Token Resolver'

    @api.model
    def _safe_get(self, record, field_name):
        if not record or not getattr(record, 'exists', lambda: False)():
            return ''
        if field_name not in record._fields:
            return ''
        value = record[field_name]
        if hasattr(value, 'display_name'):
            return value.display_name
        return value or ''

    @api.model
    def _record_url(self, website, path):
        if not path:
            return ''
        if path.startswith('http'):
            return path
        domain = (getattr(website, 'domain', '') or '').strip()
        if not domain:
            return path
        base = domain.rstrip('/') if domain.startswith('http') else 'https://' + domain.rstrip('/')
        return base + path

    @api.model
    def _resolvers(self, context):
        website = context.get('website')
        company = context.get('company') or (website.company_id if website and 'company_id' in website._fields else self.env.company)
        page = context.get('page')
        current = context.get('current') or {}
        product = context.get('product')
        blog = context.get('blog')

        return {
            'website.name': lambda: self._safe_get(website, 'name'),
            'website.domain': lambda: getattr(website, 'domain', '') or '',
            'company.name': lambda: self._safe_get(company, 'name'),
            'company.email': lambda: self._safe_get(company, 'email'),
            'company.phone': lambda: self._safe_get(company, 'phone'),
            'page.name': lambda: self._safe_get(page, 'name') or self._safe_get(getattr(page, 'view_id', False), 'name'),
            'page.url': lambda: self._record_url(website, self._safe_get(page, 'url')),
            'page.meta_title': lambda: self._safe_get(getattr(page, 'view_id', False), 'website_meta_title') or self._safe_get(getattr(page, 'view_id', False), 'name'),
            'page.meta_description': lambda: self._safe_get(getattr(page, 'view_id', False), 'website_meta_description'),
            'current.url': lambda: current.get('url', ''),
            'current.path': lambda: current.get('path', ''),
            'current.lang': lambda: current.get('lang', ''),
            'current.canonical_url': lambda: current.get('canonical_url', '') or current.get('url', ''),
            'product.name': lambda: self._safe_get(product, 'name'),
            'product.description': lambda: self._safe_get(product, 'description_sale') or self._safe_get(product, 'description'),
            'product.default_code': lambda: self._safe_get(product, 'default_code'),
            'product.price': lambda: self._safe_get(product, 'list_price'),
            'product.currency': lambda: self._safe_get(getattr(product, 'currency_id', False), 'name'),
            'product.image_url': lambda: self._product_image_url(website, product),
            'product.website_url': lambda: self._record_url(website, self._safe_get(product, 'website_url')),
            'blog.name': lambda: self._safe_get(blog, 'name'),
            'blog.subtitle': lambda: self._safe_get(blog, 'subtitle'),
            'blog.author': lambda: self._safe_get(getattr(blog, 'author_id', False), 'name'),
            'blog.date_published': lambda: self._safe_get(blog, 'published_date'),
            'blog.url': lambda: self._record_url(website, self._safe_get(blog, 'website_url')),
            'blog.image_url': lambda: self._blog_image_url(website, blog),
        }

    @api.model
    def _product_image_url(self, website, product):
        if not product or not getattr(product, 'exists', lambda: False)():
            return ''
        if 'image_1920' not in product._fields or not product.image_1920:
            return ''
        return self._record_url(website, '/web/image/product.template/%s/image_1920' % product.id)

    @api.model
    def _blog_image_url(self, website, blog):
        if not blog or not getattr(blog, 'exists', lambda: False)():
            return ''
        if 'cover_properties' in blog._fields and blog.cover_properties:
            match = re.search(r'url\([\'"]?([^\'")]+)[\'"]?\)', blog.cover_properties)
            if match:
                return self._record_url(website, match.group(1))
        if 'image_1920' in blog._fields and blog.image_1920:
            return self._record_url(website, '/web/image/blog.post/%s/image_1920' % blog.id)
        return ''

    @api.model
    def resolve_tokens(self, text, context=None):
        if not text or '{{' not in text:
            return text, []
        context = context or {}
        warnings = []
        resolvers = self._resolvers(context)

        def replace(match):
            token = match.group(1)
            resolver = resolvers.get(token)
            if not resolver:
                warnings.append('Unknown token "{{ %s }}".' % token)
                return match.group(0)
            value = resolver()
            if value is False or value is None:
                value = ''
            return str(value)

        return TOKEN_RE.sub(replace, text), warnings

    @api.model
    def preview_tokens(self, text, context=None):
        resolved, warnings = self.resolve_tokens(text, context=context)
        return {
            'input': text,
            'resolved': resolved,
            'warnings': warnings,
        }

    @api.model
    def get_available_tokens(self, target_type=None):
        groups = {
            'Website': ['website.name', 'website.domain'],
            'Company': ['company.name', 'company.email', 'company.phone'],
            'Current Page': ['current.url', 'current.path', 'current.lang', 'current.canonical_url'],
            'Website Page': ['page.name', 'page.url', 'page.meta_title', 'page.meta_description'],
        }
        if target_type in (None, 'product'):
            groups['Product'] = [
                'product.name', 'product.description', 'product.default_code',
                'product.price', 'product.currency', 'product.image_url',
                'product.website_url',
            ]
        if target_type in (None, 'blog_post'):
            groups['Blog'] = [
                'blog.name', 'blog.subtitle', 'blog.author', 'blog.date_published',
                'blog.url', 'blog.image_url',
            ]
        return groups
