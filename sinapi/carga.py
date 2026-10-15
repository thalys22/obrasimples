"""Carga do SINAPI no banco (tudo ou nada). Usada pelo comando `carregar_sinapi`."""
import hashlib
from collections import Counter
from datetime import date
from decimal import Decimal

from django.db import transaction

from . import leitor, mapas
from .models import Carga, Composicao, ComposicaoItem, CustoComposicao, Insumo, PrecoInsumo, Referencia

LOTE = 5000
PROFUNDIDADE_MAX = 8
UF_FALLBACK = "SP"


class ErroCarga(Exception):
    pass


def sha256(caminho):
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def verificar_estrutura(comps, itens):
    """Itens órfãos, ciclos e profundidade. Devolve a profundidade máxima."""
    filhos = {}
    for cod, _o, tipo, alvo, *_ in itens:
        if tipo == "composicao":
            if alvo not in comps:
                raise ErroCarga(f"Composição {cod} usa a auxiliar {alvo}, que não está definida no Analítico.")
            filhos.setdefault(cod, []).append(alvo)
    prof, visitando = {}, set()

    def p(c):
        if c in prof:
            return prof[c]
        if c in visitando:
            raise ErroCarga(f"Ciclo de composições envolvendo {c}.")
        visitando.add(c)
        d = 1 + max((p(f) for f in filhos.get(c, [])), default=0)
        visitando.discard(c)
        if d > PROFUNDIDADE_MAX:
            raise ErroCarga(f"Composição {c} passa de {PROFUNDIDADE_MAX} níveis de auxiliares.")
        prof[c] = d
        return d

    return max((p(c) for c in comps), default=0)


def tolerancia(publicado):
    return max(0.02, 0.005 * publicado)


def conferir_custos(itens, preco, publicados):
    """Recalcula soma(coef x preço) recursivamente. preco: {insumo: float|None}; publicados: {composicao: float}.
    Devolve dict com contagens e lista de divergências > 5%."""
    por_comp = {}
    for cod, _o, tipo, alvo, _d, _u, coef, _s in itens:
        por_comp.setdefault(cod, []).append((tipo, alvo, float(coef or 0)))
    memo = {}

    def custo(c):
        if c in memo:
            return memo[c]
        total = 0.0
        for tipo, alvo, coef in por_comp.get(c, []):
            v = preco.get(alvo) if tipo == "insumo" else custo(alvo)
            if v is None:
                memo[c] = None
                return None
            total += coef * v
        memo[c] = total
        return total

    r = dict(dentro=0, ate5=0, acima5=0, sem_calculo=0, acima=[], sem_calculo_lista=[])
    for c, pub in publicados.items():
        calc = custo(c)
        if calc is None:
            r["sem_calculo"] += 1
            r["sem_calculo_lista"].append(c)
        elif abs(calc - pub) <= tolerancia(pub):
            r["dentro"] += 1
        elif abs(calc - pub) <= 0.05 * pub:
            r["ate5"] += 1
        else:
            r["acima5"] += 1
            r["acima"].append((c, pub, round(calc, 4)))
    return r


def _lotes(seq, n=LOTE):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def montar_insumos(precos_por_regime, itens):
    """União das abas de preço com o Analítico. Devolve (info_ins, sem_preco_nacional)."""
    info = {}
    for precos in precos_por_regime:
        for cod, d in precos.items():
            info.setdefault(cod, dict(classificacao=d.get("classificacao", ""), descricao=d.get("descricao", ""),
                                      unidade=d.get("unidade", ""), coleta=d.get("coleta", "")))
    for _c, _o, tipo, alvo, desc, un, _co, _sit in itens:
        if tipo == "insumo" and alvo not in info:
            info[alvo] = dict(classificacao="", descricao=desc, unidade=un, coleta="")
    sem_preco = {alvo for _c, _o, t, alvo, _d, _u, _co, sit in itens if t == "insumo" and sit == "SEM PREÇO"}
    return info, sem_preco


def unidades_fora_do_mapa(info_ins, comps):
    c = Counter()
    for d in info_ins.values():
        if not mapas.unidade_conhecida(d["unidade"]):
            c[d["unidade"]] += 1
    for d in comps.values():
        if not mapas.unidade_conhecida(d["unidade"]):
            c[d["unidade"]] += 1
    return dict(c)


def gravar_estrutura(comps, itens, info_ins, sem_preco_nac):
    """Insumos, composições e itens (independentes de UF e regime). Chamar dentro de transaction.atomic."""
    Insumo.objects.bulk_create(
        [Insumo(codigo=c, descricao=d["descricao"][:400], unidade=d["unidade"][:12], classificacao=d["classificacao"][:60],
                tipo=mapas.tipo_do_insumo(d["classificacao"]), sem_preco_nacional=c in sem_preco_nac) for c, d in info_ins.items()],
        batch_size=LOTE, update_conflicts=True, unique_fields=["codigo"],
        update_fields=["descricao", "unidade", "classificacao", "tipo", "sem_preco_nacional"])
    Composicao.objects.bulk_create(
        [Composicao(codigo=c, descricao=d["descricao"][:400], busca=mapas.normalizar(d["descricao"])[:400], unidade=d["unidade"][:12],
                    grupo=d["grupo"][:200], situacao_nacional=d["situacao"][:20], orcavel=not mapas.grupo_interno(d["grupo"]))
         for c, d in comps.items()],
        batch_size=LOTE, update_conflicts=True, unique_fields=["codigo"],
        update_fields=["descricao", "busca", "unidade", "grupo", "situacao_nacional", "orcavel"])
    ComposicaoItem.objects.all().delete()
    id_ins = dict(Insumo.objects.values_list("codigo", "id"))
    id_comp = dict(Composicao.objects.values_list("codigo", "id"))
    novos = [ComposicaoItem(composicao_id=id_comp[c], ordem=o, tipo_item=t, coeficiente=co or Decimal(0),
                            insumo_id=id_ins[a] if t == "insumo" else None,
                            composicao_filha_id=id_comp[a] if t == "composicao" else None)
             for c, o, t, a, _d, _u, co, _s in itens]
    for lote in _lotes(novos):
        ComposicaoItem.objects.bulk_create(lote)


def gravar_referencia(uf, regime, base, info_ins, precos, custos, itens, digest, arquivo, avisos_gerais=()):
    """Uma UF + regime: preços (com fallback para SP), custos e conferência. Levanta ErroCarga se reprovar.
    precos: {codigo: {"coleta": str, "precos": {uf: Decimal|None}}}; custos: {codigo: {"custos": {uf: (custo|None, pct)}}}.
    Chamar dentro de transaction.atomic."""
    id_ins = dict(Insumo.objects.values_list("codigo", "id"))
    id_comp = dict(Composicao.objects.values_list("codigo", "id"))
    faltam = [c for c in custos if c not in id_comp]
    if faltam:
        raise ErroCarga(f"Há {len(faltam)} composição(ões) de custo que não estão na estrutura carregada (ex.: {faltam[:3]}).")
    if not precos or UF_FALLBACK not in next(iter(precos.values()))["precos"]:
        raise ErroCarga(f"Os preços de {UF_FALLBACK} (usados como substituto) não vieram no arquivo.")
    ref, _ = Referencia.objects.get_or_create(uf=uf, data_base=base, regime=regime)
    PrecoInsumo.objects.filter(referencia=ref).delete()
    CustoComposicao.objects.filter(referencia=ref).delete()
    Carga.objects.filter(referencia=ref).delete()
    efetivo, linhas_preco, n_sp, n_local, n_nenhum = {}, [], 0, 0, 0
    for cod in info_ins:
        d = precos.get(cod)
        loc = d["precos"].get(uf) if d else None
        sp = d["precos"].get(UF_FALLBACK) if d else None
        if loc is not None:
            p, orig, n_local = loc, "local", n_local + 1
        elif sp is not None:
            p, orig, n_sp = sp, "sp", n_sp + 1
        else:
            p, orig, n_nenhum = None, "", n_nenhum + 1
        efetivo[cod] = None if p is None else float(p)
        if d is not None:
            linhas_preco.append(PrecoInsumo(referencia=ref, insumo_id=id_ins[cod], preco=p, origem_preco=orig, coleta=str(d.get("coleta", ""))[:4]))
    for lote in _lotes(linhas_preco):
        PrecoInsumo.objects.bulk_create(lote)
    linhas_custo, publicados = [], {}
    for cod, d in custos.items():
        custo, pct = d["custos"][uf]
        linhas_custo.append(CustoComposicao(referencia=ref, composicao_id=id_comp[cod], custo_publicado=custo, pct_as=pct))
        if custo is not None:
            publicados[cod] = float(custo)
    for lote in _lotes(linhas_custo):
        CustoComposicao.objects.bulk_create(lote)
    conf = conferir_custos(itens, efetivo, publicados)
    n_pub = len(publicados)
    if conf["sem_calculo"] or (n_pub and conf["acima5"] / n_pub > 0.01):
        raise ErroCarga(f"Conferência de custo reprovada para {uf} {regime}: {conf['acima5']} acima de 5% e {conf['sem_calculo']} sem custo calculável, de {n_pub}. Nada foi gravado.")
    avisos = []
    if conf["acima5"]:
        avisos.append(f"{conf['acima5']} composição(ões) acima de 5% (aceito, abaixo do limite de 1%): {conf['acima'][:10]}")
    Carga.objects.create(referencia=ref, arquivo=str(arquivo)[-300:], sha256=digest, linhas=len(linhas_preco) + len(linhas_custo),
                         avisos="\n".join(avisos + list(avisos_gerais)[:50]))
    blanks = n_sp + n_nenhum
    return dict(precos=len(linhas_preco), custos=len(linhas_custo), com_custo=n_pub, preco_local=n_local, preco_sp=n_sp, sem_preco=n_nenhum,
                pct_sem_preco_local=round(100 * blanks / max(1, len(info_ins)), 1),
                conferencia={k: conf[k] for k in ("dentro", "ate5", "acima5", "sem_calculo")}, avisos=avisos)


def carregar(arquivo, base, ufs, regimes, saida=print):
    """Lê o xlsx (openpyxl) e grava. base: date (dia 1). Devolve o relatório (dict). Levanta ErroCarga/ErroLayout sem gravar nada."""
    ufs = [u.upper() for u in ufs]
    ufs_leitura = sorted(set(ufs) | {UF_FALLBACK})
    digest = sha256(arquivo)
    rel = dict(arquivo=str(arquivo), sha256=digest, referencias={}, avisos=[])
    wv, wf = leitor.abrir(arquivo), leitor.abrir(arquivo, formulas=True)

    for regime in regimes:
        if regime not in leitor.ABAS:
            raise ErroCarga(f"Regime desconhecido: {regime}.")
        for aba in leitor.ABAS[regime]:
            ano, mes = leitor.ler_mes(wv, aba)
            if (ano, mes) != (base.year, base.month):
                raise ErroCarga(f"Aba {aba} é do mês {mes:02d}/{ano}, mas --base pede {base.month:02d}/{base.year}.")

    ja = {(r.uf, r.regime) for r in Referencia.objects.filter(data_base=base, cargas__sha256=digest)}
    pendentes = [(uf, rg) for rg in regimes for uf in ufs if (uf, rg) not in ja]
    if not pendentes:
        saida("Nada a fazer: este arquivo já foi carregado para todas as UFs e regimes pedidos.")
        rel["nada"] = True
        return rel
    estrutura_nova = not Carga.objects.filter(sha256=digest).exists()

    saida("Lendo estrutura (Analítico)…")
    comps, itens, av = leitor.ler_analitico(wv)
    rel["avisos"] += av
    rel["profundidade_max"] = verificar_estrutura(comps, itens)
    rel.update(composicoes=len(comps), itens=len(itens))

    leituras = {}
    for regime in regimes:
        if not any(rg == regime for _, rg in pendentes):
            continue
        a_ins, a_cus = leitor.ABAS[regime]
        saida(f"Lendo {a_ins} e {a_cus}…")
        precos = leitor.ler_precos(wv, a_ins, ufs_leitura)
        custos = leitor.ler_custos(wf, wv, a_cus, ufs_leitura)
        if set(custos) != set(comps):
            raise ErroCarga(f"{a_cus} e Analítico não têm as mesmas composições (só em {a_cus}: {len(set(custos) - set(comps))}; só no Analítico: {len(set(comps) - set(custos))}).")
        leituras[regime] = (precos, custos)

    info_ins, sem_preco_nac = montar_insumos([p for p, _c in leituras.values()], itens)
    rel.update(insumos=len(info_ins), unidades_fora_do_mapa=unidades_fora_do_mapa(info_ins, comps),
               insumos_sem_classificacao=sum(1 for d in info_ins.values() if not d["classificacao"]))

    with transaction.atomic():
        if estrutura_nova:
            saida("Gravando insumos e composições…")
            gravar_estrutura(comps, itens, info_ins, sem_preco_nac)
        for uf, regime in pendentes:
            precos, custos = leituras[regime]
            r = gravar_referencia(uf, regime, base, info_ins, precos, custos, itens, digest, arquivo, rel["avisos"])
            rel["referencias"][f"{uf}/{regime}"] = r
            c = r["conferencia"]
            saida(f"  {uf}/{regime}: {r['com_custo']} com custo · dentro {c['dentro']} · até 5% {c['ate5']} · acima {c['acima5']}")
    return rel
