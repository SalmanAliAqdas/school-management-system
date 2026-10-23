from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


@register.filter
def money(value, places=2):
    try:
        precision = max(0, min(3, int(places)))
        return f"{Decimal(value):,.{precision}f}"
    except (InvalidOperation, ValueError, TypeError):
        return value
