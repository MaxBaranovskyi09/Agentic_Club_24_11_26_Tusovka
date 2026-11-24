"""Єдине місце перевірки прав доступу до подій.

Правило: кожен view отримує подію ЛИШЕ через get_viewable_event / get_editable_event.
Для приватних подій без доступу завжди 404 — щоб не розкривати факт існування.
"""

from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404

from .models import Event, PrivateAccess


def can_view(user, event):
    if not event.is_private:
        return True
    if not user.is_authenticated:
        return False
    if event.author_id == user.pk:
        return True
    return PrivateAccess.objects.filter(user=user, event=event).exists()


def can_edit(user, event):
    return user.is_authenticated and event.author_id == user.pk


def _fetch(public_id, *, for_update=False):
    qs = Event.objects.select_related("author")
    if for_update:
        # Блокуємо лише рядок події (без JOIN-таблиць).
        qs = Event.objects.select_for_update(of=("self",)).select_related("author")
    return get_object_or_404(qs, public_id=public_id)


def get_viewable_event(user, public_id, *, for_update=False):
    event = _fetch(public_id, for_update=for_update)
    if not can_view(user, event):
        raise Http404
    return event


def get_editable_event(user, public_id, *, for_update=False):
    event = get_viewable_event(user, public_id, for_update=for_update)
    if not can_edit(user, event):
        if event.is_private:
            raise Http404
        raise PermissionDenied
    return event
