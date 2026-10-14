from django.contrib import admin, messages
from django.db.models import Count, Sum

from . import services as S
from .models import (
    Consumo, Contrato, Empreiteiro, Fornecedor, ItemNota, ItemOrcamento, Material,
    Medicao, NotaFiscal, Obra, Pagamento,
)


class PorObra(admin.ModelAdmin):
    """Base: mostra a obra e o usuário dono, e filtra por usuário."""
    list_filter = ("obra__dono",)
    list_select_related = ("obra", "obra__dono")

    @admin.display(description="Usuário", ordering="obra__dono__username")
    def usuario(self, o):
        return o.obra.dono


@admin.register(Obra)
class ObraAdmin(admin.ModelAdmin):
    list_display = ("nome", "dono", "compartilhada_com", "prazo", "servicos", "total_orcado", "exemplo", "atualizada_em")
    list_filter = ("exemplo", "dono")
    search_fields = ("nome", "dono__username", "dono__first_name", "dono__email")
    readonly_fields = ("criada_em", "atualizada_em")
    filter_horizontal = ("membros",)
    autocomplete_fields = ("dono",)
    actions = ["recarregar_exemplo", "zerar_obra"]
    fieldsets = (
        ("Quem acessa esta obra", {
            "fields": ("dono", "membros"),
            "description": "<b>Dono</b>: responsável pela obra; é quem pode apagar todos os dados dela ou importar planilha. "
                           "<b>Outros usuários com acesso</b>: também abrem a obra e fazem lançamentos. "
                           "Uma pessoa pode ter várias obras; no app ela troca pelo seletor no topo. "
                           "Para criar uma obra para alguém, clique em <i>Adicionar obra</i>, escolha o dono e salve: "
                           "a obra começa vazia.",
        }),
        ("Dados da obra", {"fields": ("nome", "cliente", "prazo", "valor_contratado", "exemplo")}),
        ("Datas", {"fields": ("criada_em", "atualizada_em"), "classes": ("collapse",)}),
    )

    @admin.display(description="Compartilhada com")
    def compartilhada_com(self, o):
        nomes = [u.get_full_name() or u.username for u in o.membros.all()]
        return ", ".join(nomes) or "—"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("dono").annotate(n_itens=Count("orcamento", distinct=True))

    @admin.display(description="Serviços", ordering="n_itens")
    def servicos(self, o):
        return o.n_itens

    @admin.display(description="Total orçado (R$)")
    def total_orcado(self, o):
        return f"{sum(i.planejado for i in o.orcamento.all()):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    @admin.action(description="Apagar dados e carregar o exemplo")
    def recarregar_exemplo(self, request, qs):
        for o in qs:
            S.recomecar(o, "exemplo")
        self.message_user(request, f"{qs.count()} obra(s) voltaram aos dados de exemplo.", messages.SUCCESS)

    @admin.action(description="Apagar todos os dados (obra em branco)")
    def zerar_obra(self, request, qs):
        for o in qs:
            S.recomecar(o, "vazio")
        self.message_user(request, f"{qs.count()} obra(s) zeradas.", messages.SUCCESS)


@admin.register(ItemOrcamento)
class ItemOrcamentoAdmin(PorObra):
    list_display = ("servico", "etapa", "unidade", "quantidade", "preco_unitario", "usuario")
    search_fields = ("servico", "etapa")


@admin.register(Material)
class MaterialAdmin(PorObra):
    list_display = ("nome", "unidade", "saldo", "custo_medio", "usuario")
    search_fields = ("nome",)


class ItemNotaInline(admin.TabularInline):
    model = ItemNota
    extra = 0


@admin.register(NotaFiscal)
class NotaFiscalAdmin(PorObra):
    list_display = ("numero", "fornecedor", "data", "usuario", "criada_em")
    inlines = [ItemNotaInline]
    search_fields = ("numero",)


@admin.register(Consumo)
class ConsumoAdmin(PorObra):
    list_display = ("data", "item", "material", "quantidade", "valor", "usuario")


@admin.register(Medicao)
class MedicaoAdmin(PorObra):
    list_display = ("id", "contrato", "data", "percentual", "valor", "status", "aprovada_por", "usuario")
    list_filter = ("status", "obra__dono")


@admin.register(Pagamento)
class PagamentoAdmin(PorObra):
    list_display = ("data_programada", "tipo", "origem", "valor", "status", "data_pagamento", "usuario")
    list_filter = ("status", "tipo", "obra__dono")


admin.site.register(Fornecedor, PorObra)
admin.site.register(Empreiteiro, PorObra)
admin.site.register(Contrato, PorObra)
