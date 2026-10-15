import json
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


def api(metodos):
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
            if obra is None:
                if request.method == "GET":
                    return JsonResponse({"estado": S.estado_sem_obra(request.user)})
                return JsonResponse({"erro": "Nenhuma obra foi liberada para você ainda. Fale com o administrador."}, status=400)
            request.session["obra_id"] = obra.pk
            try:
                extra = fn(request, obra, corpo, *args, **kwargs) or {}
            except S.RegraNegocio as e:
                return JsonResponse({"erro": str(e)}, status=400)
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
    return {"id": S.adicionar_material(obra, d).pk}


@api(["POST"])
def nota_criar(request, obra, d):
    nota = S.lancar_nf(obra, d)
    return {"id": nota.pk, "total": float(nota.pagamento.valor)}


@api(["POST"])
def consumo_criar(request, obra, d):
    c = S.registrar_consumo(obra, d)
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
