"""Mapas de unidade, tipo e grupos internos (completos para o arquivo 09/2026)."""
import unicodedata

UNIDADES = {
    "M2": "m²", "M3": "m³", "H": "h", "KG": "kg", "UN": "un", "T": "t", "L": "l", "M": "m",
    "MES": "mês", "KWH": "kWh",
}
# Compostas e específicas (CHP, CHI, CJ, PAR, CENTO, MIL, JG, SC25KG, M3XKM...) ficam como vieram, em minúsculas.
TIPOS = {
    "MATERIAL": "material",
    "MAO DE OBRA": "mao-de-obra",
    "ENCARGOS COMPLEMENTARES": "mao-de-obra",
    "EQUIPAMENTO (AQUISICAO)": "equipamento",
    "EQUIPAMENTO (LOCACAO)": "equipamento",
    "SERVICOS": "empreitada",
    "ESPECIAIS": "material",
}
GRUPOS_INTERNOS = (
    "depreciacao, juros",
    "custos horarios produtivo",
    "livro sinapi",
)


def normalizar(texto):
    t = unicodedata.normalize("NFKD", str(texto or ""))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(t.casefold().split())


def unidade_prumo(unidade):
    u = str(unidade or "").strip()
    return UNIDADES.get(u.upper(), u.lower())


def unidade_conhecida(unidade):
    u = str(unidade or "").strip().upper()
    return u in UNIDADES or u in UNIDADES_COMPOSTAS


UNIDADES_COMPOSTAS = {
    "CHI", "CHP", "UNXKM", "TXKM", "M3XKM", "MXKM", "M2XKM", "KGXKM", "LXKM", "CJ", "PAR", "CENTO", "JG",
    "M/MES", "DIA", "UNXMES", "SC25KG", "MIL", "100M", "M2XMES", "MXMES", "310ML",
}


def tipo_do_insumo(classificacao):
    return TIPOS.get(normalizar(classificacao).upper(), "material")


def grupo_interno(grupo):
    g = normalizar(grupo)
    return any(g.startswith(p) for p in GRUPOS_INTERNOS)
