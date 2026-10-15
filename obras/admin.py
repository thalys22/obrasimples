from django import forms
from django.contrib import admin, messages
from django.db.models import Count, Sum

from . import services as S
from .models import (
    Composicao, Consumo, Contrato, Empreiteiro, Etapa, Fornecedor, Insumo, InsumoPrevisto, ItemComposicao,
    ItemNota, ItemOrcamento, Material, Medicao, NotaFiscal, Obra, Pagamento,
)


class MesmaObraForm(forms.ModelForm):
    """Impede ligar um registro a algo de outra obra (ex.: nota da obra A com fornecedor da obra B)."""
    def clean(self):
        cd = super().clean()
        obra = cd.get("obra")
        if obra is None and getattr(self.instance, "obra_id", None):
            obra = self.instance.obra
        if obra:
            for nome, valor in list(cd.items()):
                if nome != "obra" and getattr(valor, "obra_id", None) not in (None, obra.pk):
                    self.add_error(nome, f"Isso pertence a outra obra ({valor.obra.nome}). Escolha um item da obra {obra.nome}.")
        return cd


class PorObra(admin.ModelAdmin):
    """Base: cada registro pertence a uma única obra; mostra e filtra por obra."""
    form = MesmaObraForm
    list_filter = ("obra",)
    list_select_related = ("obra", "obra__dono")

    @admin.display(description="Obra", ordering="obra__nome")
    def obra_col(self, o):
        return f"{o.obra.nome} · {o.obra.dono}"


class SoConsulta(PorObra):
    """Lançamentos: só consulta no admin. Criar, alterar ou apagar pelo admin pularia as regras
    (estoque, custo médio, pagamentos automáticos). Lançamentos são feitos pelo app."""
    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


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
                           "a obra começa vazia. Quem não tem nenhuma obra liberada vê um aviso ao entrar no app. "
                           "Para preencher com os dados de exemplo, use a ação <i>Apagar dados e carregar o exemplo</i> na lista de obras.",
        }),
        ("Dados da obra", {"fields": ("nome", "cliente", "prazo", "valor_contratado", "exemplo")}),
        ("Datas", {"fields": ("criada_em", "atualizada_em"), "classes": ("collapse",)}),
    )

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        # O dono já tem acesso: não precisa (e não deve) aparecer também como membro
        form.instance.membros.remove(form.instance.dono)

    def get_deleted_objects(self, objs, request):
        # A obra leva junto todos os lançamentos dela; mostra um resumo em vez da lista de travas internas
        resumo = [f"{o.nome} (dono: {o.dono}) com {o.orcamento.count()} serviços, {o.notas.count()} notas fiscais, "
                  f"{o.medicoes.count()} medições e {o.pagamentos.count()} pagamentos" for o in objs]
        return resumo, {"obras": len(objs)}, set(), []

    def delete_model(self, request, obj):
        S.excluir_obra(obj)

    def delete_queryset(self, request, queryset):
        for o in queryset:
            S.excluir_obra(o)

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


# ---------------------------------------------------------------- cadastro de insumos e composições
class EscopoFiltro(admin.SimpleListFilter):
    title = "onde vale"
    parameter_name = "escopo"

    def lookups(self, request, model_admin):
        return [("base", "Base geral (todas as obras)"), ("obra", "Só de uma obra")]

    def queryset(self, request, qs):
        if self.value() == "base":
            return qs.filter(obra__isnull=True)
        if self.value() == "obra":
            return qs.filter(obra__isnull=False)
        return qs


class CatalogoAdmin(admin.ModelAdmin):
    list_select_related = ("obra",)

    @admin.display(description="Onde vale", ordering="obra__nome")
    def escopo(self, o):
        return "Base geral" if o.obra_id is None else f"Só a obra {o.obra.nome}"


@admin.register(Insumo)
class InsumoAdmin(CatalogoAdmin):
    list_display = ("codigo", "descricao", "unidade", "tipo", "preco", "escopo", "atualizado_em")
    list_filter = (EscopoFiltro, "tipo", "obra")
    search_fields = ("codigo", "descricao")
    fields = ("obra", "codigo", "descricao", "unidade", "tipo", "preco")


class ItemComposicaoFormSet(forms.BaseInlineFormSet):
    def clean(self):
        super().clean()
        comp = self.instance
        vistos = set()
        for f in self.forms:
            if not getattr(f, "cleaned_data", None) or f.cleaned_data.get("DELETE"):
                continue
            ins = f.cleaned_data.get("insumo")
            if not ins:
                continue
            if ins.obra_id is not None and ins.obra_id != comp.obra_id:
                f.add_error("insumo", "Esse insumo é de outra obra. Uma composição da base geral só pode usar insumos da base geral; "
                                      "uma composição de uma obra, os da base geral ou os daquela obra.")
            if ins.pk in vistos:
                f.add_error("insumo", "Insumo repetido na composição.")
            vistos.add(ins.pk)


class ItemComposicaoInline(admin.TabularInline):
    model = ItemComposicao
    formset = ItemComposicaoFormSet
    extra = 1
    autocomplete_fields = ("insumo",)


@admin.register(Composicao)
class ComposicaoAdmin(CatalogoAdmin):
    list_display = ("codigo", "descricao", "unidade", "custo", "escopo", "referencia")
    list_filter = (EscopoFiltro, "referencia", "obra")
    search_fields = ("codigo", "descricao")
    fields = ("obra", "codigo", "descricao", "unidade", "observacao", "referencia")
    inlines = [ItemComposicaoInline]

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("itens__insumo")

    @admin.display(description="Custo por unidade (R$)")
    def custo(self, o):
        return f"{o.custo_unitario:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


@admin.register(Etapa)
class EtapaAdmin(PorObra):
    list_display = ("nome", "ordem", "percentual", "obra_col")
    search_fields = ("nome", "obra__nome")


class InsumoPrevistoInline(admin.TabularInline):
    model = InsumoPrevisto
    extra = 0
    can_delete = False
    readonly_fields = ("insumo", "coeficiente", "preco_unitario")
    verbose_name_plural = "insumos previstos (cópia da composição na data em que o serviço entrou no orçamento)"

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(ItemOrcamento)
class ItemOrcamentoAdmin(PorObra):
    list_display = ("servico", "codigo", "etapa", "unidade", "quantidade", "preco_unitario", "obra_col")
    search_fields = ("servico", "codigo", "etapa__nome", "obra__nome")
    readonly_fields = ("composicao", "codigo")
    inlines = [InsumoPrevistoInline]


@admin.register(Material)
class MaterialAdmin(PorObra):
    list_display = ("nome", "insumo", "unidade", "saldo", "custo_medio", "obra_col")
    search_fields = ("nome", "obra__nome", "insumo__codigo")
    readonly_fields = ("saldo", "custo_medio")
    autocomplete_fields = ("insumo",)


@admin.register(Fornecedor)
class FornecedorAdmin(PorObra):
    list_display = ("nome", "contato", "obra_col")
    search_fields = ("nome", "obra__nome")


@admin.register(Empreiteiro)
class EmpreiteiroAdmin(PorObra):
    list_display = ("nome", "especialidade", "contato", "obra_col")
    search_fields = ("nome", "obra__nome")


@admin.register(Contrato)
class ContratoAdmin(PorObra):
    list_display = ("empreiteiro", "item", "valor_contratado", "forma_pagamento", "obra_col")
    search_fields = ("empreiteiro__nome", "obra__nome")


class ItemNotaInline(admin.TabularInline):
    model = ItemNota
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(NotaFiscal)
class NotaFiscalAdmin(SoConsulta):
    list_display = ("numero", "fornecedor", "data", "obra_col", "criada_em")
    inlines = [ItemNotaInline]
    search_fields = ("numero", "obra__nome")


@admin.register(Consumo)
class ConsumoAdmin(SoConsulta):
    list_display = ("data", "item", "material", "quantidade", "valor", "obra_col")


@admin.register(Medicao)
class MedicaoAdmin(SoConsulta):
    list_display = ("id", "contrato", "data", "percentual", "valor", "status", "aprovada_por", "obra_col")
    list_filter = ("obra", "status")


@admin.register(Pagamento)
class PagamentoAdmin(SoConsulta):
    list_display = ("data_programada", "tipo", "origem", "valor", "status", "data_pagamento", "obra_col")
    list_filter = ("obra", "status", "tipo")
