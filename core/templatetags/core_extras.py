from django import template
from datetime import date, datetime

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """Allow dict[key] access in templates."""
    return dictionary.get(key, 0)


@register.filter
def ddmmyy(value):
    """Convert date and datetime values to DD/MM/YYYY."""
    if not value:
        return value
    if isinstance(value, (date, datetime)):
        return value.strftime('%d/%m/%Y')
    s = str(value).strip()
    try:
        date_part = s.split('T', 1)[0].split(' ', 1)[0]
        for pattern in ('%Y-%m-%d', '%d/%m/%Y'):
            try:
                return datetime.strptime(date_part, pattern).strftime('%d/%m/%Y')
            except ValueError:
                continue
    except (TypeError, ValueError):
        return value
    return value


@register.filter
def waste_th(value):
    return {
        'Plastic': 'พลาสติก',
        'Glass': 'แก้ว',
        'Can': 'กระป๋อง',
        'All': 'ทั้งหมด',
    }.get(value, value)


@register.filter
def role_th(value):
    return {
        'System admin': 'แอดมินสูงสุด',
        'Admin': 'แอดมินหน่วยงาน',
        'Collector': 'คนเก็บขยะ',
    }.get(value, value)


@register.simple_tag(takes_context=True)
def pagination_url(context, page_param, page_number):
    """Keep the current filters while changing one pagination parameter."""
    query = context['request'].GET.copy()
    query[page_param] = page_number
    encoded = query.urlencode()
    return f'?{encoded}' if encoded else '?'
