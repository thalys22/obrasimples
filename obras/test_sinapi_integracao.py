import json
import os
import tempfile
import unittest
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import Client, TestCase

from sinapi import carga
from sinapi.models import PrecoInsumo
from sinapi.tests import BASE, montar_xlsx, openpyxl

from . import services as S
from .models import Composicao, Insumo, ItemOrcamento, Obra


@unittest.skipUnless(openpyxl, "openpyxl não instalado (requirements-etl.txt)")
class IntegracaoSinapiTests(TestCase):
    def setUp(self):
        self.ana = User.objects.create_user("ana", password="x" * 12)
        self.beto = User.objects.create_user("beto", password="y" * 12)
        self.obra = Obra.objects.create(dono=self.ana)
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        arq = os.path.join(self.d.name, "s.xlsx")
        montar_xlsx(arq)
        carga.carregar(arq, BASE, ["SE"], ["sd"], saida=lambda *_: None)
        self.c = Client()
        self.c.force_login(self.ana)

    def importar(self, codigo=12, **kw):
        return S.importar_sinapi_composicao(self.obra, dict(codigo=codigo, uf="SE", base="2026-09", regime="sd", **kw))

    def post(self, url, corpo=None):
        return self.c.post(url, json.dumps(corpo or {}), content_type="application/json")

    def test_importa_copia_com_insumos_achatados_e_rotulo(self):
        comp, avisos = self.importar()
        self.assertEqual((comp.codigo, comp.fonte, comp.codigo_fonte, comp.uf, comp.regime), ("SINAPI-12", "sinapi", "12", "SE", "sd"))
        self.assertEqual(comp.data_base, date(2026, 9, 1))
        self.assertEqual(comp.custo_publicado, Decimal("74.1"))
        self.assertEqual(S.rotulo_fonte(comp), "SINAPI 12 · SE · 09/2026 · sem desoneração")
        coefs = {i.insumo.codigo_fonte: i.coeficiente for i in comp.itens.select_related("insumo")}
        self.assertEqual(coefs, {"100": Decimal("9"), "200": Decimal("0.036"), "300": Decimal("2"), "400": Decimal("0.5")})
        self.assertLess(abs(comp.custo_unitario - comp.custo_publicado), Decimal("0.02"))
        areia = Insumo.objects.get(obra=self.obra, codigo="SINAPI-200")
        self.assertEqual((areia.origem_preco, areia.preco, areia.fonte, areia.tipo, areia.unidade), ("sp", Decimal("100"), "sinapi", "material", "m³"))
        self.assertTrue(any("São Paulo" in a for a in avisos))
        self.assertEqual(Composicao.objects.filter(obra__isnull=True, fonte="sinapi").count(), 0, "sempre na obra, nunca na base geral")

    def test_importar_duas_vezes_nao_duplica(self):
        a, _ = self.importar()
        n = Insumo.objects.filter(obra=self.obra).count()
        b, avisos = self.importar()
        self.assertEqual(a.pk, b.pk)
        self.assertEqual(Insumo.objects.filter(obra=self.obra).count(), n)
        self.assertIn("já estava", avisos[0])

    def test_composicoes_que_dividem_insumo_reaproveitam_o_cadastro(self):
        self.importar(12)
        self.importar(13)
        self.assertEqual(Insumo.objects.filter(obra=self.obra, codigo="SINAPI-100").count(), 1)

    def test_outra_data_base_ja_importada_pede_atualizar(self):
        self.importar()
        Composicao.objects.filter(obra=self.obra).update(data_base=date(2026, 8, 1))
        with self.assertRaisesMessage(S.RegraNegocio, "Atualizar"):
            self.importar()

    def test_preco_ausente_vira_sem_preco_e_nunca_zero_em_silencio(self):
        PrecoInsumo.objects.filter(insumo__codigo=400).update(preco=None, origem_preco="")
        comp, avisos = self.importar()
        ped = Insumo.objects.get(obra=self.obra, codigo="SINAPI-400")
        self.assertTrue(ped.sem_preco)
        self.assertEqual(ped.preco, 0)
        self.assertTrue(any("sem preço" in a for a in avisos))
        cat = {c["codigo"]: c for c in S.catalogo(self.obra, self.ana)["composicoes"]}
        self.assertEqual(cat["SINAPI-12"]["semPreco"], 1)

    def test_composicao_sem_custo_nao_importa(self):
        with self.assertRaisesMessage(S.RegraNegocio, "não publicou custo"):
            self.importar(14)

    def test_referencia_inexistente_vira_erro_de_regra(self):
        with self.assertRaisesMessage(S.RegraNegocio, "não está carregada"):
            S.importar_sinapi_composicao(self.obra, dict(codigo=12, uf="SE", base="2025-01", regime="sd"))

    def test_composicao_e_insumos_sinapi_sao_travados(self):
        comp, _ = self.importar()
        with self.assertRaisesMessage(S.RegraNegocio, "Duplicar"):
            S.salvar_composicao(self.obra, self.ana, dict(descricao="x", unidade="m²", itens=[]), pk=comp.pk)
        ins = Insumo.objects.get(obra=self.obra, codigo="SINAPI-100")
        with self.assertRaisesMessage(S.RegraNegocio, "não pode ser editado"):
            S.salvar_insumo(self.obra, self.ana, dict(descricao="x", unidade="kg", preco=9), pk=ins.pk)

    def test_so_o_preco_ausente_pode_ser_preenchido(self):
        PrecoInsumo.objects.filter(insumo__codigo=400).update(preco=None, origem_preco="")
        self.importar()
        ped = Insumo.objects.get(obra=self.obra, codigo="SINAPI-400")
        S.salvar_insumo(self.obra, self.ana, dict(preco=26.5), pk=ped.pk)
        ped.refresh_from_db()
        self.assertEqual((ped.preco, ped.sem_preco, ped.descricao), (Decimal("26.5"), False, "PEDREIRO"))
        with self.assertRaises(S.RegraNegocio):
            S.salvar_insumo(self.obra, self.ana, dict(preco=0), pk=Insumo.objects.get(obra=self.obra, codigo="SINAPI-100").pk)

    def test_duplicar_gera_composicao_propria_editavel(self):
        comp, _ = self.importar()
        nova = S.duplicar_composicao(self.obra, comp.pk)
        self.assertEqual(nova.fonte, "proprio")
        self.assertIn("SINAPI-12", nova.observacao)
        itens = [dict(insumoId=i.insumo_id, coef=i.coeficiente) for i in nova.itens.all()]
        itens[0]["coef"] = 99
        S.salvar_composicao(self.obra, self.ana, dict(descricao=nova.descricao, unidade=nova.unidade, itens=itens), pk=nova.pk)

    def test_servico_no_orcamento_congela_preco_e_origem(self):
        comp, _ = self.importar()
        item = S.adicionar_item(self.obra, dict(etapa="Alvenaria", composicaoId=comp.pk, qtd=10))
        self.assertEqual(item.origem, "SINAPI 12 · SE · 09/2026 · sem desoneração")
        self.assertLess(abs(item.preco_unitario - Decimal("74.10")), Decimal("0.02"))
        self.assertEqual(item.insumos.count(), 4)
        # preço do SINAPI mudar depois não altera o que foi orçado
        Insumo.objects.filter(obra=self.obra, codigo="SINAPI-100").update(preco=50)
        item.refresh_from_db()
        self.assertLess(abs(item.preco_unitario - Decimal("74.10")), Decimal("0.02"))
        e = S.estado(self.obra, self.ana)
        self.assertEqual(next(i for i in e["orcamento"] if i["id"] == item.pk)["origem"], item.origem)

    def test_descricao_longa_do_sinapi_cabe_no_orcamento(self):
        comp, _ = self.importar()
        Composicao.objects.filter(pk=comp.pk).update(descricao="A" * 380)
        item = S.adicionar_item(self.obra, dict(etapa="Alvenaria", composicaoId=comp.pk, qtd=1))
        self.assertEqual(len(item.servico), 380)

    def test_uf_e_regime_da_obra(self):
        S.atualizar_obra(self.obra, dict(uf="ba", regimeSinapi="cd"))
        self.obra.refresh_from_db()
        self.assertEqual((self.obra.uf, self.obra.regime_sinapi), ("BA", "cd"))
        with self.assertRaises(S.RegraNegocio):
            S.atualizar_obra(self.obra, dict(uf="Sergipe"))
        with self.assertRaises(S.RegraNegocio):
            S.atualizar_obra(self.obra, dict(regimeSinapi="se"))

    # ---- API
    def test_api_busca_e_previa_nao_incluem_estado(self):
        r = self.c.get("/api/sinapi/composicoes?q=alvenaria&base=2026-09")
        self.assertEqual(r.status_code, 200, r.content)
        j = r.json()
        self.assertNotIn("estado", j)
        self.assertEqual(j["total"], 2)
        self.assertIsInstance(j["itens"][0]["custo"], float)
        r = self.c.get("/api/sinapi/composicoes/12?base=2026-09")
        j = r.json()["composicao"]
        self.assertNotIn("estado", r.json())
        self.assertEqual(j["custo"], 74.1)
        self.assertEqual(j["itens"][0]["origem_preco"] in ("local", "sp"), True)
        self.assertTrue(any(i["origem_preco"] == "sp" for i in j["itens"]))

    def test_api_erros_viram_400_com_mensagem(self):
        r = self.c.get("/api/sinapi/composicoes?q=a&base=2026-09")
        self.assertEqual(r.status_code, 400)
        self.assertIn("pelo menos", r.json()["erro"])
        r = self.c.get("/api/sinapi/composicoes?q=alvenaria&base=2026-09&uf=BA")
        self.assertEqual(r.status_code, 400)

    def test_api_importar_devolve_estado_com_a_composicao(self):
        r = self.post("/api/sinapi/importar", dict(codigo=12, base="2026-09"))
        self.assertEqual(r.status_code, 200, r.content)
        j = r.json()
        comp = next(c for c in j["estado"]["composicoes"] if c["codigo"] == "SINAPI-12")
        self.assertEqual((comp["fonte"], comp["origem"], comp["custoPublicado"]), ("sinapi", "SINAPI 12 · SE · 09/2026 · sem desoneração", 74.1))
        self.assertEqual(j["composicaoId"], comp["id"])

    def test_estado_nao_carrega_dados_do_sinapi(self):
        self.assertEqual(self.c.get("/api/estado").status_code, 200)
        e = self.c.get("/api/estado").json()["estado"]
        self.assertFalse([k for k in e if "sinapi" in k.lower()])
        self.assertEqual(len(json.dumps(e)) < 200_000, True)

    def test_importacao_vai_so_para_a_obra_de_quem_pediu(self):
        outra = Client()
        outra.force_login(self.beto)
        r = outra.post("/api/sinapi/importar", json.dumps(dict(codigo=12, base="2026-09")), content_type="application/json")
        self.assertEqual(r.status_code, 400)  # beto não tem obra liberada
        self.assertEqual(Composicao.objects.filter(fonte="sinapi").count(), 0)
        self.post("/api/sinapi/importar", dict(codigo=12, base="2026-09"))
        self.assertEqual(Composicao.objects.get(fonte="sinapi").obra_id, self.obra.pk)
        self.assertFalse(Obra.objects.exclude(pk=self.obra.pk).exists())

    def test_sem_login_401(self):
        self.assertEqual(Client().get("/api/sinapi/referencias").status_code, 401)

    def test_api_referencias(self):
        j = self.c.get("/api/sinapi/referencias").json()
        self.assertEqual(j["referencias"], [dict(uf="SE", data_base="2026-09", regime="sd")])
        self.assertEqual(j["padrao"], dict(uf="SE", regime="sd"))
