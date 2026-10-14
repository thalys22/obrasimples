import json
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import Client, TestCase

from . import services as S
from .models import Material, Medicao, Obra, Pagamento


class Base(TestCase):
    def setUp(self):
        self.ana = User.objects.create_user("ana", password="senha-forte-123", first_name="Ana", last_name="Lima")
        self.beto = User.objects.create_user("beto", password="senha-forte-456")
        self.c = Client()
        self.c.force_login(self.ana)

    def post(self, url, corpo=None, client=None):
        return (client or self.c).post(url, json.dumps(corpo or {}), content_type="application/json")

    def estado(self, client=None):
        r = (client or self.c).get("/api/estado")
        self.assertEqual(r.status_code, 200)
        return r.json()["estado"]


class AcessoTests(Base):
    def test_sem_login_api_responde_401_e_app_manda_para_login(self):
        anon = Client()
        self.assertEqual(anon.get("/api/estado").status_code, 401)
        r = anon.get("/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/conta/login/", r["Location"])

    def test_login_pela_tela(self):
        anon = Client()
        r = anon.post("/conta/login/", {"username": "ana", "password": "senha-forte-123"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(anon.get("/").status_code, 200)

    def test_usuario_bloqueado_nao_entra(self):
        self.beto.is_active = False
        self.beto.save()
        anon = Client()
        r = anon.post("/conta/login/", {"username": "beto", "password": "senha-forte-456"})
        self.assertEqual(r.status_code, 200)  # volta para a tela com erro
        self.assertEqual(anon.get("/api/estado").status_code, 401)

    def test_csrf_obrigatorio(self):
        c = Client(enforce_csrf_checks=True)
        c.force_login(self.ana)
        r = c.post("/api/fornecedores", json.dumps({"nome": "X"}), content_type="application/json")
        self.assertEqual(r.status_code, 403)

    def test_primeiro_acesso_cria_obra_de_exemplo(self):
        e = self.estado()
        self.assertTrue(e["exemplo"])
        self.assertEqual(len(e["orcamento"]), 8)
        self.assertEqual(e["usuario"]["nome"], "Ana Lima")
        self.assertEqual(Obra.objects.filter(dono=self.ana).count(), 1)


class IsolamentoTests(Base):
    def test_cada_usuario_ve_so_a_propria_obra(self):
        self.post("/api/fornecedores", {"nome": "Só da Ana"})
        cb = Client(); cb.force_login(self.beto)
        nomes_beto = [f["nome"] for f in self.estado(cb)["fornecedores"]]
        self.assertNotIn("Só da Ana", nomes_beto)

    def test_nao_aprova_medicao_de_outro_usuario(self):
        self.estado()
        med_ana = Medicao.objects.get(obra__dono=self.ana, status="pendente")
        cb = Client(); cb.force_login(self.beto)
        r = self.post(f"/api/medicoes/{med_ana.pk}/aprovar", client=cb)
        self.assertEqual(r.status_code, 400)
        med_ana.refresh_from_db()
        self.assertEqual(med_ana.status, "pendente")

    def test_nao_usa_material_de_outro_usuario(self):
        self.estado()
        cb = Client(); cb.force_login(self.beto)
        e_beto = self.estado(cb)
        mat_ana = Material.objects.filter(obra__dono=self.ana).first()
        r = self.post("/api/consumos", {"orcamentoItemId": e_beto["orcamento"][0]["id"], "materialId": mat_ana.pk, "qtd": 1, "data": "2026-10-01"}, client=cb)
        self.assertEqual(r.status_code, 400)


class RegrasTests(Base):
    def setUp(self):
        super().setUp()
        self.obra = S.obter_obra(self.ana)
        S.recomecar(self.obra, "vazio")
        self.item = S.adicionar_item(self.obra, dict(etapa="Acabamento", servico="Piso", unidade="m²", qtd=100, precoUnit=80))
        self.forn = S.adicionar_fornecedor(self.obra, dict(nome="Loja"))
        self.mat = S.adicionar_material(self.obra, dict(nome="Porcelanato", unidade="m²"))

    def nf(self, qtd, vu, num="1"):
        return S.lancar_nf(self.obra, dict(fornecedorId=self.forn.pk, numero=num, data="2026-10-01", itens=[dict(materialId=self.mat.pk, qtd=qtd, valorUnit=vu)]))

    def test_custo_medio_ponderado_e_pagamento_da_nota(self):
        self.nf(100, 30, "1")
        nota = self.nf(100, 34, "2")
        self.mat.refresh_from_db()
        self.assertEqual(self.mat.saldo, Decimal("200"))
        self.assertEqual(self.mat.custo_medio, Decimal("32"))
        self.assertEqual(nota.pagamento.valor, Decimal("3400.00"))
        self.assertEqual(nota.pagamento.origem, "NF 2")

    def test_consumo_baixa_estoque_e_vira_realizado(self):
        self.nf(300, 62)
        c = S.registrar_consumo(self.obra, dict(orcamentoItemId=self.item.pk, materialId=self.mat.pk, qtd=120, data="2026-10-02"))
        self.mat.refresh_from_db()
        self.assertEqual(self.mat.saldo, Decimal("180"))
        self.assertEqual(c.valor, Decimal("7440.00"))

    def test_consumo_maior_que_estoque_exige_confirmacao(self):
        self.nf(50, 10)
        with self.assertRaises(S.RegraNegocio):
            S.registrar_consumo(self.obra, dict(orcamentoItemId=self.item.pk, materialId=self.mat.pk, qtd=80, data="2026-10-02"))
        c = S.registrar_consumo(self.obra, dict(orcamentoItemId=self.item.pk, materialId=self.mat.pk, qtd=80, data="2026-10-02", aceitarParcial=True))
        self.assertEqual(c.quantidade, Decimal("50"))
        with self.assertRaises(S.RegraNegocio):  # agora sem saldo
            S.registrar_consumo(self.obra, dict(orcamentoItemId=self.item.pk, materialId=self.mat.pk, qtd=1, data="2026-10-02", aceitarParcial=True))

    def test_medicao_nao_passa_de_100_e_aprovacao_gera_pagamento(self):
        emp = S.adicionar_empreiteiro(self.obra, dict(nome="Equipe"))
        ctr = S.criar_contrato(self.obra, dict(empreiteiroId=emp.pk, orcamentoItemId=self.item.pk, valorContratado=10000))
        m = S.registrar_medicao(self.obra, dict(contratoId=ctr.pk, data="2026-10-01", percentual=60))
        with self.assertRaises(S.RegraNegocio):
            S.registrar_medicao(self.obra, dict(contratoId=ctr.pk, data="2026-10-02", percentual=41))
        pag = S.aprovar_medicao(self.obra, m.pk, self.ana)
        self.assertEqual(pag.valor, Decimal("6000.00"))
        self.assertEqual(pag.item_id, self.item.pk)
        with self.assertRaises(S.RegraNegocio):
            S.aprovar_medicao(self.obra, m.pk, self.ana)

    def test_nao_exclui_servico_com_gasto(self):
        S.pagamento_avulso(self.obra, dict(descricao="Taxa", orcamentoItemId=self.item.pk, valor=100, data="2026-10-01"))
        with self.assertRaises(S.RegraNegocio):
            S.excluir_item(self.obra, self.item.pk)

    def test_validacoes_basicas(self):
        with self.assertRaises(S.RegraNegocio):
            S.adicionar_item(self.obra, dict(etapa="X", servico="Y", unidade="un", qtd=0, precoUnit=10))
        with self.assertRaises(S.RegraNegocio):
            S.lancar_nf(self.obra, dict(fornecedorId=self.forn.pk, numero="9", data="2026-10-01", itens=[]))


class ApiTests(Base):
    def test_fluxo_completo_pela_api(self):
        e = self.estado()
        porcelanato = next(m for m in e["materiais"] if m["nome"].startswith("Porcelanato"))
        revest = next(i for i in e["orcamento"] if i["servico"] == "Revestimento cerâmico")
        forn = e["fornecedores"][2]
        r = self.post("/api/notas", {"fornecedorId": forn["id"], "numero": "NF-9001", "data": "2026-10-20", "itens": [{"materialId": porcelanato["id"], "qtd": 300, "valorUnit": 62}]})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["total"], 18600.0)
        r = self.post("/api/consumos", {"orcamentoItemId": revest["id"], "materialId": porcelanato["id"], "qtd": 120, "data": "2026-10-21"})
        self.assertEqual(r.json()["valor"], 7440.0)
        e = r.json()["estado"]
        self.assertEqual(next(m for m in e["materiais"] if m["id"] == porcelanato["id"])["saldo"], 180.0)
        pend = next(p for p in e["pagamentos"] if p["origem"] == "NF-9001")
        r = self.post(f"/api/pagamentos/{pend['id']}/pagar")
        self.assertEqual(next(p for p in r.json()["estado"]["pagamentos"] if p["id"] == pend["id"])["status"], "pago")

    def test_erro_de_regra_volta_mensagem(self):
        e = self.estado()
        ctr = e["contratos"][0]  # já tem 40% medido
        r = self.post("/api/medicoes", {"contratoId": ctr["id"], "data": "2026-10-01", "percentual": 70})
        self.assertEqual(r.status_code, 400)
        self.assertIn("máximo", r.json()["erro"])

    def test_importar_estado_exportado_mantem_vinculos(self):
        e = self.estado()
        r = self.post("/api/importar", {"estado": e})
        self.assertEqual(r.status_code, 200, r.content)
        e2 = r.json()["estado"]
        for k in ("orcamento", "materiais", "notasFiscais", "pedidos", "contratos", "medicoes", "pagamentos"):
            self.assertEqual(len(e2[k]), len(e[k]), k)
        self.assertEqual(sum(p["valor"] for p in e2["pedidos"]), sum(p["valor"] for p in e["pedidos"]))
        ids = {i["id"] for i in e2["orcamento"]}
        self.assertTrue(all(p["orcamentoItemId"] in ids for p in e2["pedidos"]))

    def test_recomecar_em_branco(self):
        r = self.post("/api/recomecar", {"tipo": "vazio"})
        e = r.json()["estado"]
        self.assertEqual(e["orcamento"], [])
        self.assertFalse(e["exemplo"])
        self.assertEqual(Pagamento.objects.filter(obra__dono=self.ana).count(), 0)


class CompartilhamentoTests(Base):
    def test_obra_criada_pelo_admin_e_usada_no_primeiro_acesso(self):
        obra = Obra.objects.create(dono=self.beto, nome="Casa Atalaia")
        cb = Client(); cb.force_login(self.beto)
        e = self.estado(cb)
        self.assertEqual(e["obra"]["nome"], "Casa Atalaia")
        self.assertEqual(e["obraId"], obra.pk)
        self.assertEqual(Obra.objects.filter(dono=self.beto).count(), 1)  # não criou obra de exemplo extra

    def test_membro_ve_troca_e_lanca_mas_nao_apaga_tudo(self):
        e_ana = self.estado()
        obra_ana = Obra.objects.get(pk=e_ana["obraId"])
        obra_ana.membros.add(self.beto)
        cb = Client(); cb.force_login(self.beto)
        S.obter_obra(self.beto)  # beto ganha a obra dele também
        obra_beto = Obra.objects.create(dono=self.beto, nome="Obra do Beto")
        e = self.estado(cb)
        self.assertEqual(len(e["obras"]), 2)
        r = self.post("/api/obra/selecionar", {"obraId": obra_ana.pk}, client=cb)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["estado"]["obraId"], obra_ana.pk)
        self.assertFalse(r.json()["estado"]["souDono"])
        r = self.post("/api/fornecedores", {"nome": "Fornecedor do Beto na obra da Ana"}, client=cb)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(obra_ana.fornecedores.filter(nome__contains="Beto").exists())
        r = self.post("/api/recomecar", {"tipo": "vazio"}, client=cb)
        self.assertEqual(r.status_code, 400)
        self.assertTrue(obra_ana.orcamento.exists())
        r = self.post("/api/importar", {"estado": e}, client=cb)
        self.assertEqual(r.status_code, 400)

    def test_nao_seleciona_obra_sem_acesso(self):
        e_ana = self.estado()
        cb = Client(); cb.force_login(self.beto)
        self.estado(cb)
        r = self.post("/api/obra/selecionar", {"obraId": e_ana["obraId"]}, client=cb)
        self.assertEqual(r.status_code, 400)

    def test_removido_da_obra_perde_acesso(self):
        e_ana = self.estado()
        obra_ana = Obra.objects.get(pk=e_ana["obraId"])
        obra_ana.membros.add(self.beto)
        cb = Client(); cb.force_login(self.beto)
        self.post("/api/obra/selecionar", {"obraId": obra_ana.pk}, client=cb)
        obra_ana.membros.remove(self.beto)
        e = self.estado(cb)
        self.assertNotEqual(e["obraId"], obra_ana.pk)


class AdminPermissoesTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import Group
        self.root = User.objects.create_superuser("root", "r@x.com", "senha-forte-789")
        self.gestor = User.objects.create_user("gestor", password="senha-forte-000", is_staff=True)
        self.gestor.groups.add(Group.objects.get(name="Gestão de usuários e obras"))
        self.comum = User.objects.create_user("comum", password="senha-forte-111")

    def test_grupos_prontos_existem(self):
        from django.contrib.auth.models import Group
        consulta = Group.objects.get(name="Consulta (somente leitura)")
        self.assertTrue(consulta.permissions.exists())
        self.assertFalse(consulta.permissions.exclude(codename__startswith="view_").exists())

    def test_superusuario_ve_telas_com_explicacao(self):
        c = Client(); c.force_login(self.root)
        r = c.get(f"/admin/auth/user/{self.comum.pk}/change/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Membro da equipe")
        self.assertContains(r, "Consulta (somente leitura)")
        obra = Obra.objects.create(dono=self.comum, nome="X")
        self.assertEqual(c.get(f"/admin/obras/obra/{obra.pk}/change/").status_code, 200)
        self.assertEqual(c.get("/admin/obras/obra/add/").status_code, 200)

    def test_gestor_nao_altera_superusuario_nem_se_promove(self):
        c = Client(); c.force_login(self.gestor)
        self.assertEqual(c.get(f"/admin/auth/user/{self.comum.pk}/change/").status_code, 200)
        r = c.get(f"/admin/auth/user/{self.root.pk}/password/")
        self.assertIn(r.status_code, (403, 302))
        r = c.post(f"/admin/auth/user/{self.gestor.pk}/change/", {
            "username": "gestor", "is_active": "on", "is_superuser": "on", "is_staff": "on",
            "date_joined_0": "2026-10-14", "date_joined_1": "10:00:00",
        })
        self.gestor.refresh_from_db()
        self.assertFalse(self.gestor.is_superuser)
