from decimal import Decimal

from django.conf import settings
from django.db import models

D0 = Decimal("0")


class Obra(models.Model):
    """Uma obra tem um dono e, opcionalmente, outros usuários com acesso a ela."""
    dono = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="obras",
        help_text="Responsável pela obra. É o único (além do administrador) que pode apagar todos os dados dela ou importar planilha por cima.",
    )
    membros = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name="obras_compartilhadas",
        verbose_name="outros usuários com acesso",
        help_text="Essas pessoas também abrem esta obra no app e podem lançar notas, consumos, medições e pagamentos. "
                  "Se a pessoa tiver mais de uma obra, ela troca de obra pelo seletor no topo do app.",
    )
    nome = models.CharField(max_length=200, default="Minha obra")
    cliente = models.CharField(max_length=200, blank=True)
    prazo = models.DateField(null=True, blank=True)
    valor_contratado = models.DecimalField(max_digits=14, decimal_places=2, default=D0)
    exemplo = models.BooleanField(default=False, help_text="Dados de exemplo carregados automaticamente")
    criada_em = models.DateTimeField(auto_now_add=True)
    atualizada_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["dono__username", "id"]

    def __str__(self):
        return f"{self.nome} ({self.dono})"


ETAPAS_PADRAO = [
    "Serviços preliminares", "Fundação", "Estrutura", "Alvenaria", "Cobertura",
    "Instalações elétricas", "Instalações hidrossanitárias", "Esquadrias", "Revestimentos",
    "Pisos", "Pintura", "Louças e metais", "Limpeza e entrega",
]


class Etapa(models.Model):
    """Etapa (fase) de uma obra. Os serviços do orçamento ficam dentro de uma etapa."""
    obra = models.ForeignKey(Obra, on_delete=models.CASCADE, related_name="etapas")
    nome = models.CharField(max_length=120)
    ordem = models.PositiveIntegerField(default=0)
    percentual = models.DecimalField("avanço físico (%)", max_digits=5, decimal_places=2, default=D0)

    class Meta:
        ordering = ["ordem", "id"]
        constraints = [models.UniqueConstraint(fields=["obra", "nome"], name="etapa_unica_por_obra")]
        verbose_name = "etapa da obra"
        verbose_name_plural = "etapas da obra"

    def __str__(self):
        return self.nome


# ---------------------------------------------------------------- catálogo
class Insumo(models.Model):
    """O que um serviço consome: material, mão de obra, equipamento ou empreitada.
    Sem obra = base geral (todas as obras usam). Com obra = só daquela obra."""
    MATERIAL, MAO_DE_OBRA, EQUIPAMENTO, EMPREITADA = "material", "mao-de-obra", "equipamento", "empreitada"
    TIPOS = [(MATERIAL, "Material"), (MAO_DE_OBRA, "Mão de obra"), (EQUIPAMENTO, "Equipamento"), (EMPREITADA, "Empreitada / terceiro")]
    obra = models.ForeignKey(Obra, null=True, blank=True, on_delete=models.CASCADE, related_name="insumos",
                             help_text="Vazio = base geral, disponível para todas as obras.")
    codigo = models.CharField("código", max_length=30)
    descricao = models.CharField("descrição", max_length=200)
    unidade = models.CharField(max_length=20)
    tipo = models.CharField(max_length=12, choices=TIPOS, default=MATERIAL)
    preco = models.DecimalField("preço de referência", max_digits=14, decimal_places=4, default=D0)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["codigo"]
        constraints = [
            models.UniqueConstraint(fields=["codigo"], condition=models.Q(obra__isnull=True), name="insumo_codigo_unico_base"),
            models.UniqueConstraint(fields=["obra", "codigo"], name="insumo_codigo_unico_obra"),
        ]

    def __str__(self):
        return f"{self.codigo} · {self.descricao} ({self.unidade})"


class Composicao(models.Model):
    """Composição de serviço: quanto de cada insumo é preciso para 1 unidade do serviço."""
    obra = models.ForeignKey(Obra, null=True, blank=True, on_delete=models.CASCADE, related_name="composicoes",
                             help_text="Vazio = base geral, disponível para todas as obras.")
    codigo = models.CharField("código", max_length=30)
    descricao = models.CharField("descrição", max_length=200)
    unidade = models.CharField(max_length=20)
    referencia = models.BooleanField("referência da biblioteca", default=False,
                                     help_text="Veio da biblioteca inicial do Prumo. Coeficientes aproximados: confira antes de usar.")
    observacao = models.CharField("observação", max_length=300, blank=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["codigo"]
        verbose_name = "composição de serviço"
        verbose_name_plural = "composições de serviço"
        constraints = [
            models.UniqueConstraint(fields=["codigo"], condition=models.Q(obra__isnull=True), name="composicao_codigo_unico_base"),
            models.UniqueConstraint(fields=["obra", "codigo"], name="composicao_codigo_unico_obra"),
        ]

    def __str__(self):
        return f"{self.codigo} · {self.descricao} ({self.unidade})"

    @property
    def custo_unitario(self):
        return sum((i.coeficiente * i.insumo.preco for i in self.itens.all()), D0)


class ItemComposicao(models.Model):
    composicao = models.ForeignKey(Composicao, on_delete=models.CASCADE, related_name="itens")
    insumo = models.ForeignKey(Insumo, on_delete=models.PROTECT, related_name="usos")
    coeficiente = models.DecimalField(max_digits=14, decimal_places=6, help_text="Quantidade do insumo para 1 unidade do serviço")

    class Meta:
        ordering = ["id"]
        verbose_name = "insumo da composição"
        verbose_name_plural = "insumos da composição"

    def __str__(self):
        return f"{self.insumo.codigo} × {self.coeficiente.normalize():f}"


class ItemOrcamento(models.Model):
    """Serviço do orçamento. Com composição: preço e insumos previstos vêm dela (congelados na data).
    Sem composição: serviço "por verba", só com o valor."""
    obra = models.ForeignKey(Obra, on_delete=models.CASCADE, related_name="orcamento")
    etapa = models.ForeignKey(Etapa, on_delete=models.PROTECT, related_name="itens")
    composicao = models.ForeignKey(Composicao, null=True, blank=True, on_delete=models.SET_NULL, related_name="usos_orcamento")
    codigo = models.CharField("código da composição", max_length=30, blank=True)
    servico = models.CharField(max_length=200)
    observacao = models.CharField("observação", max_length=200, blank=True)
    unidade = models.CharField(max_length=20)
    quantidade = models.DecimalField(max_digits=14, decimal_places=4)
    preco_unitario = models.DecimalField(max_digits=14, decimal_places=4)

    class Meta:
        ordering = ["etapa__ordem", "etapa_id", "id"]
        verbose_name = "serviço do orçamento"
        verbose_name_plural = "serviços do orçamento"

    @property
    def planejado(self):
        return self.quantidade * self.preco_unitario

    def __str__(self):
        return f"{self.etapa} · {self.servico}"


class InsumoPrevisto(models.Model):
    """Cópia da composição no momento em que o serviço entrou no orçamento.
    Mudar o preço do insumo depois não altera o orçado (a não ser que você peça para atualizar)."""
    item = models.ForeignKey(ItemOrcamento, on_delete=models.CASCADE, related_name="insumos")
    insumo = models.ForeignKey(Insumo, on_delete=models.PROTECT, related_name="previstos")
    coeficiente = models.DecimalField(max_digits=14, decimal_places=6)
    preco_unitario = models.DecimalField(max_digits=14, decimal_places=4)

    class Meta:
        ordering = ["id"]
        verbose_name = "insumo previsto"
        verbose_name_plural = "insumos previstos"

    def __str__(self):
        return f"{self.insumo.codigo} no serviço {self.item}"


class Fornecedor(models.Model):
    obra = models.ForeignKey(Obra, on_delete=models.CASCADE, related_name="fornecedores")
    nome = models.CharField(max_length=200)
    contato = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["id"]
        verbose_name_plural = "fornecedores"

    def __str__(self):
        return self.nome


class Material(models.Model):
    """Saldo de um material no estoque desta obra. Ligado a um insumo do cadastro."""
    obra = models.ForeignKey(Obra, on_delete=models.CASCADE, related_name="materiais")
    insumo = models.ForeignKey(Insumo, null=True, blank=True, on_delete=models.PROTECT, related_name="estoques")
    nome = models.CharField(max_length=200)
    unidade = models.CharField(max_length=20)
    saldo = models.DecimalField(max_digits=16, decimal_places=4, default=D0)
    custo_medio = models.DecimalField(max_digits=16, decimal_places=6, default=D0)

    class Meta:
        ordering = ["id"]
        verbose_name_plural = "materiais"

    def __str__(self):
        return f"{self.nome} ({self.unidade})"


class NotaFiscal(models.Model):
    """Documento de entrada de material: nota fiscal ou outro documento que será pago."""
    TIPOS = [("nota_fiscal", "Nota fiscal"), ("recibo", "Recibo"), ("fatura", "Fatura"), ("outro", "Outro documento")]
    obra = models.ForeignKey(Obra, on_delete=models.CASCADE, related_name="notas")
    tipo = models.CharField(max_length=12, choices=TIPOS, default="nota_fiscal")
    fornecedor = models.ForeignKey(Fornecedor, on_delete=models.PROTECT, related_name="notas")
    numero = models.CharField(max_length=60)
    data = models.DateField(help_text="Vencimento do pagamento ao fornecedor")
    criada_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        verbose_name = "nota fiscal"
        verbose_name_plural = "notas fiscais"

    def __str__(self):
        return self.numero


class ItemNota(models.Model):
    nota = models.ForeignKey(NotaFiscal, on_delete=models.CASCADE, related_name="itens")
    material = models.ForeignKey(Material, on_delete=models.PROTECT, related_name="entradas")
    # Serviço do orçamento para o qual o material foi comprado (opcional). Não é gasto: o gasto é a baixa.
    item = models.ForeignKey(ItemOrcamento, null=True, blank=True, on_delete=models.PROTECT, related_name="compras")
    quantidade = models.DecimalField(max_digits=16, decimal_places=4)
    valor_unitario = models.DecimalField(max_digits=16, decimal_places=4)

    class Meta:
        ordering = ["id"]


class Consumo(models.Model):
    """Baixa de estoque: retirada de material para um serviço do orçamento (consumo) ou
    saída sem serviço (perda, quebra, ajuste de inventário, devolução)."""
    SERVICO, PERDA, QUEBRA, AJUSTE, DEVOLUCAO = "servico", "perda", "quebra", "ajuste", "devolucao"
    TIPOS = [(SERVICO, "Uso em serviço"), (PERDA, "Perda ou furto"), (QUEBRA, "Quebra"),
             (AJUSTE, "Ajuste de inventário"), (DEVOLUCAO, "Devolução ao fornecedor")]
    obra = models.ForeignKey(Obra, on_delete=models.CASCADE, related_name="consumos")
    item = models.ForeignKey(ItemOrcamento, null=True, blank=True, on_delete=models.PROTECT, related_name="consumos")
    tipo = models.CharField(max_length=12, choices=TIPOS, default=SERVICO)
    observacao = models.CharField(max_length=200, blank=True)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    material = models.ForeignKey(Material, on_delete=models.PROTECT, related_name="consumos")
    quantidade = models.DecimalField(max_digits=16, decimal_places=4)
    quantidade_solicitada = models.DecimalField(max_digits=16, decimal_places=4)
    valor = models.DecimalField(max_digits=16, decimal_places=2)
    data = models.DateField()
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        verbose_name = "consumo de material"
        verbose_name_plural = "consumos de material"


class Empreiteiro(models.Model):
    obra = models.ForeignKey(Obra, on_delete=models.CASCADE, related_name="empreiteiros")
    nome = models.CharField(max_length=200)
    contato = models.CharField(max_length=200, blank=True)
    especialidade = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return self.nome


class Contrato(models.Model):
    obra = models.ForeignKey(Obra, on_delete=models.CASCADE, related_name="contratos")
    empreiteiro = models.ForeignKey(Empreiteiro, on_delete=models.PROTECT, related_name="contratos")
    item = models.ForeignKey(ItemOrcamento, on_delete=models.PROTECT, related_name="contratos")
    valor_contratado = models.DecimalField(max_digits=14, decimal_places=2)
    forma_pagamento = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.empreiteiro} · {self.item.servico}"


class Medicao(models.Model):
    PENDENTE, APROVADA = "pendente", "aprovada"
    obra = models.ForeignKey(Obra, on_delete=models.CASCADE, related_name="medicoes")
    contrato = models.ForeignKey(Contrato, on_delete=models.PROTECT, related_name="medicoes")
    data = models.DateField()
    percentual = models.DecimalField(max_digits=6, decimal_places=2)
    valor = models.DecimalField(max_digits=14, decimal_places=2)
    status = models.CharField(max_length=10, choices=[(PENDENTE, "Pendente"), (APROVADA, "Aprovada")], default=PENDENTE)
    aprovada_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    aprovada_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["id"]
        verbose_name = "medição"
        verbose_name_plural = "medições"


class Pagamento(models.Model):
    MATERIAL, MAO_DE_OBRA, AVULSO = "material", "mao-de-obra", "avulso"
    PROGRAMADO, PAGO = "programado", "pago"
    obra = models.ForeignKey(Obra, on_delete=models.CASCADE, related_name="pagamentos")
    tipo = models.CharField(max_length=12, choices=[(MATERIAL, "Material"), (MAO_DE_OBRA, "Mão de obra"), (AVULSO, "Avulso")])
    origem = models.CharField(max_length=200)
    item = models.ForeignKey(ItemOrcamento, null=True, blank=True, on_delete=models.PROTECT, related_name="pagamentos")
    valor = models.DecimalField(max_digits=14, decimal_places=2)
    data_programada = models.DateField()
    data_pagamento = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=[(PROGRAMADO, "Programado"), (PAGO, "Pago")], default=PROGRAMADO)
    medicao = models.OneToOneField(Medicao, null=True, blank=True, on_delete=models.CASCADE, related_name="pagamento")
    nota = models.OneToOneField(NotaFiscal, null=True, blank=True, on_delete=models.CASCADE, related_name="pagamento")

    class Meta:
        ordering = ["id"]
