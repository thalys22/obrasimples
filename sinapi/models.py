"""Base de consulta do SINAPI (somente leitura para o usuário).

Nenhum model do app `obras` aponta para estas tabelas: ao usar uma composição, o Prumo
COPIA os dados para a obra (ver docs/sinapi-integracao.md). Por isso estas tabelas podem
ser recarregadas ou podadas sem quebrar nenhum orçamento.
"""
from django.db import models


class Referencia(models.Model):
    SD, CD, SE = "sd", "cd", "se"
    REGIMES = [(SD, "Sem desoneração"), (CD, "Com desoneração"), (SE, "Sem encargos sociais")]

    uf = models.CharField(max_length=2)
    data_base = models.DateField(help_text="Primeiro dia do mês de referência.")
    regime = models.CharField(max_length=2, choices=REGIMES)
    carregada_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["uf", "data_base", "regime"], name="sinapi_referencia_unica")]
        ordering = ["-data_base", "uf", "regime"]

    def __str__(self):
        return f"{self.uf} {self.data_base:%m/%Y} {self.regime}"


class Insumo(models.Model):
    codigo = models.PositiveIntegerField(unique=True)
    descricao = models.CharField(max_length=400)
    unidade = models.CharField(max_length=12)
    classificacao = models.CharField(max_length=60, blank=True, help_text="Texto original da aba de preços; vazio se o insumo só aparece no Analítico.")
    tipo = models.CharField(max_length=12, help_text="Tipo já mapeado para o Prumo (material, mao-de-obra, equipamento, empreitada).")
    sem_preco_nacional = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.codigo} {self.descricao}"


class PrecoInsumo(models.Model):
    LOCAL, SP = "local", "sp"
    referencia = models.ForeignKey(Referencia, on_delete=models.CASCADE, related_name="precos")
    insumo = models.ForeignKey(Insumo, on_delete=models.CASCADE, related_name="precos")
    preco = models.DecimalField(max_digits=16, decimal_places=4, null=True, blank=True)
    origem_preco = models.CharField(max_length=5, blank=True, help_text="local, sp (fallback de São Paulo) ou vazio quando não há preço.")
    coleta = models.CharField(max_length=4, blank=True, help_text="Coluna 'Origem de Preço' do arquivo: C ou CR.")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["referencia", "insumo"], name="sinapi_preco_unico")]


class Composicao(models.Model):
    codigo = models.PositiveIntegerField(unique=True)
    descricao = models.CharField(max_length=400)
    busca = models.CharField(max_length=400, db_index=False, help_text="Descrição normalizada (minúscula, sem acento) para a busca.")
    unidade = models.CharField(max_length=12)
    grupo = models.CharField(max_length=200, db_index=True)
    situacao_nacional = models.CharField(max_length=20, blank=True)
    orcavel = models.BooleanField(default=True, help_text="Falso para composições internas (custos horários, livro de parâmetros).")

    def __str__(self):
        return f"{self.codigo} {self.descricao}"


class ComposicaoItem(models.Model):
    INSUMO, COMPOSICAO = "insumo", "composicao"
    composicao = models.ForeignKey(Composicao, on_delete=models.CASCADE, related_name="itens")
    tipo_item = models.CharField(max_length=10)
    insumo = models.ForeignKey(Insumo, null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    composicao_filha = models.ForeignKey(Composicao, null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    coeficiente = models.DecimalField(max_digits=18, decimal_places=8)
    ordem = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["composicao_id", "ordem"]
        constraints = [
            models.CheckConstraint(
                condition=(models.Q(tipo_item="insumo", insumo__isnull=False, composicao_filha__isnull=True)
                           | models.Q(tipo_item="composicao", insumo__isnull=True, composicao_filha__isnull=False)),
                name="sinapi_item_um_alvo",
            )
        ]


class CustoComposicao(models.Model):
    referencia = models.ForeignKey(Referencia, on_delete=models.CASCADE, related_name="custos")
    composicao = models.ForeignKey(Composicao, on_delete=models.CASCADE, related_name="custos")
    custo_publicado = models.DecimalField(max_digits=16, decimal_places=4, null=True, blank=True)
    pct_as = models.DecimalField(max_digits=7, decimal_places=4, default=0, help_text="Fração do custo obtida com preços de São Paulo (0 a 1).")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["referencia", "composicao"], name="sinapi_custo_unico")]


class Carga(models.Model):
    OK = "ok"
    referencia = models.ForeignKey(Referencia, on_delete=models.CASCADE, related_name="cargas")
    arquivo = models.CharField(max_length=300)
    sha256 = models.CharField(max_length=64)
    status = models.CharField(max_length=10, default=OK)
    linhas = models.PositiveIntegerField(default=0)
    avisos = models.TextField(blank=True)
    criada_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["referencia", "sha256"], name="sinapi_carga_unica")]
