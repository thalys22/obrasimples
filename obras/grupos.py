"""Cria (ou atualiza) os grupos de permissões prontos depois de cada migração."""
from django.db.models import Q

GRUPOS = {
    "Consulta (somente leitura)": lambda P: P.filter(Q(content_type__app_label="obras") | Q(content_type__app_label="auth", content_type__model="user"), codename__startswith="view_"),
    "Gestão de usuários e obras": lambda P: P.filter(
        Q(content_type__app_label="obras", codename__startswith="view_")
        | Q(content_type__app_label="obras", codename="change_obra")
        | Q(content_type__app_label="auth", content_type__model="user", codename__in=["view_user", "add_user", "change_user"])
    ),
}


def criar_grupos(sender, **kwargs):
    from django.contrib.auth.models import Group, Permission
    for nome, filtro in GRUPOS.items():
        g, _ = Group.objects.get_or_create(name=nome)
        g.permissions.set(filtro(Permission.objects.all()))
