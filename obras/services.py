"""
Regras de negócio do ObraSimples. Toda alteração de dados passa por aqui,
dentro de uma transação, sempre filtrando pela obra do usuário logado.
"""
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .models import (
    Consumo, Contrato, Empreiteiro, EtapaAvanco, Fornecedor, ItemNota, ItemOrcamento,
    Material, Medicao, NotaFiscal, Obra, Pagamento,
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
def obter_obra(usuario):
    obra = usuario.obras.order_by("id").first()
    if obra is None:
        with transaction.atomic():
            obra = Obra.objects.create(dono=usuario)
            carregar_exemplo(obra)
    return obra


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


def definir_avanco(obra, etapa, percentual):
    p = max(D0, min(Decimal("100"), dec(percentual or 0, "o percentual")))
    EtapaAvanco.objects.update_or_create(obra=obra, etapa=texto(etapa, "a etapa", maximo=120), defaults={"percentual": p})


# ---------------------------------------------------------------- orçamento
@transaction.atomic
def adicionar_item(obra, d):
    item = ItemOrcamento.objects.create(
        obra=obra,
        etapa=texto(d.get("etapa"), "a etapa", maximo=120),
        servico=texto(d.get("servico"), "o serviço"),
        insumo=texto(d.get("insumo"), "o insumo", obrigatorio=False),
        unidade=texto(d.get("unidade"), "a unidade", maximo=20),
        quantidade=dec(d.get("qtd"), "a quantidade", minimo=D0),
        preco_unitario=dec(d.get("precoUnit"), "o preço unitário", minimo=D0),
    )
    EtapaAvanco.objects.get_or_create(obra=obra, etapa=item.etapa)
    return item


def item_tem_vinculo(item):
    return item.consumos.exists() or item.contratos.exists() or item.pagamentos.exists()


@transaction.atomic
def excluir_item(obra, item_id):
    item = pegar(ItemOrcamento, obra, item_id, "Serviço")
    if item_tem_vinculo(item):
        raise RegraNegocio("Esse serviço já tem gastos ligados a ele e não pode ser excluído.")
    item.delete()


# ---------------------------------------------------------------- cadastros
def adicionar_fornecedor(obra, d):
    return Fornecedor.objects.create(obra=obra, nome=texto(d.get("nome"), "o nome do fornecedor"), contato=texto(d.get("contato"), "o contato", obrigatorio=False))


def adicionar_material(obra, d):
    return Material.objects.create(obra=obra, nome=texto(d.get("nome"), "o nome do material"), unidade=texto(d.get("unidade"), "a unidade", maximo=20))


def adicionar_empreiteiro(obra, d):
    return Empreiteiro.objects.create(
        obra=obra, nome=texto(d.get("nome"), "o nome do empreiteiro"),
        contato=texto(d.get("contato"), "o contato", obrigatorio=False),
        especialidade=texto(d.get("especialidade"), "a especialidade", obrigatorio=False),
    )


# ---------------------------------------------------------------- estoque
@transaction.atomic
def lancar_nf(obra, d):
    numero = texto(d.get("numero"), "o número da nota", maximo=60)
    fornecedor = pegar(Fornecedor, obra, d.get("fornecedorId"), "Fornecedor")
    venc = data_iso(d.get("data"), "data de vencimento")
    itens = d.get("itens") or []
    if not itens:
        raise RegraNegocio("Adicione pelo menos um item à nota.")
    nota = NotaFiscal.objects.create(obra=obra, fornecedor=fornecedor, numero=numero, data=venc)
    total = D0
    for it in itens:
        mat = Material.objects.select_for_update().get(pk=pegar(Material, obra, it.get("materialId"), "Material").pk)
        qtd = dec(it.get("qtd"), "a quantidade", minimo=D0)
        vu = dec(it.get("valorUnit"), "o valor unitário", minimo=D0)
        entrada = qtd * vu
        novo_saldo = mat.saldo + qtd
        mat.custo_medio = ((mat.saldo * mat.custo_medio + entrada) / novo_saldo).quantize(Decimal("0.000001"), ROUND_HALF_UP)
        mat.saldo = novo_saldo
        mat.save()
        ItemNota.objects.create(nota=nota, material=mat, quantidade=qtd, valor_unitario=vu)
        total += entrada
    origem = numero if numero.lower().startswith("nf") else f"NF {numero}"
    Pagamento.objects.create(obra=obra, tipo=Pagamento.MATERIAL, origem=origem, valor=total.quantize(CENT, ROUND_HALF_UP), data_programada=venc, nota=nota)
    return nota


@transaction.atomic
def registrar_consumo(obra, d):
    item = pegar(ItemOrcamento, obra, d.get("orcamentoItemId"), "Serviço")
    mat = Material.objects.select_for_update().get(pk=pegar(Material, obra, d.get("materialId"), "Material").pk)
    qtd = dec(d.get("qtd"), "a quantidade", minimo=D0)
    dia = data_iso(d.get("data"))
    if mat.saldo <= 0:
        raise RegraNegocio(f"{mat.nome} está sem saldo no estoque. Lance uma nota fiscal primeiro.")
    if qtd > mat.saldo and not d.get("aceitarParcial"):
        raise RegraNegocio(f"O estoque tem só {mat.saldo.normalize():f} {mat.unidade} de {mat.nome}.")
    usada = min(qtd, mat.saldo)
    valor = (usada * mat.custo_medio).quantize(CENT, ROUND_HALF_UP)
    mat.saldo -= usada
    mat.save()
    return Consumo.objects.create(obra=obra, item=item, material=mat, quantidade=usada, quantidade_solicitada=qtd, valor=valor, data=dia)


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
    for it in e.get("orcamento") or []:
        if not it.get("etapa") or not it.get("servico"):
            continue
        novo = ItemOrcamento.objects.create(obra=obra, etapa=str(it["etapa"])[:120], servico=str(it["servico"])[:200], insumo=str(it.get("insumo") or "")[:200],
                                            unidade=str(it.get("unidade") or "")[:20], quantidade=num(it.get("qtd")), preco_unitario=num(it.get("precoUnit")))
        m_item[str(it.get("id"))] = novo
    for et, pct in (e.get("etapaAvanco") or {}).items():
        EtapaAvanco.objects.update_or_create(obra=obra, etapa=str(et)[:120], defaults={"percentual": max(D0, min(Decimal(100), num(pct)))})
    for et in set(i.etapa for i in m_item.values()):
        EtapaAvanco.objects.get_or_create(obra=obra, etapa=et)
    for f in e.get("fornecedores") or []:
        m_forn[str(f.get("id"))] = Fornecedor.objects.create(obra=obra, nome=str(f.get("nome") or "Fornecedor")[:200], contato=str(f.get("contato") or "")[:200])
    for m in e.get("materiais") or []:
        m_mat[str(m.get("id"))] = Material.objects.create(obra=obra, nome=str(m.get("nome") or "Material")[:200], unidade=str(m.get("unidade") or "")[:20],
                                                          saldo=num(m.get("saldo")), custo_medio=num(m.get("custoMedio")))
    for nf in e.get("notasFiscais") or []:
        forn = m_forn.get(str(nf.get("fornecedorId")))
        if not forn:
            continue
        nota = NotaFiscal.objects.create(obra=obra, fornecedor=forn, numero=str(nf.get("numero") or "")[:60], data=data_iso(nf.get("data")) or timezone.localdate())
        for it in nf.get("itens") or []:
            mat = m_mat.get(str(it.get("materialId")))
            if mat:
                ItemNota.objects.create(nota=nota, material=mat, quantidade=num(it.get("qtd")), valor_unitario=num(it.get("valorUnit")))
        m_nf[str(nf.get("id"))] = nota
    for p in e.get("pedidos") or []:
        item, mat = m_item.get(str(p.get("orcamentoItemId"))), m_mat.get(str(p.get("materialId")))
        if item and mat:
            Consumo.objects.create(obra=obra, item=item, material=mat, quantidade=num(p.get("qtd")), quantidade_solicitada=num(p.get("qtdSolicitada") or p.get("qtd")),
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
    obra.nome, obra.cliente, obra.prazo = "Residencial Bela Vista", "Construtora Horizonte Ltda.", date(2027, 3, 15)
    obra.valor_contratado, obra.exemplo = Decimal("315000"), True
    obra.save()
    linhas = [
        ("Fundação", "Escavação e sapatas", "Cimento, escavação e mão de obra", "m³", 120, 180),
        ("Fundação", "Concreto estrutural", "Concreto usinado FCK 25 + aço", "m³", 60, 620),
        ("Estrutura", "Alvenaria estrutural", "Bloco estrutural 14x19x39", "m²", 480, 145),
        ("Estrutura", "Laje pré-moldada", "Vigota e lajota pré-moldada", "m²", 210, 210),
        ("Instalações", "Instalação elétrica", "Cabos e conduítes elétricos", "ponto", 150, 95),
        ("Instalações", "Instalação hidráulica", "Tubos e conexões PVC", "ponto", 90, 110),
        ("Acabamento", "Revestimento cerâmico", "Porcelanato 60x60", "m²", 340, 78),
        ("Acabamento", "Pintura interna/externa", "Tinta acrílica", "m²", 520, 34),
    ]
    itens = [adicionar_item(obra, dict(etapa=a, servico=b, insumo=c, unidade=u, qtd=q, precoUnit=p)) for a, b, c, u, q, p in linhas]
    for et, pct in {"Fundação": 100, "Estrutura": 65, "Instalações": 30, "Acabamento": 5}.items():
        definir_avanco(obra, et, pct)
    f = [adicionar_fornecedor(obra, dict(nome=n, contato=c)) for n, c in [
        ("Cimento Forte Materiais", "(79) 3211-4400"), ("Ferragens União", "(79) 3211-8899"), ("Cerâmica Costa do Sol", "(79) 3025-1122")]]
    m = [adicionar_material(obra, dict(nome=n, unidade=u)) for n, u in [
        ("Cimento CP-II (saco 50kg)", "sc"), ("Aço CA-50 10mm", "kg"), ("Bloco estrutural 14x19x39", "un"), ("Porcelanato 60x60", "m²")]]
    e = [adicionar_empreiteiro(obra, dict(nome=n, contato=c, especialidade=s)) for n, c, s in [
        ("Equipe Silva Estrutura", "(79) 99911-2233", "Estrutura/Alvenaria"), ("Elétrica Santos", "(79) 99822-1010", "Instalações elétricas")]]
    nf1 = lancar_nf(obra, dict(fornecedorId=f[0].pk, numero="NF-4521", data="2026-06-02", itens=[dict(materialId=m[0].pk, qtd=400, valorUnit="32.5"), dict(materialId=m[1].pk, qtd=2000, valorUnit="7.2")]))
    lancar_nf(obra, dict(fornecedorId=f[1].pk, numero="NF-1187", data="2026-06-10", itens=[dict(materialId=m[2].pk, qtd=6000, valorUnit="3.9")]))
    registrar_consumo(obra, dict(orcamentoItemId=itens[0].pk, materialId=m[0].pk, qtd=180, data="2026-06-05"))
    registrar_consumo(obra, dict(orcamentoItemId=itens[1].pk, materialId=m[1].pk, qtd=1400, data="2026-06-12"))
    registrar_consumo(obra, dict(orcamentoItemId=itens[2].pk, materialId=m[2].pk, qtd=4200, data="2026-06-20"))
    c1 = criar_contrato(obra, dict(empreiteiroId=e[0].pk, orcamentoItemId=itens[2].pk, valorContratado=65000, formaPagamento="Por medição mensal"))
    c2 = criar_contrato(obra, dict(empreiteiroId=e[1].pk, orcamentoItemId=itens[4].pk, valorContratado=12500, formaPagamento="Por medição mensal"))
    aprovar_medicao(obra, registrar_medicao(obra, dict(contratoId=c1.pk, data="2026-06-25", percentual=40)).pk)
    registrar_medicao(obra, dict(contratoId=c2.pk, data="2026-07-05", percentual=20))
    marcar_pago(obra, nf1.pagamento.pk, date(2026, 7, 2))


# ---------------------------------------------------------------- leitura (formato que o app usa)
def estado(obra, usuario):
    f = float
    iso = lambda d: d.isoformat() if d else ""
    notas = []
    for n in obra.notas.prefetch_related("itens"):
        notas.append({"id": n.pk, "fornecedorId": n.fornecedor_id, "numero": n.numero, "data": iso(n.data),
                      "itens": [{"materialId": i.material_id, "qtd": f(i.quantidade), "valorUnit": f(i.valor_unitario)} for i in n.itens.all()]})
    return {
        "obra": {"nome": obra.nome, "cliente": obra.cliente, "prazo": iso(obra.prazo), "valorContratado": f(obra.valor_contratado)},
        "exemplo": obra.exemplo,
        "orcamento": [{"id": i.pk, "etapa": i.etapa, "servico": i.servico, "insumo": i.insumo, "unidade": i.unidade, "qtd": f(i.quantidade), "precoUnit": f(i.preco_unitario)} for i in obra.orcamento.all()],
        "etapaAvanco": {e.etapa: f(e.percentual) for e in obra.etapas.all()},
        "fornecedores": [{"id": x.pk, "nome": x.nome, "contato": x.contato} for x in obra.fornecedores.all()],
        "materiais": [{"id": x.pk, "nome": x.nome, "unidade": x.unidade, "saldo": f(x.saldo), "custoMedio": f(x.custo_medio)} for x in obra.materiais.all()],
        "notasFiscais": notas,
        "pedidos": [{"id": c.pk, "orcamentoItemId": c.item_id, "materialId": c.material_id, "qtd": f(c.quantidade), "qtdSolicitada": f(c.quantidade_solicitada), "valor": f(c.valor), "data": iso(c.data)} for c in obra.consumos.all()],
        "empreiteiros": [{"id": x.pk, "nome": x.nome, "contato": x.contato, "especialidade": x.especialidade} for x in obra.empreiteiros.all()],
        "contratos": [{"id": c.pk, "empreiteiroId": c.empreiteiro_id, "orcamentoItemId": c.item_id, "valorContratado": f(c.valor_contratado), "formaPagamento": c.forma_pagamento} for c in obra.contratos.all()],
        "medicoes": [{"id": m.pk, "contratoId": m.contrato_id, "data": iso(m.data), "percentual": f(m.percentual), "valor": f(m.valor), "status": m.status} for m in obra.medicoes.all()],
        "pagamentos": [{"id": p.pk, "tipo": p.tipo, "origem": p.origem, "orcamentoItemId": p.item_id, "valor": f(p.valor), "dataProgramada": iso(p.data_programada),
                        "dataPagamento": iso(p.data_pagamento) or None, "status": p.status, "medicaoId": p.medicao_id} for p in obra.pagamentos.all()],
        "usuario": {"nome": usuario.get_full_name() or usuario.username, "login": usuario.username, "admin": usuario.is_staff},
        # IDs temporários usados só pela importação de planilha no navegador
        "seq": 10 ** 9,
        "nextIds": {"nf": 1, "pedido": 1, "contrato": 1, "medicao": 1, "pagamento": 1},
    }
