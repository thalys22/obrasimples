"""
Tela de usuários do admin em português simples: explica cada permissão,
mostra as obras de cada pessoa e impede que quem não é superusuário
dê a si mesmo (ou a outros) mais poderes.
"""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import Group, Permission, User
from django.db.models import Q
from django.urls import reverse
from django.utils.html import format_html, format_html_join

from .models import Obra

EXPLICA_ACESSO_APP = """
<div style="max-width:780px;line-height:1.6">
<b>Ativo</b>: a pessoa consegue entrar no ObraSimples com usuário e senha.
Desmarque para <b>bloquear</b> o acesso sem apagar nada; a obra e os lançamentos dela continuam guardados.
<br>Para vincular uma obra a esta pessoa, abra a obra em <i>Obras</i> e escolha-a como <b>Dono</b> ou em
<b>Outros usuários com acesso</b>. Se ela não tiver nenhuma obra, ganha uma com dados de exemplo no primeiro acesso.
</div>"""

EXPLICA_ADMIN = """
<div style="max-width:780px;line-height:1.6">
<p style="margin:0 0 8px">Estas opções valem <b>só para este painel de administração</b> (o endereço /admin).
Elas não mudam o que a pessoa vê ou faz dentro do app da obra.</p>
<table style="border-collapse:collapse;margin:0 0 10px">
<tr><td style="padding:4px 12px 4px 0;vertical-align:top"><b>Membro da equipe</b></td>
<td style="padding:4px 0">Deixa a pessoa <b>entrar</b> no /admin. Sozinho não mostra nada: ela só vê o que os
<b>grupos</b> ou as <b>permissões</b> abaixo liberarem.</td></tr>
<tr><td style="padding:4px 12px 4px 0;vertical-align:top"><b>Superusuário</b></td>
<td style="padding:4px 0">Pode <b>tudo</b>: ver e alterar as obras de todos, criar e bloquear usuários, trocar senhas e dar
permissões. Já inclui todas as permissões, sem precisar marcar mais nada. Dê só para quem administra o sistema.</td></tr>
<tr><td style="padding:4px 12px 4px 0;vertical-align:top"><b>Grupos</b></td>
<td style="padding:4px 0">Pacotes prontos de permissões. Use em vez de marcar uma a uma:
<br>• <b>Consulta (somente leitura)</b>: vê usuários e os dados de <b>todas</b> as obras no /admin, sem poder alterar nada.
Bom para quem acompanha os testes.
<br>• <b>Gestão de usuários e obras</b>: cria e edita usuários (inclusive troca senha), vincula obras a pessoas e vê os dados
de todas as obras. Não pode tornar ninguém superusuário nem dar acesso ao /admin.</td></tr>
<tr><td style="padding:4px 12px 4px 0;vertical-align:top"><b>Permissões do usuário</b></td>
<td style="padding:4px 0">Ajuste fino, item por item. Cada linha tem o formato <i>tabela · ação</i>:
<b>ver</b> = ver a lista e os detalhes; <b>adicionar</b> = criar registros; <b>alterar</b> = editar;
<b>excluir</b> = apagar. Valem para os registros de <b>todas</b> as obras.</td></tr>
</table>
<p style="margin:0">⚠️ Quem pode ver uma tabela no /admin vê os dados de <b>todos</b> os usuários nela.
Só o superusuário pode alterar esta seção.</p>
</div>"""


ACOES = {"view": "ver", "add": "adicionar", "change": "alterar", "delete": "excluir"}


def rotulo_permissao(p):
    """Ex.: 'Notas fiscais · alterar' em vez de 'obras | nota fiscal | Can change nota fiscal'."""
    modelo = p.content_type.model_class()
    tabela = str(modelo._meta.verbose_name_plural).capitalize() if modelo else p.content_type.model
    acao = ACOES.get(p.codename.split("_", 1)[0], p.codename)
    return f"{tabela} · {acao}"


class UsuarioAdmin(UserAdmin):
    list_display = ("username", "nome", "email", "is_active", "is_staff", "is_superuser", "qtd_obras", "last_login")
    list_filter = ("is_active", "is_staff", "is_superuser", "groups")
    readonly_fields = ("last_login", "date_joined", "obras_vinculadas")

    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Dados pessoais", {"fields": ("first_name", "last_name", "email"),
                            "description": "O nome aparece no app, no canto superior direito."}),
        ("Acesso ao ObraSimples", {"fields": ("is_active", "obras_vinculadas"), "description": EXPLICA_ACESSO_APP}),
        ("Acesso ao painel de administração", {"fields": ("is_staff", "is_superuser", "groups", "user_permissions"),
                                               "description": EXPLICA_ADMIN}),
        ("Datas", {"fields": ("last_login", "date_joined"), "classes": ("collapse",)}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("username", "password1", "password2"),
            "description": "Defina o usuário e a senha inicial. Depois de salvar, preencha o nome e o e-mail e "
                           "vincule uma obra em <i>Obras</i> (ou deixe a pessoa receber uma obra de exemplo no primeiro acesso).",
        }),
    )

    AJUDA = {
        "is_active": "Marcado: pode entrar no ObraSimples. Desmarcado: acesso bloqueado (os dados ficam guardados).",
        "is_staff": "Pode entrar no painel de administração (/admin). Sozinho não libera nada: combine com grupos ou permissões.",
        "is_superuser": "Pode tudo no /admin, sem precisar marcar grupos ou permissões.",
        "groups": "Pacotes prontos de permissões. Veja a explicação acima.",
        "user_permissions": "Ajuste fino, item por item. Formato: tabela · ação (ver, adicionar, alterar, excluir).",
    }

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        for campo, texto in self.AJUDA.items():
            if campo in form.base_fields:
                form.base_fields[campo].help_text = texto
        if "user_permissions" in form.base_fields:
            # Só as permissões que fazem sentido aqui: dados das obras e usuários
            form.base_fields["user_permissions"].queryset = Permission.objects.filter(
                Q(content_type__app_label="obras") | Q(content_type__app_label="auth", content_type__model="user")
            ).select_related("content_type").order_by("content_type__model", "codename")
            form.base_fields["user_permissions"].label_from_instance = rotulo_permissao
        return form

    def has_change_permission(self, request, obj=None):
        # Só um superusuário edita (ou troca a senha de) outro superusuário
        if obj is not None and obj.is_superuser and not request.user.is_superuser:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.is_superuser and not request.user.is_superuser:
            return False
        return super().has_delete_permission(request, obj)

    def get_readonly_fields(self, request, obj=None):
        ro = list(super().get_readonly_fields(request, obj))
        if not request.user.is_superuser:
            # Evita que alguém com permissão de editar usuários se dê mais poderes
            ro += ["is_staff", "is_superuser", "groups", "user_permissions"]
        return ro

    @admin.display(description="Nome")
    def nome(self, u):
        return u.get_full_name()

    @admin.display(description="Obras")
    def qtd_obras(self, u):
        return Obra.objects.filter(Q(dono=u) | Q(membros=u)).distinct().count()

    @admin.display(description="Obras desta pessoa")
    def obras_vinculadas(self, u):
        if not u or not u.pk:
            return "—"
        obras = Obra.objects.filter(Q(dono=u) | Q(membros=u)).distinct().order_by("id")
        if not obras:
            return "Nenhuma ainda. Ela recebe uma obra de exemplo no primeiro acesso."
        return format_html_join(
            format_html("<br>"), '<a href="{}">{}</a> ({})',
            ((reverse("admin:obras_obra_change", args=[o.pk]), o.nome, "dono" if o.dono_id == u.pk else "acesso compartilhado") for o in obras),
        )


admin.site.unregister(User)
admin.site.register(User, UsuarioAdmin)
