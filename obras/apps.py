from django.apps import AppConfig
from django.db.models.signals import post_migrate


class ObrasConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "obras"
    verbose_name = "Obras"

    def ready(self):
        from . import admin_usuarios  # noqa: F401  (tela de usuários em português)
        from .grupos import criar_grupos
        post_migrate.connect(criar_grupos, sender=self)
