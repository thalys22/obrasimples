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
            obra = S.obter_obra(request.user)
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


@api(["DELETE"])
def orcamento_excluir(request, obra, d, pk):
    S.excluir_item(obra, pk)


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
    S.recomecar(obra, "exemplo" if d.get("tipo") == "exemplo" else "vazio")


@api(["POST"])
def importar(request, obra, d):
    S.substituir(obra, d.get("estado") or {})
