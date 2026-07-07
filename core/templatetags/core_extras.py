from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """Allow dict[key] access in templates."""
    return dictionary.get(key, 0)


@register.filter
def ddmmyy(value):
    """
    Convert dates to DD/MM/YY.
    Supports:
      - YYYY-MM-DD  →  DD/MM/YY
      - DD/MM/YYYY  →  DD/MM/YY
    """
    if not value:
        return value
    s = str(value).strip()
    try:
        if '-' in s:
            # YYYY-MM-DD
            parts = s.split('-')
            if len(parts) == 3:
                y, m, d = parts
                return f"{d.zfill(2)}/{m.zfill(2)}/{y[2:]}"
        elif '/' in s:
            # DD/MM/YYYY
            parts = s.split('/')
            if len(parts) == 3:
                d, m, y = parts
                return f"{d.zfill(2)}/{m.zfill(2)}/{y[2:]}"
    except Exception:
        pass
    return value
