from django.contrib import admin

from .models import Comment, Event, PrivateAccess, Registration


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ("title", "author", "starts_at", "capacity", "is_private")
    list_filter = ("is_private",)
    search_fields = ("title",)
    readonly_fields = ("public_id", "invite_token", "created_at", "updated_at")


admin.site.register(Registration)
admin.site.register(PrivateAccess)
admin.site.register(Comment)
