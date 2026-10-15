"""Camada de serviço do SINAPI: a ÚNICA porta de entrada para o resto do Prumo.

O contrato é desenhado como uma API (dicts simples); se o SINAPI virar um serviço separado,
troca-se esta implementação por um cliente HTTP sem mexer em quem a chama.
"""
from datetime import date
from decimal import Decimal

from . import mapas
from .models import Composicao, ComposicaoItem, CustoComposicao, PrecoInsumo, Referencia

LIMITE_MAX = 50
MIN_BUSCA = 2


class SinapiErro(Exception):
    pass


def _data(base):
    if isinstance(base, date):
        return base.replace(day=1)
    try:
        ano, mes = str(base)[:7].split("-")
        return date(int(ano), int(mes), 1)
    except ValueError:
        raise SinapiErro("Data-base inválida. Use AAAA-MM.")


def _referencia(uf, base, regime):
    try:
        return Referencia.objects.get(uf=str(uf).upper(), data_base=_data(base), regime=regime)
    except Referencia.DoesNotExist:
        raise SinapiErro("Essa combinação de UF, mês e regime não está carregada.")


def referencias_disponiveis():
    return [dict(uf=r.uf, data_base=r.data_base.strftime("%Y-%m"), regime=r.regime) for r in Referencia.objects.all()]


def buscar_composicoes(q, uf, base, regime, grupo=None, limite=20, deslocamento=0, incluir_sem_custo=False, incluir_internas=False):
    ref = _referencia(uf, base, regime)
    palavras = mapas.normalizar(q).split()
    if sum(len(p) for p in palavras) < MIN_BUSCA:
        raise SinapiErro(f"Digite pelo menos {MIN_BUSCA} caracteres para buscar.")
    limite = max(1, min(int(limite), LIMITE_MAX))
    deslocamento = max(0, int(deslocamento))
    qs = CustoComposicao.objects.filter(referencia=ref).select_related("composicao")
    if not incluir_sem_custo:
        qs = qs.filter(custo_publicado__isnull=False)
    if not incluir_internas:
        qs = qs.filter(composicao__orcavel=True)
    if grupo:
        qs = qs.filter(composicao__grupo=grupo)
    for p in palavras:
        qs = qs.filter(composicao__busca__contains=p)
    qs = qs.order_by("composicao__descricao", "composicao__codigo")
    total = qs.count()
    itens = [dict(codigo=c.composicao.codigo, descricao=c.composicao.descricao, unidade=mapas.unidade_prumo(c.composicao.unidade),
                  grupo=c.composicao.grupo, custo=c.custo_publicado, pct_as=c.pct_as)
             for c in qs[deslocamento:deslocamento + limite]]
    return dict(total=total, itens=itens)


def grupos(uf, base, regime):
    ref = _referencia(uf, base, regime)
    return sorted(Composicao.objects.filter(custos__referencia=ref, custos__custo_publicado__isnull=False, orcavel=True)
                  .values_list("grupo", flat=True).distinct())


def _achatar(comp_id, fator, cache, acc, estrutura, nivel=0):
    if comp_id not in cache:
        cache[comp_id] = list(ComposicaoItem.objects.filter(composicao_id=comp_id).select_related("insumo", "composicao_filha"))
    for it in cache[comp_id]:
        if it.tipo_item == "insumo":
            acc[it.insumo_id] = acc.get(it.insumo_id, Decimal(0)) + fator * it.coeficiente
            estrutura.append(dict(nivel=nivel, tipo="insumo", codigo=it.insumo.codigo, descricao=it.insumo.descricao,
                                  unidade=mapas.unidade_prumo(it.insumo.unidade), coef=it.coeficiente))
        else:
            f = it.composicao_filha
            estrutura.append(dict(nivel=nivel, tipo="composicao", codigo=f.codigo, descricao=f.descricao,
                                  unidade=mapas.unidade_prumo(f.unidade), coef=it.coeficiente))
            _achatar(f.id, fator * it.coeficiente, cache, acc, estrutura, nivel + 1)


def obter_composicao(codigo, uf, base, regime):
    ref = _referencia(uf, base, regime)
    try:
        comp = Composicao.objects.get(codigo=int(codigo))
    except (Composicao.DoesNotExist, ValueError):
        raise SinapiErro("Composição não encontrada.")
    custo = CustoComposicao.objects.filter(referencia=ref, composicao=comp).first()
    acc, estrutura = {}, []
    _achatar(comp.id, Decimal(1), {}, acc, estrutura)
    precos = {p.insumo_id: p for p in PrecoInsumo.objects.filter(referencia=ref, insumo_id__in=acc).select_related("insumo")}
    from .models import Insumo
    ins = {i.id: i for i in Insumo.objects.filter(id__in=acc)}
    itens, calc, faltam, sp = [], Decimal(0), 0, 0
    for iid, coef in acc.items():
        i, p = ins[iid], precos.get(iid)
        preco = p.preco if p else None
        origem = p.origem_preco if p else ""
        if preco is None:
            faltam += 1
        else:
            calc += coef * preco
        sp += origem == "sp"
        itens.append(dict(codigo_insumo=i.codigo, descricao=i.descricao, unidade=mapas.unidade_prumo(i.unidade), tipo=i.tipo,
                          coef=coef, preco=preco, origem_preco=origem))
    itens.sort(key=lambda x: (-(x["preco"] or 0) * x["coef"], x["descricao"]))
    publicado = custo.custo_publicado if custo else None
    pct = custo.pct_as if custo else Decimal(0)
    avisos = []
    if publicado is None:
        avisos.append("O SINAPI não publicou custo para esta composição nesta referência.")
    if faltam:
        avisos.append(f"{faltam} insumo(s) sem preço nesta referência (não são tratados como zero).")
    if pct and pct > 0:
        avisos.append(f"{round(float(pct) * 100)}% do custo usa preços de São Paulo, porque o SINAPI não coletou preço em {ref.uf} neste mês." if ref.uf != "SP"
                      else "Parte do custo usa preços atribuídos.")
    return dict(codigo=comp.codigo, descricao=comp.descricao, unidade=mapas.unidade_prumo(comp.unidade), grupo=comp.grupo,
                referencia=dict(uf=ref.uf, data_base=ref.data_base.strftime("%Y-%m"), regime=ref.regime),
                custo=publicado, custo_calculado=None if faltam else calc.quantize(Decimal("0.01")), pct_as=pct,
                itens=itens, estrutura=estrutura, avisos=avisos)
