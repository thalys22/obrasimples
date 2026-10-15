from django.contrib import admin
from django.http import HttpResponseForbidden
from django.template.response import TemplateResponse
from django.urls import path, reverse

from obras import services as S

from .models import Carga, Referencia


@admin.register(Referencia)
class ReferenciaAdmin(admin.ModelAdmin):
    """Meses do SINAPI já carregados. Somente leitura: a base só muda pela carga (botão \"Carregar planilha\")."""
    list_display = ("uf", "mes", "regime", "composicoes_com_custo", "insumos_com_preco", "carga")
    list_filter = ("uf", "regime", "data_base")
    ordering = ("-data_base", "uf", "regime")
    change_list_template = "admin/sinapi/referencia/change_list.html"

    @admin.display(description="Mês", ordering="data_base")
    def mes(self, r):
        return f"{r.data_base:%m/%Y}"

    @admin.display(description="Carga", ordering="carregada_em")
    def carga(self, r):
        return f"{r.carregada_em:%d/%m/%Y}"

    @admin.display(description="Comp. com custo")
    def composicoes_com_custo(self, r):
        return r.custos.filter(custo_publicado__isnull=False).count()

    @admin.display(description="Insumos c/ preço")
    def insumos_com_preco(self, r):
        return r.precos.filter(preco__isnull=False).count()

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        # Apagar uma referência antiga é seguro (nenhuma obra aponta para essas tabelas), mas só o superusuário.
        return request.user.is_superuser

    def get_urls(self):
        return [path("carregar/", self.admin_site.admin_view(self.carregar), name="sinapi_referencia_carregar")] + super().get_urls()

    def carregar(self, request):
        if not S.pode_editar_base(request.user):
            return HttpResponseForbidden("Só o administrador carrega o SINAPI.")
        ctx = dict(
            self.admin_site.each_context(request), title="Carregar o SINAPI", opts=self.model._meta,
            referencias=[dict(r=r, precos=r.precos.count(), custos=r.custos.count(), carga=r.cargas.order_by("-criada_em").first())
                         for r in Referencia.objects.all()],
        )
        return TemplateResponse(request, "admin/sinapi/referencia/carregar.html", ctx)
