from django.urls import path

from . import views as v

urlpatterns = [
    path("", v.app, name="app"),
    path("api/estado", v.estado),
    path("api/obra", v.obra_atualizar),
    path("api/etapa-avanco", v.etapa_avanco),
    path("api/orcamento", v.orcamento_criar),
    path("api/orcamento/<int:pk>", v.orcamento_excluir),
    path("api/fornecedores", v.fornecedor_criar),
    path("api/materiais", v.material_criar),
    path("api/notas", v.nota_criar),
    path("api/consumos", v.consumo_criar),
    path("api/empreiteiros", v.empreiteiro_criar),
    path("api/contratos", v.contrato_criar),
    path("api/medicoes", v.medicao_criar),
    path("api/medicoes/<int:pk>/aprovar", v.medicao_aprovar),
    path("api/medicoes/<int:pk>", v.medicao_excluir),
    path("api/pagamentos", v.pagamento_criar),
    path("api/pagamentos/<int:pk>/pagar", v.pagamento_pagar),
    path("api/pagamentos/<int:pk>", v.pagamento_excluir),
    path("api/recomecar", v.recomecar),
    path("api/importar", v.importar),
]
