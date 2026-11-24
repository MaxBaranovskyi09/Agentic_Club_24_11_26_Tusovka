from django.urls import path

from . import views

app_name = "events"

urlpatterns = [
    path("", views.home, name="home"),
    path("events/new/", views.event_create, name="create"),
    path("events/<uuid:public_id>/", views.event_detail, name="detail"),
    path("events/<uuid:public_id>/edit/", views.event_edit, name="edit"),
    path("events/<uuid:public_id>/delete/", views.event_delete, name="delete"),
    path("events/<uuid:public_id>/register/", views.event_register, name="register"),
    path("events/<uuid:public_id>/unregister/", views.event_unregister, name="unregister"),
    path("events/<uuid:public_id>/comments/", views.comment_add, name="comment_add"),
    path("events/<uuid:public_id>/invite/regenerate/", views.regenerate_invite, name="regenerate_invite"),
    path("events/<uuid:public_id>/cover/", views.event_cover, name="cover"),
    path("invite/<str:token>/", views.invite_accept, name="invite"),
    path("me/", views.profile, name="profile"),
]
