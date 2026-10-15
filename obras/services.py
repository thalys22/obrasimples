"""
Regras de negócio do Prumo. Toda alteração de dados passa por aqui,
dentro de uma transação, sempre filtrando pela obra do usuário logado.
"""
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from .biblioteca import carregar_biblioteca
from .models import (
    ETAPAS_PADRAO, Composicao, Consumo, Contrato, Empreiteiro, Etapa, Fornecedor, Insumo, InsumoPrevisto,
    ItemComposicao, ItemNota, ItemOrcamento, Material, Medicao, NotaFiscal, Obra, Pagamento,
)

D0 = Decimal("0")
CENT = Decimal("0.01")


class RegraNegocio(Exception):
    """Erro mostrado ao usuário como está (mensagem em português)."""


# ---------------------------------------------------------------- conversões
def dec(v, campo="valor", minimo=None):
    if v is None or v == "":
        raise RegraNegocio(f"Informe {campo}.")
    s = str(v).strip()
    if "," in s and "." not in s:
        s = s.replace(",", ".")
    try:
        d = Decimal(s)
    except (InvalidOperation, ValueError):
        raise RegraNegocio(f"{campo.capitalize()} inválido.")
    if not d.is_finite():
        raise RegraNegocio(f"{campo.capitalize()} inválido.")
    if minimo is not None and d <= minimo:
        raise RegraNegocio(f"{campo.capitalize()} precisa ser maior que zero.")
    return d


def data_iso(v, campo="data", obrigatoria=True):
    if not v:
        if obrigatoria:
            raise RegraNegocio(f"Informe a {campo}.")
        return None
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        raise RegraNegocio(f"{campo.capitalize()} inválida.")


def texto(v, campo, obrigatorio=True, maximo=200):
    s = str(v or "").strip()
    if obrigatorio and not s:
        raise RegraNegocio(f"Informe {campo}.")
    return s[:maximo]


def pegar(modelo, obra, id_, nome):
    try:
        return modelo.objects.get(obra=obra, pk=int(id_))
    except (modelo.DoesNotExist, TypeError, ValueError):
        raise RegraNegocio(f"{nome} não encontrado nesta obra.")


# ---------------------------------------------------------------- obra
def obras_do_usuario(usuario):
    """Obras que o usuário pode abrir: as que ele é dono e as compartilhadas com ele."""
    return Obra.objects.filter(Q(dono=usuario) | Q(membros=usuario)).distinct().order_by("id")


def obter_obra(usuario, obra_id=None):
    """Obra ativa do usuário, entre as liberadas para ele. Nunca cria obra:
    quem cria e libera obras é o administrador. Retorna None se não houver nenhuma."""
    qs = obras_do_usuario(usuario)
    obra = qs.filter(pk=obra_id).first() if obra_id else None
    return obra or qs.first()


@transaction.atomic
def excluir_obra(obra):
    """Apaga a obra, os lançamentos e o cadastro próprio dela (na ordem que as travas internas exigem)."""
    limpar(obra)
    obra.composicoes.all().delete()
    obra.insumos.all().delete()
    obra.delete()


def pode_apagar_tudo(obra, usuario):
    return usuario.is_superuser or obra.dono_id == usuario.pk


def exigir_dono(obra, usuario):
    if not pode_apagar_tudo(obra, usuario):
        raise RegraNegocio("Só o dono da obra pode apagar todos os dados ou importar uma planilha por cima.")


def atualizar_obra(obra, dados):
    if "nome" in dados:
        obra.nome = texto(dados["nome"], "o nome da obra")
    if "cliente" in dados:
        obra.cliente = texto(dados["cliente"], "o cliente", obrigatorio=False)
    if "prazo" in dados:
        obra.prazo = data_iso(dados["prazo"], "prazo", obrigatoria=False)
    if "valorContratado" in dados:
        obra.valor_contratado = dec(dados["valorContratado"] or 0, "o valor contratado")
    obra.save()


# ---------------------------------------------------------------- etapas
def _ordem_nova(obra, nome):
    if nome in ETAPAS_PADRAO:
        return (ETAPAS_PADRAO.index(nome) + 1) * 10
    ultima = obra.etapas.order_by("-ordem").values_list("ordem", flat=True).first() or 0
    return max(ultima, len(ETAPAS_PADRAO) * 10) + 10


def etapa_por(obra, d, criar=True):
    """Etapa a partir de etapaId ou do nome. Pelo nome, cria se ainda não existir na obra
    (usado ao escolher uma etapa da lista padrão e na importação de planilha)."""
    if d.get("etapaId"):
        return pegar(Etapa, obra, d.get("etapaId"), "Etapa")
    nome = texto(d.get("etapa"), "a etapa", maximo=120)
    et = obra.etapas.filter(nome__iexact=nome).first()
    if et:
        return et
    if not criar:
        raise RegraNegocio(f'A etapa "{nome}" não existe nesta obra.')
    return Etapa.objects.create(obra=obra, nome=nome, ordem=_ordem_nova(obra, nome))


def criar_etapa(obra, d):
    nome = texto(d.get("nome"), "o nome da etapa", maximo=120)
    if obra.etapas.filter(nome__iexact=nome).exists():
        raise RegraNegocio(f'A etapa "{nome}" já existe nesta obra.')
    return Etapa.objects.create(obra=obra, nome=nome, ordem=_ordem_nova(obra, nome))


def renomear_etapa(obra, pk, d):
    et = pegar(Etapa, obra, pk, "Etapa")
    nome = texto(d.get("nome"), "o nome da etapa", maximo=120)
    if obra.etapas.filter(nome__iexact=nome).exclude(pk=et.pk).exists():
        raise RegraNegocio(f'Já existe outra etapa chamada "{nome}".')
    et.nome = nome
    et.save()


def excluir_etapa(obra, pk):
    et = pegar(Etapa, obra, pk, "Etapa")
    if et.itens.exists():
        raise RegraNegocio("Essa etapa tem serviços no orçamento. Exclua ou mova os serviços antes.")
    et.delete()


def definir_avanco(obra, etapa, percentual):
    p = max(D0, min(Decimal("100"), dec(percentual or 0, "o percentual")))
    et = etapa_por(obra, {"etapa": etapa} if not isinstance(etapa, dict) else etapa)
    et.percentual = p
    et.save()


# ---------------------------------------------------------------- catálogo (insumos e composições)
TIPOS_INSUMO = dict(Insumo.TIPOS)
_ALIAS_TIPO = {
    "material": Insumo.MATERIAL, "materiais": Insumo.MATERIAL, "mat": Insumo.MATERIAL,
    "maodeobra": Insumo.MAO_DE_OBRA, "mo": Insumo.MAO_DE_OBRA, "mdo": Insumo.MAO_DE_OBRA,
    "equipamento": Insumo.EQUIPAMENTO, "equipamentos": Insumo.EQUIPAMENTO, "eq": Insumo.EQUIPAMENTO,
    "empreitada": Insumo.EMPREITADA, "empreitadaterceiro": Insumo.EMPREITADA, "terceiro": Insumo.EMPREITADA, "servico": Insumo.EMPREITADA,
}


def _chave(v):
    import unicodedata
    s = unicodedata.normalize("NFD", str(v or "")).encode("ascii", "ignore").decode().lower()
    return "".join(ch for ch in s if ch.isalnum())


def tipo_insumo(v):
    if not v:
        return Insumo.MATERIAL
    t = _ALIAS_TIPO.get(_chave(v))
    if not t:
        raise RegraNegocio(f'Tipo de insumo "{v}" não reconhecido. Use: material, mão de obra, equipamento ou empreitada.')
    return t


def pode_editar_base(usuario):
    return bool(usuario and (usuario.is_superuser or usuario.has_perm("obras.change_insumo")))


def _escopo(obra, usuario, escopo):
    """None = base geral (só quem tem permissão); senão, a obra ativa."""
    if escopo == "base":
        if not pode_editar_base(usuario):
            raise RegraNegocio("Só o administrador altera a base geral. Cadastre na base desta obra.")
        return None
    return obra


def _pode_alterar(obj, obra, usuario, nome):
    if obj.obra_id is None:
        if not pode_editar_base(usuario):
            raise RegraNegocio(f"Esse {nome} é da base geral: só o administrador altera. "
                               f"Para mudar só nesta obra, use Duplicar para esta obra.")
    elif obj.obra_id != obra.pk:
        raise RegraNegocio(f"{nome.capitalize()} não encontrado nesta obra.")


def insumos_visiveis(obra):
    return Insumo.objects.filter(Q(obra__isnull=True) | Q(obra=obra))


def composicoes_visiveis(obra):
    return Composicao.objects.filter(Q(obra__isnull=True) | Q(obra=obra))


def pegar_visivel(qs, id_, nome):
    try:
        return qs.get(pk=int(id_))
    except (qs.model.DoesNotExist, TypeError, ValueError):
        raise RegraNegocio(f"{nome} não encontrado.")


def por_codigo(qs, codigo):
    """Pelo código: o da obra tem preferência sobre o da base geral."""
    codigo = str(codigo or "").strip()
    return qs.filter(codigo__iexact=codigo).order_by("obra_id").last() if codigo else None


def proximo_codigo(modelo, escopo_obra, prefixo):
    qs = modelo.objects.filter(obra=escopo_obra, codigo__startswith=prefixo)
    maior = 0
    for c in qs.values_list("codigo", flat=True):
        resto = c[len(prefixo):]
        if resto.isdigit():
            maior = max(maior, int(resto))
    return f"{prefixo}{maior + 1:04d}"


def _codigo_livre(modelo, escopo_obra, codigo, exceto=None):
    qs = modelo.objects.filter(obra=escopo_obra, codigo__iexact=codigo)
    if exceto:
        qs = qs.exclude(pk=exceto.pk)
    if qs.exists():
        onde = "na base geral" if escopo_obra is None else "nesta obra"
        raise RegraNegocio(f'O código "{codigo}" já está em uso {onde}.')


@transaction.atomic
def salvar_insumo(obra, usuario, d, pk=None):
    if pk:
        ins = pegar_visivel(insumos_visiveis(obra), pk, "Insumo")
        _pode_alterar(ins, obra, usuario, "insumo")
    else:
        ins = Insumo(obra=_escopo(obra, usuario, d.get("escopo")))
    prefixo = "I-" if ins.obra_id is None else "IP-"
    codigo = texto(d.get("codigo"), "o código", obrigatorio=False, maximo=30) or (ins.codigo or proximo_codigo(Insumo, ins.obra, prefixo))
    _codigo_livre(Insumo, ins.obra, codigo, exceto=ins if ins.pk else None)
    ins.codigo = codigo
    ins.descricao = texto(d.get("descricao"), "a descrição do insumo")
    ins.unidade = texto(d.get("unidade"), "a unidade", maximo=20)
    ins.tipo = tipo_insumo(d.get("tipo"))
    ins.preco = dec(d.get("preco") if d.get("preco") not in (None, "") else 0, "o preço")
    if ins.preco < 0:
        raise RegraNegocio("O preço não pode ser negativo.")
    ins.save()
    return ins


def excluir_insumo(obra, usuario, pk):
    ins = pegar_visivel(insumos_visiveis(obra), pk, "Insumo")
    _pode_alterar(ins, obra, usuario, "insumo")
    usos = []
    if ins.usos.exists():
        usos.append(f"{ins.usos.values('composicao').distinct().count()} composição(ões)")
    if ins.previstos.exists():
        usos.append("serviços do orçamento")
    if ins.estoques.exists():
        usos.append("estoque")
    if usos:
        raise RegraNegocio(f"Esse insumo está em uso ({', '.join(usos)}) e não pode ser excluído.")
    ins.delete()


def _itens_composicao(comp, obra, itens):
    if not itens:
        raise RegraNegocio("Adicione pelo menos um insumo à composição.")
    vis = insumos_visiveis(obra)
    vistos, novos = set(), []
    for it in itens:
        ins = pegar_visivel(vis, it.get("insumoId"), "Insumo")
        if comp.obra_id is None and ins.obra_id is not None:
            raise RegraNegocio(f"{ins.codigo} é um insumo só desta obra; uma composição da base geral só pode usar insumos da base geral.")
        if ins.pk in vistos:
            raise RegraNegocio(f"O insumo {ins.codigo} aparece duas vezes na composição.")
        vistos.add(ins.pk)
        novos.append(ItemComposicao(composicao=comp, insumo=ins, coeficiente=dec(it.get("coef"), f"o coeficiente de {ins.codigo}", minimo=D0)))
    comp.itens.all().delete()
    ItemComposicao.objects.bulk_create(novos)


@transaction.atomic
def salvar_composicao(obra, usuario, d, pk=None):
    if pk:
        comp = pegar_visivel(composicoes_visiveis(obra), pk, "Composição")
        _pode_alterar(comp, obra, usuario, "composição")
    else:
        comp = Composicao(obra=_escopo(obra, usuario, d.get("escopo")))
    prefixo = "C-" if comp.obra_id is None else "CP-"
    codigo = texto(d.get("codigo"), "o código", obrigatorio=False, maximo=30) or (comp.codigo or proximo_codigo(Composicao, comp.obra, prefixo))
    _codigo_livre(Composicao, comp.obra, codigo, exceto=comp if comp.pk else None)
    comp.codigo = codigo
    comp.descricao = texto(d.get("descricao"), "a descrição do serviço")
    comp.unidade = texto(d.get("unidade"), "a unidade", maximo=20)
    comp.observacao = texto(d.get("observacao"), "a observação", obrigatorio=False, maximo=300)
    comp.save()
    _itens_composicao(comp, obra, d.get("itens") or [])
    return comp


def excluir_composicao(obra, usuario, pk):
    """Pode excluir mesmo se já usada: o orçamento guarda uma cópia dos insumos."""
    comp = pegar_visivel(composicoes_visiveis(obra), pk, "Composição")
    _pode_alterar(comp, obra, usuario, "composição")
    comp.delete()


@transaction.atomic
def duplicar_composicao(obra, pk):
    """Copia uma composição (normalmente da base geral) para a base desta obra, para ajustar."""
    orig = pegar_visivel(composicoes_visiveis(obra), pk, "Composição")
    nova = Composicao.objects.create(obra=obra, codigo=proximo_codigo(Composicao, obra, "CP-"), descricao=orig.descricao[:200],
                                     unidade=orig.unidade, observacao=f"Cópia de {orig.codigo}. {orig.observacao}"[:300])
    ItemComposicao.objects.bulk_create([ItemComposicao(composicao=nova, insumo=i.insumo, coeficiente=i.coeficiente) for i in orig.itens.all()])
    return nova


def _linhas(linhas, limite=5000):
    if not isinstance(linhas, list) or not linhas:
        raise RegraNegocio("A planilha está vazia.")
    if len(linhas) > limite:
        raise RegraNegocio(f"A planilha tem {len(linhas)} linhas; o máximo por importação é {limite}.")
    return [l for l in linhas if isinstance(l, dict) and any(str(v).strip() for v in l.values())]


def _erro_linha(n, e):
    return RegraNegocio(f"Linha {n}: {e}")


@transaction.atomic
def importar_insumos(obra, usuario, escopo, linhas):
    """Cria ou atualiza insumos pelo código. Tudo ou nada: se uma linha tem erro, nada é gravado."""
    alvo = _escopo(obra, usuario, escopo)
    criados = atualizados = 0
    for n, l in enumerate(_linhas(linhas), start=2):
        try:
            codigo = texto(l.get("codigo"), "o código", maximo=30)
            ins = Insumo.objects.filter(obra=alvo, codigo__iexact=codigo).first()
            dados = dict(codigo=codigo, descricao=l.get("descricao"), unidade=l.get("unidade"), tipo=l.get("tipo"),
                         preco=l.get("preco"), escopo="base" if alvo is None else "obra")
            salvar_insumo(obra, usuario, dados, pk=ins.pk if ins else None)
        except RegraNegocio as e:
            raise _erro_linha(n, e)
        criados += ins is None
        atualizados += ins is not None
    return {"criados": criados, "atualizados": atualizados}


@transaction.atomic
def importar_composicoes(obra, usuario, escopo, linhas):
    """Uma linha por insumo da composição. Linhas com o mesmo código de composição formam uma composição.
    Composição que já existe (pelo código) tem os insumos substituídos pelos da planilha."""
    alvo = _escopo(obra, usuario, escopo)
    vis = Insumo.objects.filter(obra__isnull=True) if alvo is None else insumos_visiveis(obra)
    grupos = {}
    for n, l in enumerate(_linhas(linhas), start=2):
        try:
            cc = texto(l.get("codigocomposicao"), "o código da composição", maximo=30)
            g = grupos.setdefault(cc.upper(), {"codigo": cc, "descricao": "", "unidade": "", "itens": [], "linha": n})
            g["descricao"] = g["descricao"] or str(l.get("descricaocomposicao") or "").strip()
            g["unidade"] = g["unidade"] or str(l.get("unidadecomposicao") or "").strip()
            ci = texto(l.get("codigoinsumo"), "o código do insumo", maximo=30)
            ins = por_codigo(vis, ci)
            if not ins:
                raise RegraNegocio(f'o insumo "{ci}" não está cadastrado{" na base geral" if alvo is None else ""}. Importe ou cadastre os insumos antes.')
            g["itens"].append({"insumoId": ins.pk, "coef": l.get("coeficiente")})
        except RegraNegocio as e:
            raise _erro_linha(n, e)
    criadas = atualizadas = 0
    for g in grupos.values():
        comp = Composicao.objects.filter(obra=alvo, codigo__iexact=g["codigo"]).first()
        dados = {"codigo": g["codigo"], "descricao": g["descricao"] or (comp.descricao if comp else ""),
                 "unidade": g["unidade"] or (comp.unidade if comp else ""), "observacao": comp.observacao if comp else "",
                 "itens": g["itens"], "escopo": "base" if alvo is None else "obra"}
        try:
            salvar_composicao(obra, usuario, dados, pk=comp.pk if comp else None)
        except RegraNegocio as e:
            raise RegraNegocio(f"Composição {g['codigo']} (a partir da linha {g['linha']}): {e}")
        criadas += comp is None
        atualizadas += comp is not None
    return {"criadas": criadas, "atualizadas": atualizadas}


def garantir_biblioteca():
    return carregar_biblioteca(Insumo, Composicao, ItemComposicao)


# ---------------------------------------------------------------- orçamento
def _congelar(item, comp):
    """Copia os insumos da composição para o serviço, com os preços de hoje."""
    itens = list(comp.itens.select_related("insumo"))
    if not itens:
        raise RegraNegocio(f"A composição {comp.codigo} não tem insumos.")
    item.insumos.all().delete()
    InsumoPrevisto.objects.bulk_create([InsumoPrevisto(item=item, insumo=i.insumo, coeficiente=i.coeficiente, preco_unitario=i.insumo.preco) for i in itens])
    item.preco_unitario = sum((i.coeficiente * i.insumo.preco for i in itens), D0).quantize(Decimal("0.0001"), ROUND_HALF_UP)
    item.codigo = comp.codigo


@transaction.atomic
def adicionar_item(obra, d):
    etapa = etapa_por(obra, d)
    qtd = dec(d.get("qtd"), "a quantidade", minimo=D0)
    comp = None
    if d.get("composicaoId"):
        comp = pegar_visivel(composicoes_visiveis(obra), d.get("composicaoId"), "Composição")
    elif d.get("composicaoCodigo"):
        comp = por_codigo(composicoes_visiveis(obra), d.get("composicaoCodigo"))
        if not comp:
            raise RegraNegocio(f'A composição "{d.get("composicaoCodigo")}" não está cadastrada.')
    obs = texto(d.get("observacao", d.get("insumo")), "a observação", obrigatorio=False)
    if comp:
        item = ItemOrcamento(obra=obra, etapa=etapa, composicao=comp, servico=texto(d.get("servico") or comp.descricao, "o serviço"),
                             observacao=obs, unidade=comp.unidade, quantidade=qtd, preco_unitario=D0)
        item.save()
        _congelar(item, comp)
        item.save()
    else:
        item = ItemOrcamento.objects.create(
            obra=obra, etapa=etapa, servico=texto(d.get("servico"), "o serviço"), observacao=obs,
            unidade=texto(d.get("unidade"), "a unidade", maximo=20),
            preco_unitario=dec(d.get("precoUnit"), "o preço unitário", minimo=D0), quantidade=qtd,
        )
    return item


@transaction.atomic
def atualizar_item(obra, pk, d):
    item = pegar(ItemOrcamento, obra, pk, "Serviço")
    if "etapaId" in d or "etapa" in d:
        item.etapa = etapa_por(obra, d)
    if "servico" in d:
        item.servico = texto(d.get("servico"), "o serviço")
    if "observacao" in d:
        item.observacao = texto(d.get("observacao"), "a observação", obrigatorio=False)
    if "qtd" in d:
        item.quantidade = dec(d.get("qtd"), "a quantidade", minimo=D0)
    tem_insumos = item.insumos.exists()
    if "precoUnit" in d and not tem_insumos:
        item.preco_unitario = dec(d.get("precoUnit"), "o preço unitário", minimo=D0)
    if "unidade" in d and not tem_insumos:
        item.unidade = texto(d.get("unidade"), "a unidade", maximo=20)
    item.save()
    return item


@transaction.atomic
def atualizar_pela_composicao(obra, pk):
    """Refaz os insumos previstos e o preço do serviço com a composição e os preços atuais."""
    item = pegar(ItemOrcamento, obra, pk, "Serviço")
    comp = item.composicao
    if not comp:
        raise RegraNegocio("Esse serviço não está ligado a uma composição (ou a composição foi excluída).")
    _congelar(item, comp)
    item.unidade = comp.unidade
    item.save()
    return item


@transaction.atomic
def importar_orcamento(obra, linhas):
    """Acrescenta serviços ao orçamento. Com código de composição, o preço vem dela;
    sem código, é serviço por verba e precisa de serviço, unidade e preço."""
    n_itens = 0
    for n, l in enumerate(_linhas(linhas), start=2):
        try:
            adicionar_item(obra, {"etapa": l.get("etapa"), "composicaoCodigo": str(l.get("codigocomposicao") or "").strip() or None,
                                  "servico": str(l.get("servico") or "").strip(), "unidade": l.get("unidade"),
                                  "qtd": l.get("quantidade"), "precoUnit": l.get("precounitario"), "observacao": l.get("observacao")})
        except RegraNegocio as e:
            raise _erro_linha(n, e)
        n_itens += 1
    return {"servicos": n_itens}


def item_tem_vinculo(item):
    return item.consumos.exists() or item.compras.exists() or item.contratos.exists() or item.pagamentos.exists()


@transaction.atomic
def excluir_item(obra, item_id):
    item = pegar(ItemOrcamento, obra, item_id, "Serviço")
    if item_tem_vinculo(item):
        raise RegraNegocio("Esse serviço já tem gastos ligados a ele e não pode ser excluído.")
    item.delete()


# ---------------------------------------------------------------- cadastros
def adicionar_fornecedor(obra, d):
    return Fornecedor.objects.create(obra=obra, nome=texto(d.get("nome"), "o nome do fornecedor"), contato=texto(d.get("contato"), "o contato", obrigatorio=False))


def material_do_insumo(obra, insumo):
    """O estoque da obra para um insumo do cadastro. Nasce sozinho na primeira nota que o usa:
    não existe mais entrada manual no estoque."""
    mat = Material.objects.select_for_update().filter(obra=obra, insumo=insumo).first()
    if mat is None:
        mat = Material.objects.create(obra=obra, insumo=insumo, nome=insumo.descricao[:200], unidade=insumo.unidade)
    return mat


def adicionar_empreiteiro(obra, d):
    return Empreiteiro.objects.create(
        obra=obra, nome=texto(d.get("nome"), "o nome do empreiteiro"),
        contato=texto(d.get("contato"), "o contato", obrigatorio=False),
        especialidade=texto(d.get("especialidade"), "a especialidade", obrigatorio=False),
    )


# ---------------------------------------------------------------- estoque
@transaction.atomic
def lancar_nf(obra, d):
    """Lança um documento de entrada (nota fiscal, recibo, fatura...). É a única forma de o saldo
    de um material subir. Cada item aponta para um insumo do cadastro e, se quiser, para o serviço
    do orçamento a que se destina. Devolve a nota; os avisos ficam em `nota.avisos`."""
    numero = texto(d.get("numero"), "o número do documento", maximo=60)
    tipo = d.get("tipo") or "nota_fiscal"
    if tipo not in dict(NotaFiscal.TIPOS):
        raise RegraNegocio("Tipo de documento inválido.")
    fornecedor = pegar(Fornecedor, obra, d.get("fornecedorId"), "Fornecedor")
    venc = data_iso(d.get("data"), "data de vencimento")
    itens = d.get("itens") or []
    if not itens:
        raise RegraNegocio("Adicione pelo menos um item ao documento.")
    nota = NotaFiscal.objects.create(obra=obra, fornecedor=fornecedor, numero=numero, data=venc, tipo=tipo)
    total, avisos = D0, []
    visiveis = insumos_visiveis(obra)
    for n, it in enumerate(itens, start=1):
        if it.get("insumoId"):
            ins = pegar_visivel(visiveis, it.get("insumoId"), "Insumo")
            mat = material_do_insumo(obra, ins)
        elif it.get("materialId"):  # material que já existia (dados antigos e importação de planilha)
            mat = Material.objects.select_for_update().get(pk=pegar(Material, obra, it.get("materialId"), "Material").pk)
        else:
            raise RegraNegocio(f"Item {n}: escolha o insumo.")
        mat = Material.objects.select_for_update().get(pk=mat.pk)
        item = pegar(ItemOrcamento, obra, it.get("orcamentoItemId"), "Serviço") if it.get("orcamentoItemId") else None
        qtd = dec(it.get("qtd"), "a quantidade", minimo=D0)
        vu = dec(it.get("valorUnit"), "o valor unitário", minimo=D0)
        entrada = qtd * vu
        novo_saldo = mat.saldo + qtd
        mat.custo_medio = ((mat.saldo * mat.custo_medio + entrada) / novo_saldo).quantize(Decimal("0.000001"), ROUND_HALF_UP)
        mat.saldo = novo_saldo
        mat.save()
        ItemNota.objects.create(nota=nota, material=mat, item=item, quantidade=qtd, valor_unitario=vu)
        total += entrada
        if item and mat.insumo_id and not item.insumos.filter(insumo_id=mat.insumo_id).exists():
            avisos.append(f"{mat.nome} não está previsto no serviço \"{item.servico}\".")
    rotulo = "NF" if tipo == "nota_fiscal" else dict(NotaFiscal.TIPOS)[tipo]
    origem = numero if numero.lower().startswith(rotulo.lower().split()[0]) else f"{rotulo} {numero}"
    Pagamento.objects.create(obra=obra, tipo=Pagamento.MATERIAL, origem=origem, valor=total.quantize(CENT, ROUND_HALF_UP), data_programada=venc, nota=nota)
    nota.avisos = avisos
    return nota


@transaction.atomic
def registrar_consumo(obra, d, usuario=None):
    """Baixa de estoque. Uso em serviço: exige o serviço e vira gasto dele, a custo médio.
    Perda, quebra, ajuste e devolução: sem serviço, exigem uma descrição e NÃO entram no gasto
    de nenhum serviço. O saldo só diminui aqui; para aumentar, só com um documento de entrada."""
    tipo = d.get("tipo") or Consumo.SERVICO
    if tipo not in dict(Consumo.TIPOS):
        raise RegraNegocio("Tipo de baixa inválido.")
    item = None
    obs = texto(d.get("observacao"), "o motivo da baixa", obrigatorio=tipo != Consumo.SERVICO)
    if tipo == Consumo.SERVICO:
        item = pegar(ItemOrcamento, obra, d.get("orcamentoItemId"), "Serviço")
    mat = Material.objects.select_for_update().get(pk=pegar(Material, obra, d.get("materialId"), "Material").pk)
    qtd = dec(d.get("qtd"), "a quantidade", minimo=D0)
    dia = data_iso(d.get("data"))
    if mat.saldo <= 0:
        raise RegraNegocio(f"{mat.nome} está sem saldo no estoque. O saldo só entra por nota fiscal ou outro documento de entrada.")
    if qtd > mat.saldo and not d.get("aceitarParcial"):
        raise RegraNegocio(f"O estoque tem só {mat.saldo.normalize():f} {mat.unidade} de {mat.nome}.")
    usada = min(qtd, mat.saldo)
    valor = (usada * mat.custo_medio).quantize(CENT, ROUND_HALF_UP)
    mat.saldo -= usada
    mat.save()
    return Consumo.objects.create(obra=obra, item=item, tipo=tipo, observacao=obs, criado_por=usuario if getattr(usuario, "pk", None) else None,
                                  material=mat, quantidade=usada, quantidade_solicitada=qtd, valor=valor, data=dia)


# ---------------------------------------------------------------- contratos e medições
def criar_contrato(obra, d):
    return Contrato.objects.create(
        obra=obra,
        empreiteiro=pegar(Empreiteiro, obra, d.get("empreiteiroId"), "Empreiteiro"),
        item=pegar(ItemOrcamento, obra, d.get("orcamentoItemId"), "Serviço"),
        valor_contratado=dec(d.get("valorContratado"), "o valor do contrato", minimo=D0),
        forma_pagamento=texto(d.get("formaPagamento") or "A combinar", "a forma de pagamento"),
    )


@transaction.atomic
def registrar_medicao(obra, d):
    contrato = Contrato.objects.select_for_update().get(pk=pegar(Contrato, obra, d.get("contratoId"), "Contrato").pk)
    pct = dec(d.get("percentual"), "o percentual", minimo=D0)
    ja = contrato.medicoes.aggregate(s=Sum("percentual"))["s"] or D0
    if ja + pct > Decimal("100"):
        raise RegraNegocio(f"Esse contrato já tem {ja.normalize():f}% medido. O máximo que dá para medir agora é {(Decimal('100') - ja).normalize():f}%.")
    valor = (contrato.valor_contratado * pct / Decimal("100")).quantize(CENT, ROUND_HALF_UP)
    return Medicao.objects.create(obra=obra, contrato=contrato, data=data_iso(d.get("data")), percentual=pct, valor=valor)


@transaction.atomic
def aprovar_medicao(obra, medicao_id, usuario=None):
    med = Medicao.objects.select_for_update().get(pk=pegar(Medicao, obra, medicao_id, "Medição").pk)
    if med.status == Medicao.APROVADA:
        raise RegraNegocio("Essa medição já foi aprovada.")
    med.status = Medicao.APROVADA
    med.aprovada_por = usuario
    med.aprovada_em = timezone.now()
    med.save()
    return Pagamento.objects.create(
        obra=obra, tipo=Pagamento.MAO_DE_OBRA, origem=f"Medição #{med.pk}", item=med.contrato.item,
        valor=med.valor, data_programada=med.data, medicao=med,
    )


def excluir_medicao(obra, medicao_id):
    med = pegar(Medicao, obra, medicao_id, "Medição")
    if med.status != Medicao.PENDENTE:
        raise RegraNegocio("Medição aprovada não pode ser excluída.")
    med.delete()


# ---------------------------------------------------------------- financeiro
def pagamento_avulso(obra, d):
    item_id = d.get("orcamentoItemId")
    return Pagamento.objects.create(
        obra=obra, tipo=Pagamento.AVULSO, origem=texto(d.get("descricao"), "a descrição"),
        item=pegar(ItemOrcamento, obra, item_id, "Serviço") if item_id else None,
        valor=dec(d.get("valor"), "o valor", minimo=D0).quantize(CENT, ROUND_HALF_UP),
        data_programada=data_iso(d.get("data"), "data de vencimento"),
    )


def marcar_pago(obra, pagamento_id, dia=None):
    p = pegar(Pagamento, obra, pagamento_id, "Pagamento")
    if p.status == Pagamento.PAGO:
        raise RegraNegocio("Esse pagamento já está marcado como pago.")
    p.status = Pagamento.PAGO
    p.data_pagamento = dia or timezone.localdate()
    p.save()


def excluir_pagamento(obra, pagamento_id):
    p = pegar(Pagamento, obra, pagamento_id, "Pagamento")
    if p.tipo != Pagamento.AVULSO or p.status != Pagamento.PROGRAMADO:
        raise RegraNegocio("Só pagamentos avulsos ainda não pagos podem ser excluídos.")
    p.delete()


# ---------------------------------------------------------------- recomeçar / importar
def limpar(obra):
    obra.pagamentos.all().delete()
    obra.medicoes.all().delete()
    obra.contratos.all().delete()
    obra.consumos.all().delete()
    obra.notas.all().delete()
    obra.materiais.all().delete()
    obra.fornecedores.all().delete()
    obra.empreiteiros.all().delete()
    obra.orcamento.all().delete()
    obra.etapas.all().delete()


@transaction.atomic
def recomecar(obra, tipo):
    limpar(obra)
    if tipo == "exemplo":
        carregar_exemplo(obra)
    else:
        obra.nome, obra.cliente, obra.prazo, obra.valor_contratado, obra.exemplo = "Minha obra", "", None, D0, False
        obra.save()


@transaction.atomic
def substituir(obra, e):
    """Substitui todos os dados da obra pelo estado enviado (usado na importação de planilha).
    IDs da planilha são mapeados para IDs novos. Lançamentos que apontam para algo que não
    existe mais são descartados (consumos, contratos, medições) ou viram despesa geral (pagamentos)."""
    limpar(obra)
    o = e.get("obra") or {}
    obra.nome = texto(o.get("nome") or "Minha obra", "o nome da obra")
    obra.cliente = texto(o.get("cliente"), "o cliente", obrigatorio=False)
    obra.prazo = data_iso(o.get("prazo"), obrigatoria=False) if o.get("prazo") else None
    obra.valor_contratado = dec(o.get("valorContratado") or 0, "o valor contratado")
    obra.exemplo = False
    obra.save()

    m_item, m_forn, m_mat, m_emp, m_ctr, m_med, m_nf = {}, {}, {}, {}, {}, {}, {}
    num = lambda v: dec(v if v not in (None, "") else 0, "valor")
    for et, pct in (e.get("etapaAvanco") or {}).items():
        if str(et).strip():
            etapa_por(obra, {"etapa": str(et)[:120]})
            obra.etapas.filter(nome__iexact=str(et)[:120].strip()).update(percentual=max(D0, min(Decimal(100), num(pct))))
    comps = composicoes_visiveis(obra)
    for it in e.get("orcamento") or []:
        if not str(it.get("etapa") or "").strip() or not str(it.get("servico") or "").strip():
            continue
        novo = ItemOrcamento.objects.create(obra=obra, etapa=etapa_por(obra, {"etapa": str(it["etapa"])[:120]}), servico=str(it["servico"])[:200],
                                            observacao=str(it.get("observacao") or it.get("insumo") or "")[:200],
                                            unidade=str(it.get("unidade") or "")[:20], quantidade=num(it.get("qtd")), preco_unitario=num(it.get("precoUnit")))
        comp = por_codigo(comps, it.get("codigo"))
        if comp and comp.itens.exists():
            # Restaura o vínculo com a composição, mas mantém o preço que estava no arquivo
            preco = novo.preco_unitario
            _congelar(novo, comp)
            novo.composicao, novo.unidade = comp, comp.unidade
            novo.preco_unitario = preco or novo.preco_unitario
            novo.save()
        m_item[str(it.get("id"))] = novo
    for f in e.get("fornecedores") or []:
        m_forn[str(f.get("id"))] = Fornecedor.objects.create(obra=obra, nome=str(f.get("nome") or "Fornecedor")[:200], contato=str(f.get("contato") or "")[:200])
    for m in e.get("materiais") or []:
        ins = por_codigo(insumos_visiveis(obra), m.get("codigoInsumo"))
        if ins and obra.materiais.filter(insumo=ins).exists():
            ins = None
        m_mat[str(m.get("id"))] = Material.objects.create(obra=obra, insumo=ins, nome=str(m.get("nome") or "Material")[:200], unidade=str(m.get("unidade") or "")[:20],
                                                          saldo=num(m.get("saldo")), custo_medio=num(m.get("custoMedio")))
    for nf in e.get("notasFiscais") or []:
        forn = m_forn.get(str(nf.get("fornecedorId")))
        if not forn:
            continue
        nota = NotaFiscal.objects.create(obra=obra, fornecedor=forn, numero=str(nf.get("numero") or "")[:60], data=data_iso(nf.get("data")) or timezone.localdate(),
                                         tipo=nf.get("tipo") if nf.get("tipo") in dict(NotaFiscal.TIPOS) else "nota_fiscal")
        for it in nf.get("itens") or []:
            mat = m_mat.get(str(it.get("materialId")))
            if mat:
                ItemNota.objects.create(nota=nota, material=mat, item=m_item.get(str(it.get("orcamentoItemId"))) if it.get("orcamentoItemId") else None,
                                        quantidade=num(it.get("qtd")), valor_unitario=num(it.get("valorUnit")))
        m_nf[str(nf.get("id"))] = nota
    for p in e.get("pedidos") or []:
        item, mat = m_item.get(str(p.get("orcamentoItemId"))), m_mat.get(str(p.get("materialId")))
        tipo = p.get("tipo") if p.get("tipo") in dict(Consumo.TIPOS) else Consumo.SERVICO
        if mat and (item if tipo == Consumo.SERVICO else True):
            Consumo.objects.create(obra=obra, item=item if tipo == Consumo.SERVICO else None, tipo=tipo, observacao=str(p.get("observacao") or "")[:200],
                                   material=mat, quantidade=num(p.get("qtd")), quantidade_solicitada=num(p.get("qtdSolicitada") or p.get("qtd")),
                                   valor=num(p.get("valor")).quantize(CENT), data=data_iso(p.get("data")))
    for x in e.get("empreiteiros") or []:
        m_emp[str(x.get("id"))] = Empreiteiro.objects.create(obra=obra, nome=str(x.get("nome") or "Empreiteiro")[:200], contato=str(x.get("contato") or "")[:200],
                                                             especialidade=str(x.get("especialidade") or "")[:200])
    for c in e.get("contratos") or []:
        emp, item = m_emp.get(str(c.get("empreiteiroId"))), m_item.get(str(c.get("orcamentoItemId")))
        if emp and item:
            m_ctr[str(c.get("id"))] = Contrato.objects.create(obra=obra, empreiteiro=emp, item=item, valor_contratado=num(c.get("valorContratado")),
                                                              forma_pagamento=str(c.get("formaPagamento") or "")[:200])
    for m in e.get("medicoes") or []:
        ctr = m_ctr.get(str(m.get("contratoId")))
        if ctr:
            m_med[str(m.get("id"))] = Medicao.objects.create(obra=obra, contrato=ctr, data=data_iso(m.get("data")), percentual=num(m.get("percentual")),
                                                             valor=num(m.get("valor")).quantize(CENT), status=Medicao.APROVADA if m.get("status") == "aprovada" else Medicao.PENDENTE)
    for p in e.get("pagamentos") or []:
        med = m_med.get(str(p.get("medicaoId"))) if p.get("medicaoId") else None
        if med and hasattr(med, "pagamento"):
            med = None
        Pagamento.objects.create(
            obra=obra, tipo=p.get("tipo") if p.get("tipo") in (Pagamento.MATERIAL, Pagamento.MAO_DE_OBRA, Pagamento.AVULSO) else Pagamento.AVULSO,
            origem=str(p.get("origem") or "")[:200], item=m_item.get(str(p.get("orcamentoItemId"))) if p.get("orcamentoItemId") else None,
            valor=num(p.get("valor")).quantize(CENT), data_programada=data_iso(p.get("dataProgramada")) or timezone.localdate(),
            data_pagamento=data_iso(p.get("dataPagamento"), obrigatoria=False) if p.get("dataPagamento") else None,
            status=Pagamento.PAGO if p.get("status") == "pago" else Pagamento.PROGRAMADO, medicao=med,
        )


# ---------------------------------------------------------------- dados de exemplo
def carregar_exemplo(obra):
    garantir_biblioteca()
    obra.nome, obra.cliente, obra.prazo = "Residencial Bela Vista", "Construtora Horizonte Ltda.", date(2027, 3, 15)
    obra.valor_contratado, obra.exemplo = Decimal("315000"), True
    obra.save()
    base = {c.codigo: c for c in Composicao.objects.filter(obra=None)}

    def item(etapa, cod, qtd, servico=None, unidade=None, preco=None):
        if cod in base:
            return adicionar_item(obra, dict(etapa=etapa, composicaoId=base[cod].pk, qtd=qtd))
        return adicionar_item(obra, dict(etapa=etapa, servico=servico, unidade=unidade, qtd=qtd, precoUnit=preco))

    escav = item("Fundação", "C-0002", 40, "Escavação manual de vala", "m³", 60)
    armacao = item("Fundação", "C-0006", 2000, "Armação com aço CA-50", "kg", 12)
    concreto = item("Fundação", "C-0005", 60, "Concreto usinado", "m³", 620)
    alvenaria = item("Alvenaria", "C-0009", 480, "Alvenaria estrutural", "m²", 145)
    item("Estrutura", None, 210, "Laje pré-moldada (empreitada fechada)", "m²", 210)
    eletrica = item("Instalações elétricas", "C-0019", 150, "Ponto elétrico", "ponto", 95)
    item("Instalações hidrossanitárias", "C-0020", 90, "Ponto de água fria", "ponto", 110)
    item("Pisos", "C-0013", 340, "Piso porcelanato", "m²", 78)
    item("Pintura", "C-0016", 520, "Pintura acrílica", "m²", 34)
    for et, pct in {"Fundação": 100, "Alvenaria": 65, "Estrutura": 40, "Instalações elétricas": 30}.items():
        definir_avanco(obra, et, pct)
    f = [adicionar_fornecedor(obra, dict(nome=n, contato=c)) for n, c in [
        ("Cimento Forte Materiais", "(79) 3211-4400"), ("Ferragens União", "(79) 3211-8899"), ("Cerâmica Costa do Sol", "(79) 3025-1122")]]
    ins = {i.codigo: i for i in Insumo.objects.filter(obra=None)}
    e = [adicionar_empreiteiro(obra, dict(nome=n, contato=c, especialidade=s)) for n, c, s in [
        ("Equipe Silva Estrutura", "(79) 99911-2233", "Estrutura/Alvenaria"), ("Elétrica Santos", "(79) 99822-1010", "Instalações elétricas")]]
    nf1 = lancar_nf(obra, dict(fornecedorId=f[0].pk, numero="NF-4521", data="2026-06-02", itens=[
        dict(insumoId=ins["I-0101"].pk, orcamentoItemId=alvenaria.pk, qtd=100, valorUnit="33.9"),
        dict(insumoId=ins["I-0107"].pk, orcamentoItemId=armacao.pk, qtd=2200, valorUnit="7.2")]))
    lancar_nf(obra, dict(fornecedorId=f[1].pk, numero="NF-1187", data="2026-06-10", itens=[
        dict(insumoId=ins["I-0106"].pk, orcamentoItemId=alvenaria.pk, qtd=6500, valorUnit="4.1")]))
    cimento, aco, bloco = (obra.materiais.get(insumo=ins[c]) for c in ("I-0101", "I-0107", "I-0106"))
    registrar_consumo(obra, dict(orcamentoItemId=armacao.pk, materialId=aco.pk, qtd=1400, data="2026-06-12"))
    registrar_consumo(obra, dict(orcamentoItemId=alvenaria.pk, materialId=bloco.pk, qtd=4200, data="2026-06-20"))
    registrar_consumo(obra, dict(orcamentoItemId=alvenaria.pk, materialId=cimento.pk, qtd=40, data="2026-06-20"))
    registrar_consumo(obra, dict(tipo="quebra", observacao="Blocos quebrados no descarregamento", materialId=bloco.pk, qtd=120, data="2026-06-21"))
    c1 = criar_contrato(obra, dict(empreiteiroId=e[0].pk, orcamentoItemId=alvenaria.pk, valorContratado=26000, formaPagamento="Por medição mensal"))
    c2 = criar_contrato(obra, dict(empreiteiroId=e[1].pk, orcamentoItemId=eletrica.pk, valorContratado=12500, formaPagamento="Por medição mensal"))
    aprovar_medicao(obra, registrar_medicao(obra, dict(contratoId=c1.pk, data="2026-06-25", percentual=40)).pk)
    registrar_medicao(obra, dict(contratoId=c2.pk, data="2026-07-05", percentual=20))
    marcar_pago(obra, nf1.pagamento.pk, date(2026, 7, 2))
    pagamento_avulso(obra, dict(descricao="Aluguel de retroescavadeira", orcamentoItemId=escav.pk, valor=1800, data="2026-06-04"))
    pagamento_avulso(obra, dict(descricao="Concreto usinado (1ª concretagem)", orcamentoItemId=concreto.pk, valor=16200, data="2026-06-18"))


# ---------------------------------------------------------------- leitura (formato que o app usa)
def _usuario(usuario):
    return {"nome": usuario.get_full_name() or usuario.username, "login": usuario.username,
            "admin": usuario.is_staff, "superusuario": usuario.is_superuser}


def catalogo(obra, usuario):
    """Insumos e composições que esta obra enxerga (base geral + os próprios)."""
    f = float
    filtro = Q(obra__isnull=True) | Q(obra=obra) if obra else Q(obra__isnull=True)
    insumos = list(Insumo.objects.filter(filtro))
    usados = set(ItemComposicao.objects.filter(insumo__in=insumos).values_list("insumo_id", flat=True))
    comps = Composicao.objects.filter(filtro).prefetch_related("itens__insumo")
    return {
        "insumos": [{"id": i.pk, "codigo": i.codigo, "descricao": i.descricao, "unidade": i.unidade, "tipo": i.tipo,
                     "preco": f(i.preco), "base": i.obra_id is None, "emUso": i.pk in usados} for i in insumos],
        "composicoes": [{"id": c.pk, "codigo": c.codigo, "descricao": c.descricao, "unidade": c.unidade, "base": c.obra_id is None,
                         "referencia": c.referencia, "observacao": c.observacao, "custo": f(c.custo_unitario),
                         "itens": [{"insumoId": i.insumo_id, "coef": f(i.coeficiente)} for i in c.itens.all()]} for c in comps],
        "tiposInsumo": [{"id": k, "nome": v} for k, v in Insumo.TIPOS],
        "etapasPadrao": ETAPAS_PADRAO,
        "podeEditarBase": pode_editar_base(usuario),
    }


def estado_sem_obra(usuario):
    """Estado para quem ainda não tem obra liberada: listas vazias e o aviso."""
    return {
        "semObra": True,
        "obra": {"nome": "", "cliente": "", "prazo": "", "valorContratado": 0}, "exemplo": False,
        "orcamento": [], "etapas": [], "etapaAvanco": {}, "fornecedores": [], "materiais": [], "notasFiscais": [], "pedidos": [],
        "tiposDocumento": [{"id": k, "nome": v} for k, v in NotaFiscal.TIPOS], "tiposBaixa": [{"id": k, "nome": v} for k, v in Consumo.TIPOS],
        "empreiteiros": [], "contratos": [], "medicoes": [], "pagamentos": [],
        **catalogo(None, usuario),
        "usuario": _usuario(usuario),
        "obraId": None, "souDono": False, "donoNome": "", "obras": [],
        "seq": 10 ** 9, "nextIds": {"nf": 1, "pedido": 1, "contrato": 1, "medicao": 1, "pagamento": 1},
    }


def estado(obra, usuario):
    f = float
    iso = lambda d: d.isoformat() if d else ""
    notas = []
    for n in obra.notas.prefetch_related("itens"):
        notas.append({"id": n.pk, "fornecedorId": n.fornecedor_id, "numero": n.numero, "data": iso(n.data), "tipo": n.tipo,
                      "itens": [{"materialId": i.material_id, "orcamentoItemId": i.item_id, "qtd": f(i.quantidade), "valorUnit": f(i.valor_unitario)} for i in n.itens.all()]})
    etapas = list(obra.etapas.all())
    orc = obra.orcamento.select_related("etapa").prefetch_related("insumos")
    return {
        "obra": {"nome": obra.nome, "cliente": obra.cliente, "prazo": iso(obra.prazo), "valorContratado": f(obra.valor_contratado)},
        "exemplo": obra.exemplo,
        "orcamento": [{"id": i.pk, "etapaId": i.etapa_id, "etapa": i.etapa.nome, "composicaoId": i.composicao_id, "codigo": i.codigo,
                       "servico": i.servico, "observacao": i.observacao, "insumo": i.observacao, "unidade": i.unidade,
                       "qtd": f(i.quantidade), "precoUnit": f(i.preco_unitario),
                       "insumos": [{"insumoId": p.insumo_id, "coef": f(p.coeficiente), "preco": f(p.preco_unitario)} for p in i.insumos.all()]}
                      for i in orc],
        "etapas": [{"id": e.pk, "nome": e.nome, "ordem": e.ordem, "percentual": f(e.percentual)} for e in etapas],
        "etapaAvanco": {e.nome: f(e.percentual) for e in etapas},
        **catalogo(obra, usuario),
        "fornecedores": [{"id": x.pk, "nome": x.nome, "contato": x.contato} for x in obra.fornecedores.all()],
        "materiais": [{"id": x.pk, "insumoId": x.insumo_id, "nome": x.nome, "unidade": x.unidade, "saldo": f(x.saldo), "custoMedio": f(x.custo_medio)} for x in obra.materiais.all()],
        "notasFiscais": notas,
        "pedidos": [{"id": c.pk, "orcamentoItemId": c.item_id, "materialId": c.material_id, "tipo": c.tipo, "observacao": c.observacao, "qtd": f(c.quantidade),
                     "qtdSolicitada": f(c.quantidade_solicitada), "valor": f(c.valor), "data": iso(c.data)} for c in obra.consumos.all()],
        "tiposDocumento": [{"id": k, "nome": v} for k, v in NotaFiscal.TIPOS],
        "tiposBaixa": [{"id": k, "nome": v} for k, v in Consumo.TIPOS],
        "empreiteiros": [{"id": x.pk, "nome": x.nome, "contato": x.contato, "especialidade": x.especialidade} for x in obra.empreiteiros.all()],
        "contratos": [{"id": c.pk, "empreiteiroId": c.empreiteiro_id, "orcamentoItemId": c.item_id, "valorContratado": f(c.valor_contratado), "formaPagamento": c.forma_pagamento} for c in obra.contratos.all()],
        "medicoes": [{"id": m.pk, "contratoId": m.contrato_id, "data": iso(m.data), "percentual": f(m.percentual), "valor": f(m.valor), "status": m.status} for m in obra.medicoes.all()],
        "pagamentos": [{"id": p.pk, "tipo": p.tipo, "origem": p.origem, "orcamentoItemId": p.item_id, "valor": f(p.valor), "dataProgramada": iso(p.data_programada),
                        "dataPagamento": iso(p.data_pagamento) or None, "status": p.status, "medicaoId": p.medicao_id} for p in obra.pagamentos.all()],
        "semObra": False,
        "usuario": _usuario(usuario),
        "obraId": obra.pk,
        "souDono": pode_apagar_tudo(obra, usuario),
        "donoNome": obra.dono.get_full_name() or obra.dono.username,
        "obras": [{"id": o.pk, "nome": o.nome, "dono": o.dono.get_full_name() or o.dono.username, "souDono": o.dono_id == usuario.pk}
                  for o in obras_do_usuario(usuario).select_related("dono")],
        # IDs temporários usados só pela importação de planilha no navegador
        "seq": 10 ** 9,
        "nextIds": {"nf": 1, "pedido": 1, "contrato": 1, "medicao": 1, "pagamento": 1},
    }
