import hashlib
import json
import os
import tempfile
from datetime import date

from django.contrib.auth.models import User
from django.test import Client, TestCase

from obras.models import Obra

from . import carga, leitor
from .models import Carga, CargaParte, Composicao, ComposicaoItem, CustoComposicao, Insumo, PrecoInsumo, Referencia
from .tests import BASE, montar_xlsx, openpyxl

import unittest


def partes_do_xlsx(caminho, ufs, regimes, tam=40):
    """Faz o que o navegador faz: lê o xlsx e devolve as partes no formato compacto de envio."""
    leitura = sorted(set(ufs) | {"SP"})
    wv, wf = leitor.abrir(caminho), leitor.abrir(caminho, formulas=True)
    comps, itens, _ = leitor.ler_analitico(wv)
    out = [("comps", "", [[c, d["grupo"], d["descricao"], d["unidade"], d["situacao"]] for c, d in comps.items()])]
    out.append(("itens", "", [[c, o, 1 if t == "composicao" else 0, a, None if co is None else str(co), 1 if s == "SEM PREÇO" else 0, d, u]
                              for c, o, t, a, d, u, co, s in itens]))
    for i, rg in enumerate(regimes):
        a_ins, a_cus = leitor.ABAS[rg]
        precos = leitor.ler_precos(wv, a_ins, leitura)
        custos = leitor.ler_custos(wf, wv, a_cus, leitura)
        if i == 0:
            out.append(("insumos", "", [[c, d["classificacao"], d["descricao"], d["unidade"]] for c, d in precos.items()]))
        out.append(("precos", rg, [[c, d["coleta"]] + [None if d["precos"][u] is None else str(d["precos"][u]) for u in leitura] for c, d in precos.items()]))
        out.append(("custos", rg, [[c] + [x for u in leitura for x in ((None if d["custos"][u][0] is None else str(d["custos"][u][0])), str(d["custos"][u][1]))]
                                   for c, d in custos.items()]))
    pedacos = []
    for tipo, rg, linhas in out:
        for n in range(0, max(1, len(linhas)), tam):
            pedacos.append((tipo, rg, n // tam, linhas[n:n + tam]))
    return pedacos


@unittest.skipUnless(openpyxl, "openpyxl não instalado (requirements-etl.txt)")
class CargaWebTests(TestCase):
    def setUp(self):
        self.adm = User.objects.create_superuser("adm", "a@x.com", "x" * 12)
        self.ana = User.objects.create_user("ana", password="y" * 12)
        Obra.objects.create(dono=self.ana)
        self.c = Client()
        self.c.force_login(self.adm)
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.arq = os.path.join(self.dir.name, "s.xlsx")

    def post(self, url, corpo=None, client=None):
        return (client or self.c).post(url, json.dumps(corpo or {}), content_type="application/json")

    def sha(self):
        return hashlib.sha256(open(self.arq, "rb").read()).hexdigest()

    def carga_completa(self, ufs=("SE",), regimes=("sd",), cliente=None, **kw):
        montar_xlsx(self.arq, **kw)
        r = self.post("/api/sinapi/carga/iniciar", dict(base="2026-09", ufs=list(ufs), regimes=list(regimes), sha256=self.sha(), arquivo="s.xlsx"), cliente)
        self.assertEqual(r.status_code, 200, r.content)
        cid = r.json()["cargaId"]
        for tipo, rg, ordem, dados in partes_do_xlsx(self.arq, list(ufs), list(regimes)):
            rr = self.post(f"/api/sinapi/carga/{cid}/parte", dict(tipo=tipo, regime=rg, ordem=ordem, dados=dados), cliente)
            self.assertEqual(rr.status_code, 200, rr.content)
        return cid

    def test_fluxo_completo_igual_ao_comando(self):
        cid = self.carga_completa()
        e = self.post(f"/api/sinapi/carga/{cid}/estrutura")
        self.assertEqual(e.status_code, 200, e.content)
        self.assertEqual((e.json()["estruturaNova"], e.json()["composicoes"], e.json()["insumos"]), (True, 6, 5))
        r = self.post(f"/api/sinapi/carga/{cid}/referencia", dict(uf="SE", regime="sd"))
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["conferencia"], dict(dentro=5, ate5=0, acima5=0, sem_calculo=0))
        self.assertEqual(self.post(f"/api/sinapi/carga/{cid}/concluir").status_code, 200)
        self.assertEqual(CargaParte.objects.count(), 0)
        web = (Insumo.objects.count(), Composicao.objects.count(), ComposicaoItem.objects.count(), PrecoInsumo.objects.count(), CustoComposicao.objects.count())
        areia = PrecoInsumo.objects.get(referencia__uf="SE", insumo__codigo=200)
        self.assertEqual((areia.origem_preco, areia.preco), ("sp", 100))
        # o mesmo arquivo pelo comando dá exatamente as mesmas contagens
        for m in (Referencia, Insumo, Composicao, ComposicaoItem, PrecoInsumo, CustoComposicao, Carga):
            m.objects.all().delete()
        carga.carregar(self.arq, BASE, ["SE"], ["sd"], saida=lambda *_: None)
        cmd = (Insumo.objects.count(), Composicao.objects.count(), ComposicaoItem.objects.count(), PrecoInsumo.objects.count(), CustoComposicao.objects.count())
        self.assertEqual(web, cmd)

    def test_busca_funciona_depois_da_carga_pelo_site(self):
        cid = self.carga_completa()
        self.post(f"/api/sinapi/carga/{cid}/estrutura")
        self.post(f"/api/sinapi/carga/{cid}/referencia", dict(uf="SE", regime="sd"))
        Obra.objects.create(dono=self.adm)
        j = self.c.get("/api/sinapi/composicoes?q=alvenaria&base=2026-09&uf=SE&regime=sd").json()
        self.assertEqual(j["total"], 2)

    def test_so_administrador(self):
        outro = Client()
        outro.force_login(self.ana)
        r = self.post("/api/sinapi/carga/iniciar", dict(base="2026-09", ufs=["SE"], regimes=["sd"], sha256="a" * 64), outro)
        self.assertEqual(r.status_code, 400)
        self.assertIn("administrador", r.json()["erro"])
        self.assertEqual(CargaParte.objects.count(), 0)
        cid = self.carga_completa()
        for url, corpo in ((f"/api/sinapi/carga/{cid}/parte", dict(tipo="comps", ordem=0, dados=[])), (f"/api/sinapi/carga/{cid}/estrutura", {}),
                           (f"/api/sinapi/carga/{cid}/referencia", dict(uf="SE", regime="sd")), (f"/api/sinapi/carga/{cid}/concluir", {})):
            self.assertEqual(self.post(url, corpo, outro).status_code, 400, url)
        self.assertEqual(Insumo.objects.count(), 0)
        self.assertEqual(Client().post("/api/sinapi/carga/iniciar", "{}", content_type="application/json").status_code, 401)

    def test_administrador_sem_obra_consegue_carregar(self):
        Obra.objects.filter(dono=self.adm).delete()
        self.carga_completa()  # não levanta

    def test_reenvio_do_mesmo_arquivo_informa_o_que_ja_foi_carregado(self):
        cid = self.carga_completa()
        self.post(f"/api/sinapi/carga/{cid}/estrutura")
        self.post(f"/api/sinapi/carga/{cid}/referencia", dict(uf="SE", regime="sd"))
        r = self.post("/api/sinapi/carga/iniciar", dict(base="2026-09", ufs=["SE"], regimes=["sd"], sha256=self.sha()))
        self.assertEqual(r.json()["jaCarregadas"], ["SE/sd"])
        cid2 = r.json()["cargaId"]
        for tipo, rg, ordem, dados in partes_do_xlsx(self.arq, ["SE"], ["sd"]):
            self.post(f"/api/sinapi/carga/{cid2}/parte", dict(tipo=tipo, regime=rg, ordem=ordem, dados=dados))
        e = self.post(f"/api/sinapi/carga/{cid2}/estrutura").json()
        self.assertFalse(e["estruturaNova"])
        self.assertEqual(ComposicaoItem.objects.count(), 10)

    def test_custo_errado_reprova_a_referencia_e_nada_dela_fica(self):
        cid = self.carga_completa(custo12_se=120.0)
        self.assertEqual(self.post(f"/api/sinapi/carga/{cid}/estrutura").status_code, 200)
        r = self.post(f"/api/sinapi/carga/{cid}/referencia", dict(uf="SE", regime="sd"))
        self.assertEqual(r.status_code, 400)
        self.assertIn("Conferência de custo reprovada", r.json()["erro"])
        self.assertEqual((Referencia.objects.count(), PrecoInsumo.objects.count(), CustoComposicao.objects.count(), Carga.objects.count()), (0, 0, 0, 0))

    def test_ciclo_na_estrutura_e_recusado_sem_gravar(self):
        cid = self.carga_completa(ciclo=True)
        r = self.post(f"/api/sinapi/carga/{cid}/estrutura")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Ciclo", r.json()["erro"])
        self.assertEqual(Composicao.objects.count(), 0)

    def test_validacoes_de_entrada(self):
        ok = dict(base="2026-09", ufs=["SE"], regimes=["sd"], sha256="a" * 64)
        for ruim in (dict(ok, base="09/2026"), dict(ok, base="2026-13"), dict(ok, ufs=[]), dict(ok, ufs=["SE", "SE"]), dict(ok, ufs=["Sergipe"]),
                     dict(ok, regimes=["xx"]), dict(ok, sha256="zz")):
            self.assertEqual(self.post("/api/sinapi/carga/iniciar", ruim).status_code, 400, ruim)
        cid = self.post("/api/sinapi/carga/iniciar", ok).json()["cargaId"]
        for corpo in (dict(tipo="xx", ordem=0, dados=[]), dict(tipo="precos", regime="", ordem=0, dados=[]), dict(tipo="comps", ordem=-1, dados=[]),
                      dict(tipo="comps", ordem=0, dados="x")):
            self.assertEqual(self.post(f"/api/sinapi/carga/{cid}/parte", corpo).status_code, 400, corpo)
        self.assertEqual(self.post("/api/sinapi/carga/naoexiste/parte", dict(tipo="comps", ordem=0, dados=[])).status_code, 400)
        self.assertEqual(self.post(f"/api/sinapi/carga/{cid}/referencia", dict(uf="BA", regime="sd")).status_code, 400)
        big = [["x" * 1000] * 100] * 30
        self.assertEqual(self.post(f"/api/sinapi/carga/{cid}/parte", dict(tipo="comps", ordem=0, dados=big)).status_code, 400)

    def test_estrutura_sem_dados_pede_envio(self):
        cid = self.post("/api/sinapi/carga/iniciar", dict(base="2026-09", ufs=["SE"], regimes=["sd"], sha256="b" * 64)).json()["cargaId"]
        r = self.post(f"/api/sinapi/carga/{cid}/estrutura")
        self.assertEqual(r.status_code, 400)
        self.assertIn("não foi enviada", r.json()["erro"])

    def test_cargas_velhas_sao_limpas(self):
        from datetime import timedelta
        from django.utils import timezone
        cid = self.post("/api/sinapi/carga/iniciar", dict(base="2026-09", ufs=["SE"], regimes=["sd"], sha256="c" * 64)).json()["cargaId"]
        CargaParte.objects.filter(carga_id=cid).update(criada_em=timezone.now() - timedelta(days=2))
        self.post("/api/sinapi/carga/iniciar", dict(base="2026-09", ufs=["SE"], regimes=["sd"], sha256="d" * 64))
        self.assertFalse(CargaParte.objects.filter(carga_id=cid).exists())
