"""Carga do SINAPI pelo site: o navegador do administrador lê o xlsx (arquivo grande demais para uma função da
Vercel, limite de 4,5 MB por envio) e manda os dados já extraídos em partes pequenas. As partes ficam numa tabela de
passagem e cada etapa (estrutura, depois uma UF+regime por vez) roda numa transação própria, com a mesma gravação e
a mesma conferência de custo do comando `carregar_sinapi`."""
import json
import re
import uuid
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from . import carga as C
from .models import Carga, CargaParte, Referencia

TIPOS_PARTE = {"comps", "itens", "insumos", "precos", "custos"}
POR_REGIME = {"precos", "custos"}
REGIMES = ("sd", "cd", "se")
MAX_PARTE = 2_300_000  # caracteres de JSON por envio (Django lê até 2,5 MB do corpo; a Vercel, 4,5 MB)


class ErroCargaWeb(C.ErroCarga):
    pass


def _meta(carga_id):
    p = CargaParte.objects.filter(carga_id=carga_id, tipo="meta").first()
    if not p:
        raise ErroCargaWeb("Carga não encontrada ou expirada. Comece de novo.")
    return json.loads(p.dados)


def iniciar(d):
    base = str(d.get("base") or "")
    m = re.fullmatch(r"(\d{4})-(\d{2})", base)
    if not m or not 1 <= int(m.group(2)) <= 12:
        raise ErroCargaWeb("Mês de referência inválido (use AAAA-MM).")
    ufs = [str(u).upper() for u in d.get("ufs") or []]
    if not ufs or any(not re.fullmatch(r"[A-Z]{2}", u) for u in ufs) or len(set(ufs)) != len(ufs):
        raise ErroCargaWeb("Escolha pelo menos uma UF (2 letras, sem repetir).")
    regimes = list(d.get("regimes") or [])
    if not regimes or any(r not in REGIMES for r in regimes) or len(set(regimes)) != len(regimes):
        raise ErroCargaWeb("Escolha pelo menos um regime (sd, cd ou se).")
    digest = str(d.get("sha256") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ErroCargaWeb("Impressão digital (sha256) do arquivo inválida.")
    CargaParte.objects.filter(criada_em__lt=timezone.now() - timedelta(days=1)).delete()
    cid = uuid.uuid4().hex
    leitura = sorted(set(ufs) | {C.UF_FALLBACK})
    meta = dict(base=base, ufs=ufs, regimes=regimes, sha256=digest, arquivo=str(d.get("arquivo") or "")[:300], ufs_leitura=leitura)
    CargaParte.objects.create(carga_id=cid, tipo="meta", dados=json.dumps(meta))
    data_base = date(int(m.group(1)), int(m.group(2)), 1)
    ja = sorted(f"{r.uf}/{r.regime}" for r in Referencia.objects.filter(data_base=data_base, cargas__sha256=digest))
    return dict(cargaId=cid, ufsLeitura=leitura, jaCarregadas=ja)


def guardar_parte(carga_id, tipo, regime, ordem, dados):
    _meta(carga_id)
    if tipo not in TIPOS_PARTE:
        raise ErroCargaWeb("Tipo de parte desconhecido.")
    if tipo in POR_REGIME and regime not in REGIMES:
        raise ErroCargaWeb("Regime da parte inválido.")
    if not isinstance(dados, list) or not isinstance(ordem, int) or ordem < 0:
        raise ErroCargaWeb("Parte inválida.")
    texto = json.dumps(dados, separators=(",", ":"))
    if len(texto) > MAX_PARTE:
        raise ErroCargaWeb("Parte grande demais; envie em pedaços menores.")
    CargaParte.objects.update_or_create(carga_id=carga_id, tipo=tipo, regime=regime if tipo in POR_REGIME else "", ordem=ordem,
                                        defaults={"dados": texto})
    return len(dados)


def _linhas(carga_id, tipo, regime=""):
    out = []
    for p in CargaParte.objects.filter(carga_id=carga_id, tipo=tipo, regime=regime).order_by("ordem"):
        out += json.loads(p.dados)
    return out


def _dec(v):
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v))
    except InvalidOperation:
        raise ErroCargaWeb(f"Número inválido recebido: {v!r}")


def _estrutura(carga_id):
    comps = {}
    for cod, grupo, desc, un, sit in _linhas(carga_id, "comps"):
        comps[int(cod)] = dict(grupo=str(grupo), descricao=str(desc), unidade=str(un), situacao=str(sit))
    if not comps:
        raise ErroCargaWeb("A estrutura (Analítico) não foi enviada.")
    itens = []
    for r in _linhas(carga_id, "itens"):
        cod, ordem, tipo, alvo, coef, sem = r[:6]
        desc, un = (r[6], r[7]) if len(r) >= 8 else ("", "")
        if int(cod) not in comps:
            raise ErroCargaWeb(f"Item da composição {cod}, que não foi definida.")
        itens.append((int(cod), int(ordem), "composicao" if tipo else "insumo", int(alvo), str(desc), str(un), _dec(coef), "SEM PREÇO" if sem else ""))
    info = {}
    for cod, classe, desc, un in _linhas(carga_id, "insumos"):
        info[int(cod)] = dict(classificacao=str(classe), descricao=str(desc), unidade=str(un), coleta="")
    return comps, itens, info


def _regime(carga_id, meta, regime):
    ufs = meta["ufs_leitura"]
    precos = {}
    for r in _linhas(carga_id, "precos", regime):
        cod, coleta, *vals = r
        if len(vals) != len(ufs):
            raise ErroCargaWeb("Preços com número de UFs diferente do combinado.")
        precos[int(cod)] = dict(coleta=str(coleta), precos={uf: _dec(v) for uf, v in zip(ufs, vals)})
    custos = {}
    for r in _linhas(carga_id, "custos", regime):
        cod, *vals = r
        if len(vals) != 2 * len(ufs):
            raise ErroCargaWeb("Custos com número de UFs diferente do combinado.")
        custos[int(cod)] = dict(custos={uf: ((lambda c: c if c and c > 0 else None)(_dec(vals[2 * i])), _dec(vals[2 * i + 1]) or Decimal(0))
                                        for i, uf in enumerate(ufs)})
    return precos, custos


def _juntar(info, precos):
    """Dados de cada insumo: o que veio da lista de insumos + o que veio da aba de preços (inclui os que só existem no Analítico)."""
    return {c: {**info.get(c, {}), **precos.get(c, {})} for c in set(info) | set(precos)}


def aplicar_estrutura(carga_id):
    """Etapa 1: grava insumos, composições e itens (só se o arquivo ainda não foi carregado)."""
    meta = _meta(carga_id)
    comps, itens, info = _estrutura(carga_id)
    profundidade = C.verificar_estrutura(comps, itens)
    dados = {rg: _regime(carga_id, meta, rg) for rg in meta["regimes"]}
    for rg, (p, custos) in dados.items():
        if not p:
            raise ErroCargaWeb(f"Os preços do regime {rg} não foram enviados.")
        if set(custos) != set(comps):
            raise ErroCargaWeb(f"Os custos do regime {rg} e o Analítico não têm as mesmas composições.")
    precos_regimes = [p for p, _c in dados.values()]
    # insumos: as abas de preço (info enviada) + os que só existem no Analítico
    info_ins, sem_preco = C.montar_insumos([_juntar(info, p) for p in precos_regimes], itens)
    nova = not Carga.objects.filter(sha256=meta["sha256"]).exists()
    if nova:
        with transaction.atomic():
            C.gravar_estrutura(comps, itens, info_ins, sem_preco)
    return dict(estruturaNova=nova, composicoes=len(comps), itens=len(itens), insumos=len(info_ins), profundidadeMax=profundidade,
                unidadesForaDoMapa=C.unidades_fora_do_mapa(info_ins, comps))


def aplicar_referencia(carga_id, uf, regime):
    """Etapa 2 (uma por UF e regime): preços com fallback de SP, custos e conferência. Tudo ou nada por referência."""
    meta = _meta(carga_id)
    uf = str(uf).upper()
    if uf not in meta["ufs"] or regime not in meta["regimes"]:
        raise ErroCargaWeb("UF ou regime que não foram combinados no início da carga.")
    comps, itens, info = _estrutura(carga_id)
    precos, custos = _regime(carga_id, meta, regime)
    info_ins, _sem = C.montar_insumos([_juntar(info, precos)], itens)
    ano, mes = meta["base"].split("-")
    with transaction.atomic():
        return C.gravar_referencia(uf, regime, date(int(ano), int(mes), 1), info_ins, precos, custos, itens, meta["sha256"], meta["arquivo"])


def concluir(carga_id):
    CargaParte.objects.filter(carga_id=carga_id).delete()
