from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from core.operations import form_errors, require_capability

from .forms import ACADEMIC_FORMS, PeriodActionForm
from .services import period_action, save_academic


def definition(kind):
    if kind not in ACADEMIC_FORMS:
        raise Http404
    form = ACADEMIC_FORMS[kind]
    return form, form._meta.model


@login_required
@require_GET
def academic_list(request, kind="years"):
    form, model = definition(kind)
    require_capability(request.user, f"academics.view_{model._meta.model_name}")
    records = model.objects.all()
    query = request.GET.get("q", "").strip()[:100]
    if query:
        lookup = Q()
        for name in form._meta.fields:
            field = model._meta.get_field(name)
            if field.get_internal_type() == "CharField":
                lookup |= Q(**{f"{name}__icontains": query})
            elif name == "teacher":
                lookup |= Q(teacher__first_name__icontains=query) | Q(
                    teacher__last_name__icontains=query
                )
            elif name in {"academic_year", "section", "school_class", "subject"}:
                lookup |= Q(**{f"{name}__name__icontains": query})
        records = records.filter(lookup)
    for name in ("academic_year", "school_class", "subject", "teacher", "section"):
        if name in form._meta.fields:
            records = records.select_related(name)
    status = request.GET.get("status", "")
    if kind in {"years", "terms"} and status in {"open", "closed", "archived"}:
        records = records.filter(status=status)
    sort = request.GET.get("sort", "")
    ordering = "-pk" if sort == "newest" else "pk"
    records = records.order_by(ordering)
    rows = []
    page = Paginator(records, 20).get_page(request.GET.get("page"))
    for obj in page:
        cells = [getattr(obj, name) for name in form._meta.fields]
        rows.append({"object": obj, "cells": cells})
    return render(
        request,
        "academics/list.html",
        {
            "kind": kind,
            "tabs": [
                key
                for key, definition in ACADEMIC_FORMS.items()
                if request.user.has_perm(
                    f"academics.view_{definition._meta.model._meta.model_name}"
                )
            ],
            "title": kind.replace("-", " ").title(),
            "columns": [model._meta.get_field(f).verbose_name for f in form._meta.fields],
            "rows": rows,
            "page_obj": page,
            "query": query,
            "status_filter": status,
            "can_add": request.user.has_perm(f"academics.add_{model._meta.model_name}"),
            "can_edit": request.user.has_perm(f"academics.change_{model._meta.model_name}"),
            "period": kind in {"years", "terms"},
            "active_nav": "academics",
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def academic_edit(request, kind, pk=None):
    form_class, model = definition(kind)
    require_capability(
        request.user, f"academics.{'change' if pk else 'add'}_{model._meta.model_name}"
    )
    instance = get_object_or_404(model, pk=pk) if pk else None
    form = form_class(request.POST if request.method == "POST" else None, instance=instance)
    for name in ("academic_year", "teacher"):
        if name in form.fields:
            form.fields[name].queryset = form.fields[name].queryset.filter(
                **({"status": "open"} if name == "academic_year" else {"is_active": True})
            )
    if request.method == "POST" and form.is_valid():
        try:
            save_academic(request.user, form)
        except (ValidationError, IntegrityError) as exc:
            form_errors(form, exc)
        else:
            messages.success(request, "Academic record saved.")
            return redirect("academics:list", kind=kind)
    return render(
        request,
        "operations/form.html",
        {
            "form": form,
            "title": f"{'Edit' if pk else 'Add'} {model._meta.verbose_name}",
            "back_url": "academics:list",
            "back_arg": kind,
            "active_nav": "academics",
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def academic_action(request, kind, pk, action):
    if kind not in {"years", "terms"} or action not in {"activate", "close", "archive"}:
        raise Http404
    _, model = definition(kind)
    require_capability(request.user, f"academics.change_{model._meta.model_name}")
    obj = get_object_or_404(model, pk=pk)
    form = PeriodActionForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            period_action(request.user, kind, pk, action)
        except (ValidationError, IntegrityError) as exc:
            form_errors(form, exc)
        else:
            messages.success(request, "Academic period updated.")
            return redirect("academics:list", kind=kind)
    return render(
        request,
        "operations/form.html",
        {
            "form": form,
            "title": f"{action.title()}: {obj}",
            "description": "Closing and archiving are permanent. "
            "Historical records remain available. "
            "Activation switches the current period.",
            "back_url": "academics:list",
            "back_arg": kind,
            "active_nav": "academics",
        },
    )
