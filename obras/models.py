from decimal import Decimal

from django.conf import settings
from django.db import models

D0 = Decimal("0")


class Obra(models.Model):
    """Uma obra pertence a um usuário. No MVP cada usuário tem uma obra."""
    dono = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="obras")
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


class EtapaAvanco(models.Model):
    obra = models.ForeignKey(Obra, on_delete=models.CASCADE, related_name="etapas")
    etapa = models.CharField(max_length=120)
    percentual = models.DecimalField(max_digits=5, decimal_places=2, default=D0)

    class Meta:
        unique_together = [("obra", "etapa")]
        verbose_name = "avanço físico por etapa"
        verbose_name_plural = "avanços físicos por etapa"


class ItemOrcamento(models.Model):
    obra = models.ForeignKey(Obra, on_delete=models.CASCADE, related_name="orcamento")
    etapa = models.CharField(max_length=120)
    servico = models.CharField(max_length=200)
    insumo = models.CharField(max_length=200, blank=True)
    unidade = models.CharField(max_length=20)
    quantidade = models.DecimalField(max_digits=14, decimal_places=4)
    preco_unitario = models.DecimalField(max_digits=14, decimal_places=4)

    class Meta:
        ordering = ["id"]
        verbose_name = "serviço do orçamento"
        verbose_name_plural = "serviços do orçamento"

    @property
    def planejado(self):
        return self.quantidade * self.preco_unitario

    def __str__(self):
        return f"{self.etapa} · {self.servico}"


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
    obra = models.ForeignKey(Obra, on_delete=models.CASCADE, related_name="materiais")
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
    obra = models.ForeignKey(Obra, on_delete=models.CASCADE, related_name="notas")
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
    quantidade = models.DecimalField(max_digits=16, decimal_places=4)
    valor_unitario = models.DecimalField(max_digits=16, decimal_places=4)

    class Meta:
        ordering = ["id"]


class Consumo(models.Model):
    """Retirada de material do estoque para um serviço do orçamento."""
    obra = models.ForeignKey(Obra, on_delete=models.CASCADE, related_name="consumos")
    item = models.ForeignKey(ItemOrcamento, on_delete=models.PROTECT, related_name="consumos")
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
