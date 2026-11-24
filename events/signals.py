"""Прибирання файлів обкладинок з диска при заміні/видаленні."""

from django.db import transaction
from django.db.models.signals import post_delete, pre_save
from django.dispatch import receiver

from .models import Event


def _delete_file_on_commit(storage, name):
    if name:
        transaction.on_commit(lambda: storage.delete(name))


@receiver(pre_save, sender=Event)
def delete_replaced_cover(sender, instance, **kwargs):
    if not instance.pk:
        return
    old_name = Event.objects.filter(pk=instance.pk).values_list("cover", flat=True).first()
    new_name = instance.cover.name if instance.cover else ""
    if old_name and old_name != new_name:
        _delete_file_on_commit(instance.cover.storage, old_name)


@receiver(post_delete, sender=Event)
def delete_cover_with_event(sender, instance, **kwargs):
    if instance.cover:
        _delete_file_on_commit(instance.cover.storage, instance.cover.name)
