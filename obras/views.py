import json
from decimal import Decimal
from functools import wraps
from pathlib import Path

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods

from . import services as S

APP_HTML = Path(settings.BASE_DIR) / "frontend" / "app.html"


@login_required
@ensure_csrf_cookie
def app(request):
    """Entrega o aplicativo (página única). Os dados chegam pela API."""
    return HttpResponse(APP_HTML.read_bytes(), content_type="text/html; charset=utf-8")


def api(metodos, com_estado=True, exige_obra=True):
    """Exige login, lê o JSON, carrega a obra do usuário e devolve o estado atualizado."""
    def deco(fn):
        @wraps(fn)
        @require_http_methods(metodos)
        def inner(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return JsonResponse({"erro": "Sua sessão expirou. Entre de novo."}, status=401)
            try:
                corpo = json.loads(request.body or b"{}") if request.method in ("POST", "PUT", "PATCH") else {}
                if not isinstance(corpo, dict):
                    raise ValueError
            except ValueError:
                return JsonResponse({"erro": "Requisição inválida."}, status=400)
            obra = S.obter_obra(request.user, request.session.get("obra_id"))
            if obra is None and not exige_obra:
                pass
            elif obra is None:
                if request.method == "GET":
                    return JsonResponse({"estado": S.estado_sem_obra(request.user)})
                return JsonResponse({"erro": "Nenhuma obra foi liberada para você ainda. Fale com o administrador."}, status=400)
            if obra is not None:
                request.session["obra_id"] = obra.pk
            try:
                extra = fn(request, obra, corpo, *args, **kwargs) or {}
            except S.RegraNegocio as e:
                return JsonResponse({"erro": str(e)}, status=400)
            if not com_estado:
                return JsonResponse(extra)
            if obra is not None:
                obra.refresh_from_db()
            return JsonResponse({"estado": S.estado(obra, request.user), **extra})
        return inner
    return deco


@api(["GET"])
def estado(request, obra, d):
    return None


@api(["POST"])
def obra_atualizar(request, obra, d):
    S.atualizar_obra(obra, d)


@api(["POST"])
def etapa_avanco(request, obra, d):
    S.definir_avanco(obra, d.get("etapa"), d.get("percentual"))


@api(["POST"])
def orcamento_criar(request, obra, d):
    return {"id": S.adicionar_item(obra, d).pk}


@api(["DELETE", "POST"])
def orcamento_item(request, obra, d, pk):
    if request.method == "DELETE":
        S.excluir_item(obra, pk)
    else:
        S.atualizar_item(obra, pk, d)


@api(["POST"])
def orcamento_atualizar_composicao(request, obra, d, pk):
    S.atualizar_pela_composicao(obra, pk)


@api(["POST"])
def orcamento_importar(request, obra, d):
    return S.importar_orcamento(obra, d.get("linhas"))


# ---- etapas
@api(["POST"])
def etapa_criar(request, obra, d):
    return {"id": S.criar_etapa(obra, d).pk}


@api(["POST", "DELETE"])
def etapa(request, obra, d, pk):
    if request.method == "DELETE":
        S.excluir_etapa(obra, pk)
    else:
        S.renomear_etapa(obra, pk, d)


# ---- cadastro de insumos e composições
@api(["POST"])
def insumo_criar(request, obra, d):
    return {"id": S.salvar_insumo(obra, request.user, d).pk}


@api(["POST", "DELETE"])
def insumo(request, obra, d, pk):
    if request.method == "DELETE":
        S.excluir_insumo(obra, request.user, pk)
    else:
        S.salvar_insumo(obra, request.user, d, pk)


@api(["POST"])
def composicao_criar(request, obra, d):
    return {"id": S.salvar_composicao(obra, request.user, d).pk}


@api(["POST", "DELETE"])
def composicao(request, obra, d, pk):
    if request.method == "DELETE":
        S.excluir_composicao(obra, request.user, pk)
    else:
        S.salvar_composicao(obra, request.user, d, pk)


@api(["POST"])
def composicao_duplicar(request, obra, d, pk):
    return {"id": S.duplicar_composicao(obra, pk).pk}


@api(["POST"])
def catalogo_importar(request, obra, d):
    if d.get("tipo") == "composicoes":
        return S.importar_composicoes(obra, request.user, d.get("escopo"), d.get("linhas"))
    return S.importar_insumos(obra, request.user, d.get("escopo"), d.get("linhas"))


@api(["POST"])
def fornecedor_criar(request, obra, d):
    return {"id": S.adicionar_fornecedor(obra, d).pk}


@api(["POST"])
def material_criar(request, obra, d):
    raise S.RegraNegocio("O estoque não aceita entrada manual. Lance uma nota fiscal ou outro documento de entrada: o material entra no estoque por ele.")


@api(["POST"])
def nota_criar(request, obra, d):
    nota = S.lancar_nf(obra, d)
    return {"id": nota.pk, "total": float(nota.pagamento.valor), "avisos": nota.avisos}


@api(["POST"])
def consumo_criar(request, obra, d):
    c = S.registrar_consumo(obra, d, request.user)
    return {"id": c.pk, "valor": float(c.valor), "qtd": float(c.quantidade)}


@api(["POST"])
def empreiteiro_criar(request, obra, d):
    return {"id": S.adicionar_empreiteiro(obra, d).pk}


@api(["POST"])
def contrato_criar(request, obra, d):
    return {"id": S.criar_contrato(obra, d).pk}


@api(["POST"])
def medicao_criar(request, obra, d):
    m = S.registrar_medicao(obra, d)
    return {"id": m.pk, "valor": float(m.valor)}


@api(["POST"])
def medicao_aprovar(request, obra, d, pk):
    S.aprovar_medicao(obra, pk, request.user)


@api(["DELETE"])
def medicao_excluir(request, obra, d, pk):
    S.excluir_medicao(obra, pk)


@api(["POST"])
def pagamento_criar(request, obra, d):
    return {"id": S.pagamento_avulso(obra, d).pk}


@api(["POST"])
def pagamento_pagar(request, obra, d, pk):
    S.marcar_pago(obra, pk)


@api(["DELETE"])
def pagamento_excluir(request, obra, d, pk):
    S.excluir_pagamento(obra, pk)


@api(["POST"])
def recomecar(request, obra, d):
    S.exigir_dono(obra, request.user)
    S.recomecar(obra, "exemplo" if d.get("tipo") == "exemplo" else "vazio")


@api(["POST"])
def importar(request, obra, d):
    S.exigir_dono(obra, request.user)
    S.substituir(obra, d.get("estado") or {})


@require_http_methods(["POST"])
def selecionar_obra(request):
    """Troca a obra ativa (só entre as obras que o usuário pode abrir)."""
    if not request.user.is_authenticated:
        return JsonResponse({"erro": "Sua sessão expirou. Entre de novo."}, status=401)
    try:
        obra_id = int(json.loads(request.body or b"{}").get("obraId"))
    except (ValueError, TypeError, AttributeError):
        return JsonResponse({"erro": "Obra inválida."}, status=400)
    obra = S.obras_do_usuario(request.user).filter(pk=obra_id).first()
    if obra is None:
        return JsonResponse({"erro": "Você não tem acesso a essa obra."}, status=400)
    request.session["obra_id"] = obra.pk
    return JsonResponse({"estado": S.estado(obra, request.user)})


# ---------------------------------------------------------------- SINAPI (base de consulta; nada disso entra no `estado`)
def _sinapi():
    from sinapi import servico
    return servico


def _com_erro_sinapi(fn):
    try:
        return fn()
    except _sinapi().SinapiErro as e:
        raise S.RegraNegocio(str(e))


def _num(v):
    """Decimal -> float (o JSON padrão do Django serializaria Decimal como texto)."""
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, dict):
        return {k: _num(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_num(x) for x in v]
    return v


@api(["GET"], com_estado=False)
def sinapi_referencias(request, obra, d):
    return {"referencias": _sinapi().referencias_disponiveis(), "padrao": {"uf": obra.uf, "regime": obra.regime_sinapi}}


@api(["GET"], com_estado=False)
def sinapi_buscar(request, obra, d):
    g = request.GET
    return _num(_com_erro_sinapi(lambda: _sinapi().buscar_composicoes(
        g.get("q", ""), g.get("uf") or obra.uf, g.get("base", ""), g.get("regime") or obra.regime_sinapi,
        grupo=g.get("grupo") or None, limite=g.get("limite", 20), deslocamento=g.get("offset", 0),
        incluir_sem_custo=g.get("semCusto") == "1")))


@api(["GET"], com_estado=False)
def sinapi_composicao(request, obra, d, codigo):
    g = request.GET
    return {"composicao": _num(_com_erro_sinapi(lambda: _sinapi().obter_composicao(
        codigo, g.get("uf") or obra.uf, g.get("base", ""), g.get("regime") or obra.regime_sinapi)))}


@api(["POST"])
def sinapi_importar(request, obra, d):
    comp, avisos = S.importar_sinapi_composicao(obra, d)
    return {"composicaoId": comp.pk, "avisos": avisos}


# ---------------------------------------------------------------- carga do SINAPI pelo site (só administrador)
def _carga_web(request, fn):
    if not S.pode_editar_base(request.user):
        raise S.RegraNegocio("Só o administrador carrega o SINAPI.")
    from sinapi import carga as carga_sinapi
    try:
        return fn()
    except carga_sinapi.ErroCarga as e:
        raise S.RegraNegocio(str(e))


@api(["POST"], com_estado=False, exige_obra=False)
def sinapi_carga_iniciar(request, obra, d):
    from sinapi import carga_web
    return _carga_web(request, lambda: carga_web.iniciar(d))


@api(["POST"], com_estado=False, exige_obra=False)
def sinapi_carga_parte(request, obra, d, cid):
    from sinapi import carga_web
    return {"recebidas": _carga_web(request, lambda: carga_web.guardar_parte(cid, d.get("tipo"), d.get("regime", ""), d.get("ordem"), d.get("dados")))}


@api(["POST"], com_estado=False, exige_obra=False)
def sinapi_carga_estrutura(request, obra, d, cid):
    from sinapi import carga_web
    return _carga_web(request, lambda: carga_web.aplicar_estrutura(cid))


@api(["POST"], com_estado=False, exige_obra=False)
def sinapi_carga_referencia(request, obra, d, cid):
    from sinapi import carga_web
    return _carga_web(request, lambda: carga_web.aplicar_referencia(cid, d.get("uf"), d.get("regime")))


@api(["POST"], com_estado=False, exige_obra=False)
def sinapi_carga_concluir(request, obra, d, cid):
    from sinapi import carga_web
    _carga_web(request, lambda: carga_web.concluir(cid))
    return {"ok": True}
