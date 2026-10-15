"""Biblioteca inicial do Prumo: insumos e composições de serviço comuns.

ATENÇÃO: coeficientes e preços são APROXIMADOS, só para dar um ponto de partida.
Não são copiados do SINAPI nem do TCPO. Cada construtora deve conferir com a própria
prática (ou com a tabela de referência da região) e ajustar no cadastro.
"""
from decimal import Decimal

OBS_REFERENCIA = ("Coeficientes aproximados de referência. Confira com a sua prática "
                  "ou com o SINAPI/TCPO da sua região antes de usar.")

# código, descrição, unidade, tipo, preço de referência (R$)
INSUMOS = [
    ("I-0001", "Pedreiro", "h", "mao-de-obra", "28.00"),
    ("I-0002", "Servente", "h", "mao-de-obra", "20.00"),
    ("I-0003", "Carpinteiro", "h", "mao-de-obra", "28.00"),
    ("I-0004", "Armador", "h", "mao-de-obra", "28.00"),
    ("I-0005", "Pintor", "h", "mao-de-obra", "27.00"),
    ("I-0006", "Eletricista", "h", "mao-de-obra", "30.00"),
    ("I-0007", "Encanador", "h", "mao-de-obra", "30.00"),
    ("I-0008", "Azulejista / ladrilhista", "h", "mao-de-obra", "29.00"),
    ("I-0101", "Cimento CP-II 50 kg", "sc", "material", "34.00"),
    ("I-0102", "Areia média", "m³", "material", "120.00"),
    ("I-0103", "Brita 1", "m³", "material", "130.00"),
    ("I-0104", "Cal hidratada 20 kg", "sc", "material", "18.00"),
    ("I-0105", "Bloco cerâmico de vedação 9x19x29", "un", "material", "1.30"),
    ("I-0106", "Bloco de concreto estrutural 14x19x39", "un", "material", "4.20"),
    ("I-0107", "Aço CA-50 (vergalhão)", "kg", "material", "7.50"),
    ("I-0108", "Arame recozido nº 18", "kg", "material", "16.00"),
    ("I-0109", "Chapa compensada resinada 12 mm", "m²", "material", "48.00"),
    ("I-0110", "Prego 18x27", "kg", "material", "18.00"),
    ("I-0111", "Concreto usinado fck 25 MPa", "m³", "material", "520.00"),
    ("I-0112", "Argamassa colante AC-II", "kg", "material", "0.90"),
    ("I-0113", "Rejunte", "kg", "material", "4.00"),
    ("I-0114", "Piso porcelanato / cerâmico", "m²", "material", "60.00"),
    ("I-0115", "Revestimento cerâmico de parede", "m²", "material", "45.00"),
    ("I-0116", "Tinta acrílica", "L", "material", "22.00"),
    ("I-0117", "Massa corrida PVA", "L", "material", "6.00"),
    ("I-0118", "Selador acrílico", "L", "material", "10.00"),
    ("I-0119", "Lixa para parede", "un", "material", "1.50"),
    ("I-0120", "Telha cerâmica", "un", "material", "1.80"),
    ("I-0121", "Madeira para telhado (caibro, ripa, terça)", "m³", "material", "2800.00"),
    ("I-0122", "Manta asfáltica 3 mm", "m²", "material", "38.00"),
    ("I-0123", "Primer asfáltico", "L", "material", "15.00"),
    ("I-0124", "Eletroduto PVC flexível 3/4\"", "m", "material", "2.50"),
    ("I-0125", "Cabo flexível 2,5 mm²", "m", "material", "3.20"),
    ("I-0126", "Caixa de luz 4x2 PVC", "un", "material", "2.50"),
    ("I-0127", "Tomada ou interruptor completo", "un", "material", "18.00"),
    ("I-0128", "Tubo PVC soldável 25 mm", "m", "material", "5.50"),
    ("I-0129", "Conexão PVC soldável 25 mm (média)", "un", "material", "3.00"),
    ("I-0201", "Betoneira 400 L (aluguel)", "h", "equipamento", "3.00"),
]

# código, descrição, unidade, [(código do insumo, coeficiente por unidade do serviço)]
COMPOSICOES = [
    ("C-0001", "Limpeza manual do terreno", "m²", [("I-0002", "0.20")]),
    ("C-0002", "Escavação manual de vala", "m³", [("I-0002", "3.00")]),
    ("C-0003", "Reaterro manual compactado", "m³", [("I-0002", "1.50")]),
    ("C-0004", "Concreto fck 20 MPa feito na obra (betoneira)", "m³",
     [("I-0101", "6.60"), ("I-0102", "0.70"), ("I-0103", "0.80"), ("I-0001", "1.50"), ("I-0002", "6.00"), ("I-0201", "0.70")]),
    ("C-0005", "Lançamento de concreto usinado em estrutura", "m³",
     [("I-0111", "1.05"), ("I-0001", "1.50"), ("I-0002", "3.00")]),
    ("C-0006", "Armação com aço CA-50 (corte, dobra e montagem)", "kg",
     [("I-0107", "1.10"), ("I-0108", "0.02"), ("I-0004", "0.08"), ("I-0002", "0.08")]),
    ("C-0007", "Forma de madeira compensada para estrutura", "m²",
     [("I-0109", "0.45"), ("I-0110", "0.15"), ("I-0003", "1.20"), ("I-0002", "0.60")]),
    ("C-0008", "Alvenaria de vedação com bloco cerâmico 9x19x29", "m²",
     [("I-0105", "17.50"), ("I-0101", "0.035"), ("I-0104", "0.06"), ("I-0102", "0.012"), ("I-0001", "0.70"), ("I-0002", "0.40")]),
    ("C-0009", "Alvenaria estrutural com bloco de concreto 14x19x39", "m²",
     [("I-0106", "13.50"), ("I-0101", "0.10"), ("I-0104", "0.05"), ("I-0102", "0.018"), ("I-0001", "0.85"), ("I-0002", "0.50")]),
    ("C-0010", "Chapisco em parede (traço 1:3)", "m²",
     [("I-0101", "0.043"), ("I-0102", "0.006"), ("I-0001", "0.10"), ("I-0002", "0.10")]),
    ("C-0011", "Reboco massa única, 2 cm (traço 1:2:8)", "m²",
     [("I-0101", "0.08"), ("I-0104", "0.16"), ("I-0102", "0.025"), ("I-0001", "0.60"), ("I-0002", "0.40")]),
    ("C-0012", "Contrapiso, 4 cm (traço 1:4)", "m²",
     [("I-0101", "0.29"), ("I-0102", "0.046"), ("I-0001", "0.30"), ("I-0002", "0.40")]),
    ("C-0013", "Piso porcelanato/cerâmico com argamassa colante", "m²",
     [("I-0114", "1.10"), ("I-0112", "5.00"), ("I-0113", "0.40"), ("I-0008", "0.45"), ("I-0002", "0.25")]),
    ("C-0014", "Revestimento cerâmico de parede", "m²",
     [("I-0115", "1.10"), ("I-0112", "5.00"), ("I-0113", "0.30"), ("I-0008", "0.55"), ("I-0002", "0.30")]),
    ("C-0015", "Massa corrida PVA, 2 demãos", "m²",
     [("I-0117", "0.40"), ("I-0119", "0.20"), ("I-0005", "0.40"), ("I-0002", "0.10")]),
    ("C-0016", "Pintura acrílica com selador, 2 demãos", "m²",
     [("I-0118", "0.10"), ("I-0116", "0.17"), ("I-0119", "0.10"), ("I-0005", "0.35"), ("I-0002", "0.10")]),
    ("C-0017", "Telhado de telha cerâmica com estrutura de madeira", "m²",
     [("I-0120", "16.50"), ("I-0121", "0.025"), ("I-0110", "0.08"), ("I-0003", "0.90"), ("I-0002", "0.60")]),
    ("C-0018", "Impermeabilização com manta asfáltica 3 mm", "m²",
     [("I-0122", "1.15"), ("I-0123", "0.40"), ("I-0001", "0.40"), ("I-0002", "0.20")]),
    ("C-0019", "Ponto elétrico (tomada ou interruptor) completo", "ponto",
     [("I-0124", "6.00"), ("I-0125", "18.00"), ("I-0126", "1.00"), ("I-0127", "1.00"), ("I-0006", "1.20"), ("I-0002", "0.60")]),
    ("C-0020", "Ponto de água fria em PVC 25 mm", "ponto",
     [("I-0128", "3.50"), ("I-0129", "3.00"), ("I-0007", "1.50"), ("I-0002", "0.80")]),
    ("C-0021", "Limpeza final da obra", "m²", [("I-0002", "0.30")]),
]


def carregar_biblioteca(Insumo, Composicao, ItemComposicao):
    """Cria na base geral o que ainda não existe (pelo código). Não altera o que já está lá.
    Recebe os modelos para funcionar também dentro de uma migração."""
    criados = 0
    for cod, desc, un, tipo, preco in INSUMOS:
        _, novo = Insumo.objects.get_or_create(obra=None, codigo=cod, defaults=dict(descricao=desc, unidade=un, tipo=tipo, preco=Decimal(preco)))
        criados += novo
    por_codigo = {i.codigo: i for i in Insumo.objects.filter(obra=None)}
    for cod, desc, un, itens in COMPOSICOES:
        if Composicao.objects.filter(obra=None, codigo=cod).exists():
            continue
        if any(c not in por_codigo for c, _ in itens):
            continue  # algum insumo da composição foi apagado da base
        comp = Composicao.objects.create(obra=None, codigo=cod, descricao=desc, unidade=un, referencia=True, observacao=OBS_REFERENCIA)
        ItemComposicao.objects.bulk_create([ItemComposicao(composicao=comp, insumo=por_codigo[c], coeficiente=Decimal(k)) for c, k in itens])
        criados += 1
    return criados
