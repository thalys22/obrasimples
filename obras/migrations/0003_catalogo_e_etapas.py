"""Cadastro de insumos e composições; etapas viram cadastro da obra.

Dados existentes:
- cada etapa digitada no orçamento vira uma Etapa da obra (mantendo o avanço físico);
- os serviços existentes continuam como estão, como serviços "por verba";
- o antigo campo "insumo" (texto) vira "observação".
"""
import django.db.models.deletion
from django.db import migrations, models

ETAPAS_PADRAO = [
    "Serviços preliminares", "Fundação", "Estrutura", "Alvenaria", "Cobertura",
    "Instalações elétricas", "Instalações hidrossanitárias", "Esquadrias", "Revestimentos",
    "Pisos", "Pintura", "Louças e metais", "Limpeza e entrega",
]


def ligar_etapas(apps, schema_editor):
    Etapa = apps.get_model("obras", "Etapa")
    Item = apps.get_model("obras", "ItemOrcamento")
    for item in Item.objects.all():
        et, _ = Etapa.objects.get_or_create(obra_id=item.obra_id, nome=item.etapa_texto[:120] or "Sem etapa")
        item.etapa_id = et.pk
        item.save(update_fields=["etapa"])
    for et in Etapa.objects.all():
        et.ordem = (ETAPAS_PADRAO.index(et.nome) + 1) * 10 if et.nome in ETAPAS_PADRAO else 1000 + et.pk
        et.save(update_fields=["ordem"])


class Migration(migrations.Migration):

    dependencies = [("obras", "0002_membros_da_obra")]

    operations = [
        # ---- etapas
        migrations.AlterUniqueTogether(name="etapaavanco", unique_together=set()),
        migrations.RenameModel("EtapaAvanco", "Etapa"),
        migrations.RenameField("etapa", "etapa", "nome"),
        migrations.AddField("etapa", "ordem", models.PositiveIntegerField(default=0)),
        migrations.AlterField("etapa", "percentual", models.DecimalField("avanço físico (%)", decimal_places=2, default=0, max_digits=5)),
        migrations.AlterModelOptions("etapa", {"ordering": ["ordem", "id"], "verbose_name": "etapa da obra", "verbose_name_plural": "etapas da obra"}),
        migrations.AddConstraint("etapa", models.UniqueConstraint(fields=("obra", "nome"), name="etapa_unica_por_obra")),

        # ---- catálogo
        migrations.CreateModel(
            name="Insumo",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("codigo", models.CharField(max_length=30, verbose_name="código")),
                ("descricao", models.CharField(max_length=200, verbose_name="descrição")),
                ("unidade", models.CharField(max_length=20)),
                ("tipo", models.CharField(choices=[("material", "Material"), ("mao-de-obra", "Mão de obra"), ("equipamento", "Equipamento"), ("empreitada", "Empreitada / terceiro")], default="material", max_length=12)),
                ("preco", models.DecimalField(decimal_places=4, default=0, max_digits=14, verbose_name="preço de referência")),
                ("atualizado_em", models.DateTimeField(auto_now=True)),
                ("obra", models.ForeignKey(blank=True, help_text="Vazio = base geral, disponível para todas as obras.", null=True, on_delete=django.db.models.deletion.CASCADE, related_name="insumos", to="obras.obra")),
            ],
            options={"ordering": ["codigo"]},
        ),
        migrations.AddConstraint("insumo", models.UniqueConstraint(condition=models.Q(("obra__isnull", True)), fields=("codigo",), name="insumo_codigo_unico_base")),
        migrations.AddConstraint("insumo", models.UniqueConstraint(fields=("obra", "codigo"), name="insumo_codigo_unico_obra")),
        migrations.CreateModel(
            name="Composicao",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("codigo", models.CharField(max_length=30, verbose_name="código")),
                ("descricao", models.CharField(max_length=200, verbose_name="descrição")),
                ("unidade", models.CharField(max_length=20)),
                ("referencia", models.BooleanField(default=False, help_text="Veio da biblioteca inicial do Prumo. Coeficientes aproximados: confira antes de usar.", verbose_name="referência da biblioteca")),
                ("observacao", models.CharField(blank=True, max_length=300, verbose_name="observação")),
                ("atualizado_em", models.DateTimeField(auto_now=True)),
                ("obra", models.ForeignKey(blank=True, help_text="Vazio = base geral, disponível para todas as obras.", null=True, on_delete=django.db.models.deletion.CASCADE, related_name="composicoes", to="obras.obra")),
            ],
            options={"ordering": ["codigo"], "verbose_name": "composição de serviço", "verbose_name_plural": "composições de serviço"},
        ),
        migrations.AddConstraint("composicao", models.UniqueConstraint(condition=models.Q(("obra__isnull", True)), fields=("codigo",), name="composicao_codigo_unico_base")),
        migrations.AddConstraint("composicao", models.UniqueConstraint(fields=("obra", "codigo"), name="composicao_codigo_unico_obra")),
        migrations.CreateModel(
            name="ItemComposicao",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("coeficiente", models.DecimalField(decimal_places=6, help_text="Quantidade do insumo para 1 unidade do serviço", max_digits=14)),
                ("composicao", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="itens", to="obras.composicao")),
                ("insumo", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="usos", to="obras.insumo")),
            ],
            options={"ordering": ["id"], "verbose_name": "insumo da composição", "verbose_name_plural": "insumos da composição"},
        ),

        # ---- orçamento: etapa vira cadastro; "insumo" texto vira observação
        migrations.RenameField("itemorcamento", "etapa", "etapa_texto"),
        migrations.RenameField("itemorcamento", "insumo", "observacao"),
        migrations.AlterField("itemorcamento", "observacao", models.CharField(blank=True, max_length=200, verbose_name="observação")),
        migrations.AddField("itemorcamento", "etapa", models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="itens", to="obras.etapa")),
        migrations.RunPython(ligar_etapas, migrations.RunPython.noop),
        migrations.RemoveField("itemorcamento", "etapa_texto"),
        migrations.AlterField("itemorcamento", "etapa", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="itens", to="obras.etapa")),
        migrations.AddField("itemorcamento", "composicao", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="usos_orcamento", to="obras.composicao")),
        migrations.AddField("itemorcamento", "codigo", models.CharField(blank=True, max_length=30, verbose_name="código da composição")),
        migrations.AlterModelOptions("itemorcamento", {"ordering": ["etapa__ordem", "etapa_id", "id"], "verbose_name": "serviço do orçamento", "verbose_name_plural": "serviços do orçamento"}),
        migrations.CreateModel(
            name="InsumoPrevisto",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("coeficiente", models.DecimalField(decimal_places=6, max_digits=14)),
                ("preco_unitario", models.DecimalField(decimal_places=4, max_digits=14)),
                ("insumo", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="previstos", to="obras.insumo")),
                ("item", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="insumos", to="obras.itemorcamento")),
            ],
            options={"ordering": ["id"], "verbose_name": "insumo previsto", "verbose_name_plural": "insumos previstos"},
        ),

        # ---- estoque ligado ao insumo
        migrations.AddField("material", "insumo", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="estoques", to="obras.insumo")),
        migrations.AlterModelOptions("material", {"ordering": ["id"], "verbose_name_plural": "materiais"}),
    ]
