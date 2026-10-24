from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from .forms import MovementForm
from .models import Asset, Item, Location, StockMovement
from .services import balance, finalize


@login_required
def overview(request):
    if not (
        request.user.has_perm("inventory.view_all_inventory")
        or hasattr(request.user, "hr_employee")
    ):
        raise PermissionDenied
    manage = request.user.has_perm("inventory.view_all_inventory")
    assets = (
        Asset.objects.select_related("item", "location", "custodian")
        if manage
        else Asset.objects.filter(custodian__user=request.user).select_related("item", "location")
    )
    stock = (
        [
            (item.code, item.name, location.name, balance(item, location))
            for item in Item.objects.filter(is_active=True)
            for location in Location.objects.filter(is_active=True)
        ]
        if manage
        else []
    )
    return render(
        request,
        "operations/phase8_dashboard.html",
        {
            "title": "Inventory and assets",
            "description": (
                "Immutable stock movement history and accountable durable-asset custody."
            ),
            "metrics": [
                ("Items", Item.objects.count()),
                ("Final movements", StockMovement.objects.filter(state="finalized").count()),
                ("Visible assets", assets.count()),
            ],
            "sections": [
                {
                    "title": "Stock on hand",
                    "help": "Quantities derive from finalized movements.",
                    "headings": ["Code", "Item", "Location", "Quantity"],
                    "rows": stock[:100],
                },
                {
                    "title": "Assets",
                    "help": "Custodians see their own assigned equipment.",
                    "headings": ["Identifier", "Asset", "Location", "Condition", "Status"],
                    "rows": [
                        (
                            x.identifier,
                            x.item.name,
                            x.location.name,
                            x.condition,
                            x.get_status_display(),
                        )
                        for x in assets[:50]
                    ],
                },
            ],
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def movement(request):
    if not request.user.has_perm("inventory.manage_inventory"):
        raise PermissionDenied
    form = MovementForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        row = form.save(commit=False)
        row.actor = request.user
        row.save()
        try:
            finalize(request.user, row.pk)
        except (ValidationError, IntegrityError, PermissionDenied) as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "Stock movement finalized.")
            return redirect("inventory:overview")
    return render(
        request,
        "operations/phase7_form.html",
        {
            "title": "Record stock movement",
            "hint": "Finalized movements are permanent; corrections use compensating entries.",
            "form": form,
        },
    )
