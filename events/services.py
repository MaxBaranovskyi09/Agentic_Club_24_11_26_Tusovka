"""Бізнес-правила запису на подію. Усі зміни — під блокуванням рядка події."""

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import Registration
from .permissions import get_viewable_event


class RegistrationError(Exception):
    pass


ALREADY_REGISTERED = "Ви вже записані на цю подію."


def register(user, public_id):
    """Записати користувача. Кидає Http404 (немає доступу) або RegistrationError."""
    with transaction.atomic():
        event = get_viewable_event(user, public_id, for_update=True)
        if event.author_id == user.pk:
            raise RegistrationError("Автор не може записатися на власну подію.")
        if event.starts_at <= timezone.now():
            raise RegistrationError("Подія вже почалась або минула — запис закрито.")
        if Registration.objects.filter(event=event, user=user).exists():
            raise RegistrationError(ALREADY_REGISTERED)
        if Registration.objects.filter(event=event).count() >= event.capacity:
            raise RegistrationError("На жаль, вільних місць немає.")
        try:
            with transaction.atomic():
                Registration.objects.create(event=event, user=user)
        except IntegrityError:
            raise RegistrationError(ALREADY_REGISTERED)
    return event


def unregister(user, public_id):
    """Скасувати ВЛАСНИЙ запис."""
    with transaction.atomic():
        event = get_viewable_event(user, public_id, for_update=True)
        if event.starts_at <= timezone.now():
            raise RegistrationError("Подія вже почалась — скасувати запис неможливо.")
        deleted, _ = Registration.objects.filter(event=event, user=user).delete()
        if not deleted:
            raise RegistrationError("Ви не були записані на цю подію.")
    return event
