import json
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import Client, TestCase

from . import services as S
from .models import Composicao, Etapa, Insumo, ItemOrcamento, Material, Medicao, Obra, Pagamento


class Base(TestCase):
    def setUp(self):
        self.ana = User.objects.create_user("ana", password="senha-forte-123", first_name="Ana", last_name="Lima")
        self.beto = User.objects.create_user("beto", password="senha-forte-456")
        # O administrador cria a obra da Ana com os dados de exemplo
        self.obra_ana = Obra.objects.create(dono=self.ana)
        S.carregar_exemplo(self.obra_ana)
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

    def test_obra_liberada_aparece_no_login(self):
        e = self.estado()
        self.assertTrue(e["exemplo"])
        self.assertEqual(len(e["orcamento"]), 9)
        self.assertEqual(e["usuario"]["nome"], "Ana Lima")

    def test_usuario_sem_obra_nao_ganha_obra_automatica(self):
        cb = Client(); cb.force_login(self.beto)
        e = self.estado(cb)
        self.assertTrue(e["semObra"])
        self.assertEqual(e["obras"], [])
        self.assertEqual(Obra.objects.filter(dono=self.beto).count(), 0)
        r = self.post("/api/fornecedores", {"nome": "X"}, client=cb)
        self.assertEqual(r.status_code, 400)
        self.assertIn("Nenhuma obra", r.json()["erro"])
        self.assertEqual(Obra.objects.filter(dono=self.beto).count(), 0)


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
        S.carregar_exemplo(Obra.objects.create(dono=self.beto))
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
        self.ins = S.salvar_insumo(self.obra, self.ana, dict(descricao="Porcelanato", unidade="m²", tipo="material", preco=0))
        self.mat = S.material_do_insumo(self.obra, self.ins)

    def nf(self, qtd, vu, num="1", servico=None):
        it = dict(insumoId=self.ins.pk, qtd=qtd, valorUnit=vu)
        if servico:
            it["orcamentoItemId"] = servico.pk
        return S.lancar_nf(self.obra, dict(fornecedorId=self.forn.pk, numero=num, data="2026-10-01", itens=[it]))

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


class EstoqueNotasTests(Base):
    def setUp(self):
        super().setUp()
        self.obra = S.obter_obra(self.ana)
        S.recomecar(self.obra, "vazio")
        self.serv = S.adicionar_item(self.obra, dict(etapa="Acabamento", servico="Piso", unidade="m²", qtd=100, precoUnit=80))
        self.outro = S.adicionar_item(self.obra, dict(etapa="Acabamento", servico="Pintura", unidade="m²", qtd=100, precoUnit=30))
        self.forn = S.adicionar_fornecedor(self.obra, dict(nome="Loja"))
        self.ins = S.salvar_insumo(self.obra, self.ana, dict(descricao="Argamassa", unidade="sc", tipo="material", preco=0))

    def nf(self, itens, num="1", tipo=None):
        d = dict(fornecedorId=self.forn.pk, numero=num, data="2026-10-01", itens=itens)
        if tipo:
            d["tipo"] = tipo
        return S.lancar_nf(self.obra, d)

    def test_material_nasce_da_primeira_nota_e_e_reaproveitado(self):
        self.assertEqual(self.obra.materiais.count(), 0)
        self.nf([dict(insumoId=self.ins.pk, qtd=10, valorUnit=20)], "1")
        self.nf([dict(insumoId=self.ins.pk, qtd=10, valorUnit=30)], "2")
        mat = self.obra.materiais.get()
        self.assertEqual((mat.insumo_id, mat.saldo, mat.custo_medio), (self.ins.pk, Decimal("20"), Decimal("25")))

    def test_item_sem_insumo_e_recusado(self):
        with self.assertRaises(S.RegraNegocio):
            self.nf([dict(qtd=1, valorUnit=1)])

    def test_nota_ligada_ao_servico_nao_e_gasto(self):
        nota = self.nf([dict(insumoId=self.ins.pk, orcamentoItemId=self.serv.pk, qtd=10, valorUnit=20)])
        self.assertEqual(self.serv.compras.count(), 1)
        self.assertEqual(self.serv.consumos.count(), 0)  # comprado para o serviço, mas ainda nada baixado
        self.assertEqual(nota.pagamento.valor, Decimal("200.00"))
        self.assertEqual(nota.avisos, [f"Argamassa não está previsto no serviço \"Piso\"."])  # serviço avulso, sem composição

    def test_aviso_some_quando_o_insumo_esta_previsto(self):
        comp = Composicao.objects.get(obra=None, codigo="C-0013")
        item = S.adicionar_item(self.obra, dict(etapa="Pisos", composicaoId=comp.pk, qtd=10))
        previsto = item.insumos.first().insumo
        nota = self.nf([dict(insumoId=previsto.pk, orcamentoItemId=item.pk, qtd=1, valorUnit=1)])
        self.assertEqual(nota.avisos, [])

    def test_servico_com_compra_nao_pode_ser_excluido(self):
        self.nf([dict(insumoId=self.ins.pk, orcamentoItemId=self.serv.pk, qtd=1, valorUnit=1)])
        with self.assertRaises(S.RegraNegocio):
            S.excluir_item(self.obra, self.serv.pk)

    def test_documento_que_nao_e_nf_tem_tipo_e_rotulo(self):
        nota = self.nf([dict(insumoId=self.ins.pk, qtd=1, valorUnit=10)], "77", tipo="recibo")
        self.assertEqual((nota.tipo, nota.pagamento.origem), ("recibo", "Recibo 77"))
        with self.assertRaises(S.RegraNegocio):
            self.nf([dict(insumoId=self.ins.pk, qtd=1, valorUnit=10)], "78", tipo="xyz")

    def test_baixa_em_servico_exige_servico(self):
        self.nf([dict(insumoId=self.ins.pk, qtd=10, valorUnit=20)])
        mat = self.obra.materiais.get()
        with self.assertRaises(S.RegraNegocio):
            S.registrar_consumo(self.obra, dict(materialId=mat.pk, qtd=1, data="2026-10-02"))

    def test_baixa_sem_servico_exige_motivo_e_nao_vira_gasto_de_servico(self):
        self.nf([dict(insumoId=self.ins.pk, orcamentoItemId=self.serv.pk, qtd=10, valorUnit=20)])
        mat = self.obra.materiais.get()
        with self.assertRaises(S.RegraNegocio):
            S.registrar_consumo(self.obra, dict(tipo="perda", materialId=mat.pk, qtd=1, data="2026-10-02"))
        c = S.registrar_consumo(self.obra, dict(tipo="quebra", observacao="Caiu do caminhão", materialId=mat.pk, qtd=2, data="2026-10-02"), self.ana)
        mat.refresh_from_db()
        self.assertEqual((c.item_id, c.tipo, c.valor, mat.saldo, c.criado_por_id), (None, "quebra", Decimal("40.00"), Decimal("8"), self.ana.pk))
        self.assertEqual(self.serv.consumos.count(), 0)
        with self.assertRaises(S.RegraNegocio):
            S.registrar_consumo(self.obra, dict(tipo="xyz", observacao="a", materialId=mat.pk, qtd=1, data="2026-10-02"))

    def test_saldo_so_sobe_por_documento(self):
        # não há função nem rota que aumente o saldo sem nota
        self.assertFalse(hasattr(S, "adicionar_material"))
        self.assertFalse(hasattr(S, "ajustar_estoque"))

    def test_estado_traz_tipos_e_vinculos(self):
        self.nf([dict(insumoId=self.ins.pk, orcamentoItemId=self.serv.pk, qtd=10, valorUnit=20)])
        e = self.estado()
        self.assertEqual(e["notasFiscais"][0]["tipo"], "nota_fiscal")
        self.assertEqual(e["notasFiscais"][0]["itens"][0]["orcamentoItemId"], self.serv.pk)
        self.assertIn("quebra", [t["id"] for t in e["tiposBaixa"]])
        self.assertIn("recibo", [t["id"] for t in e["tiposDocumento"]])

    def test_outra_obra_nao_usa_servico_ou_insumo_alheio(self):
        obra_b = Obra.objects.create(nome="Obra do Beto", dono=self.beto)
        forn_b = S.adicionar_fornecedor(obra_b, dict(nome="X"))
        with self.assertRaises(S.RegraNegocio):  # serviço da obra da Ana
            S.lancar_nf(obra_b, dict(fornecedorId=forn_b.pk, numero="1", data="2026-10-01",
                                     itens=[dict(insumoId=Insumo.objects.get(obra=None, codigo="I-0101").pk, orcamentoItemId=self.serv.pk, qtd=1, valorUnit=1)]))
        with self.assertRaises(S.RegraNegocio):  # insumo próprio da obra da Ana
            S.lancar_nf(obra_b, dict(fornecedorId=forn_b.pk, numero="2", data="2026-10-01", itens=[dict(insumoId=self.ins.pk, qtd=1, valorUnit=1)]))


class ApiTests(Base):
    def test_fluxo_completo_pela_api(self):
        e = self.estado()
        porc = Insumo.objects.get(obra=None, codigo="I-0114")
        revest = next(i for i in e["orcamento"] if i["servico"].startswith("Piso porcelanato"))
        forn = e["fornecedores"][2]
        r = self.post("/api/notas", {"fornecedorId": forn["id"], "numero": "NF-9001", "data": "2026-10-20",
                                     "itens": [{"insumoId": porc.pk, "orcamentoItemId": revest["id"], "qtd": 300, "valorUnit": 62}]})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["total"], 18600.0)
        e = r.json()["estado"]
        mat = next(m for m in e["materiais"] if m["insumoId"] == porc.pk)  # nasceu da nota
        self.assertEqual(mat["saldo"], 300.0)
        nota = next(n for n in e["notasFiscais"] if n["numero"] == "NF-9001")
        self.assertEqual(nota["itens"][0]["orcamentoItemId"], revest["id"])
        r = self.post("/api/consumos", {"orcamentoItemId": revest["id"], "materialId": mat["id"], "qtd": 120, "data": "2026-10-21"})
        self.assertEqual(r.json()["valor"], 7440.0)
        e = r.json()["estado"]
        self.assertEqual(next(m for m in e["materiais"] if m["id"] == mat["id"])["saldo"], 180.0)
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
        self.assertTrue(all(p["orcamentoItemId"] in ids for p in e2["pedidos"] if p["tipo"] == "servico"))
        self.assertTrue(any(p["tipo"] == "quebra" and p["orcamentoItemId"] is None for p in e2["pedidos"]))
        compras = [i["orcamentoItemId"] for n in e2["notasFiscais"] for i in n["itens"]]
        self.assertTrue(compras and all(c in ids for c in compras))

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


class ExcluirObraTests(TestCase):
    def test_superusuario_exclui_obra_com_todos_os_dados(self):
        root = User.objects.create_superuser("root", "r@x.com", "senha-forte-789")
        dono = User.objects.create_user("dono", password="senha-forte-222")
        obra = Obra.objects.create(dono=dono, nome="Para apagar")
        S.carregar_exemplo(obra)
        c = Client(); c.force_login(root)
        r = c.get(f"/admin/obras/obra/{obra.pk}/delete/")
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "protected")
        r = c.post(f"/admin/obras/obra/{obra.pk}/delete/", {"post": "yes"})
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Obra.objects.filter(pk=obra.pk).exists())
        self.assertEqual(Material.objects.filter(obra_id=obra.pk).count(), 0)

    def test_dono_nao_fica_como_membro(self):
        root = User.objects.create_superuser("root", "r@x.com", "senha-forte-789")
        dono = User.objects.create_user("dono", password="senha-forte-222")
        c = Client(); c.force_login(root)
        r = c.post("/admin/obras/obra/add/", {"dono": dono.pk, "membros": [dono.pk], "nome": "Nova", "cliente": "",
                                               "prazo": "", "valor_contratado": "0"})
        self.assertEqual(r.status_code, 302, r.content[:500])
        obra = Obra.objects.get(nome="Nova")
        self.assertFalse(obra.membros.filter(pk=dono.pk).exists())
        self.assertEqual(obra.orcamento.count(), 0)  # obra nova começa vazia


class AdminPorObraTests(TestCase):
    def setUp(self):
        self.root = User.objects.create_superuser("root", "r@x.com", "senha-forte-789")
        self.a = Obra.objects.create(dono=self.root, nome="Obra A"); S.carregar_exemplo(self.a)
        self.a.nome = "Obra A"; self.a.save()
        dono_b = User.objects.create_user("b", password="senha-forte-333")
        self.b = Obra.objects.create(dono=dono_b, nome="Obra B"); S.carregar_exemplo(self.b)
        self.b.nome = "Obra B"; self.b.save()
        self.c = Client(); self.c.force_login(self.root)

    def test_lista_mostra_e_filtra_por_obra(self):
        r = self.c.get("/admin/obras/notafiscal/")
        self.assertContains(r, "Obra A ·")
        self.assertContains(r, "Obra B ·")
        r = self.c.get(f"/admin/obras/notafiscal/?obra__id__exact={self.a.pk}")
        self.assertContains(r, "Obra A ·")
        self.assertNotContains(r, "Obra B ·")

    def test_lancamentos_sao_so_consulta(self):
        nf = self.a.notas.first()
        self.assertEqual(self.c.get("/admin/obras/notafiscal/add/").status_code, 403)
        r = self.c.get(f"/admin/obras/notafiscal/{nf.pk}/change/")
        self.assertEqual(r.status_code, 200)  # abre para ver
        r = self.c.post(f"/admin/obras/notafiscal/{nf.pk}/change/", {"numero": "ALTERADA"})
        nf.refresh_from_db()
        self.assertNotEqual(nf.numero, "ALTERADA")
        self.assertEqual(self.c.post(f"/admin/obras/notafiscal/{nf.pk}/delete/", {"post": "yes"}).status_code, 403)

    def test_nao_liga_cadastro_a_outra_obra(self):
        emp_b = self.b.empreiteiros.first()
        item_a = self.a.orcamento.first()
        r = self.c.post("/admin/obras/contrato/add/", {"obra": self.a.pk, "empreiteiro": emp_b.pk, "item": item_a.pk,
                                                       "valor_contratado": "1000", "forma_pagamento": "x"})
        self.assertEqual(r.status_code, 200)  # voltou com erro
        self.assertContains(r, "pertence a outra obra")
        self.assertFalse(self.a.contratos.filter(empreiteiro=emp_b).exists())


class CatalogoTests(Base):
    """Insumo (código único) -> composição -> serviço na etapa, com quantidades previstas."""

    def setUp(self):
        super().setUp()
        self.obra = self.obra_ana
        S.recomecar(self.obra, "vazio")
        self.obra_beto = Obra.objects.create(dono=self.beto)
        self.cb = Client(); self.cb.force_login(self.beto)

    def test_biblioteca_inicial_carregada(self):
        comps = Composicao.objects.filter(obra=None)
        self.assertGreaterEqual(comps.count(), 20)
        self.assertTrue(all(c.itens.exists() and c.referencia for c in comps))
        self.assertTrue(Insumo.objects.filter(obra=None, codigo="I-0101").exists())

    def test_servico_por_composicao_congela_preco_e_preve_insumos(self):
        comp = Composicao.objects.get(obra=None, codigo="C-0009")
        esperado = sum(i.coeficiente * i.insumo.preco for i in comp.itens.all())
        item = S.adicionar_item(self.obra, dict(etapa="Alvenaria", composicaoId=comp.pk, qtd=480))
        self.assertEqual(item.unidade, "m²")
        self.assertEqual(item.preco_unitario, esperado.quantize(Decimal("0.0001")))
        self.assertEqual(item.codigo, "C-0009")
        bloco = item.insumos.get(insumo__codigo="I-0106")
        self.assertEqual(item.quantidade * bloco.coeficiente, Decimal("6480"))
        # Mudar o preço do insumo depois NÃO altera o orçado...
        Insumo.objects.filter(codigo="I-0106", obra=None).update(preco=Decimal("10"))
        item.refresh_from_db()
        self.assertEqual(item.preco_unitario, esperado.quantize(Decimal("0.0001")))
        # ...até pedir para atualizar pela composição
        S.atualizar_pela_composicao(self.obra, item.pk)
        item.refresh_from_db()
        self.assertGreater(item.preco_unitario, esperado)

    def test_servico_por_verba_continua_possivel(self):
        item = S.adicionar_item(self.obra, dict(etapa="Serviços preliminares", servico="Alvará", unidade="vb", qtd=1, precoUnit=2500))
        self.assertFalse(item.insumos.exists())
        self.assertEqual(item.planejado, Decimal("2500"))

    def test_etapas_padrao_e_nova(self):
        e = self.estado()
        self.assertIn("Fundação", e["etapasPadrao"])
        r = self.post("/api/etapas", {"nome": "Paisagismo"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.post("/api/etapas", {"nome": "paisagismo"}).status_code, 400)
        S.adicionar_item(self.obra, dict(etapa="Fundação", servico="X", unidade="un", qtd=1, precoUnit=1))
        nomes = [x["nome"] for x in self.estado()["etapas"]]
        self.assertEqual(nomes, ["Fundação", "Paisagismo"])  # padrão primeiro, na ordem da obra
        fund = Etapa.objects.get(obra=self.obra, nome="Fundação")
        self.assertEqual(self.c.delete(f"/api/etapas/{fund.pk}").status_code, 400)  # tem serviço

    def test_usuario_comum_nao_altera_base_mas_cadastra_na_obra(self):
        r = self.post("/api/insumos", {"escopo": "base", "descricao": "Telha", "unidade": "un"})
        self.assertEqual(r.status_code, 400)
        base = Insumo.objects.get(obra=None, codigo="I-0101")
        self.assertEqual(self.post(f"/api/insumos/{base.pk}", {"descricao": "X", "unidade": "un"}).status_code, 400)
        r = self.post("/api/insumos", {"descricao": "Telha colonial", "unidade": "un", "tipo": "material", "preco": "2,10"})
        self.assertEqual(r.status_code, 200, r.content)
        ins = Insumo.objects.get(pk=r.json()["id"])
        self.assertEqual((ins.obra_id, ins.codigo, ins.preco), (self.obra.pk, "IP-0001", Decimal("2.1")))
        self.assertEqual(self.post("/api/insumos", {"codigo": "ip-0001", "descricao": "Outra", "unidade": "un"}).status_code, 400)
        # Beto não enxerga o insumo da obra da Ana
        self.assertNotIn(ins.pk, [i["id"] for i in self.estado(self.cb)["insumos"]])
        self.assertEqual(self.post(f"/api/insumos/{ins.pk}", {"descricao": "Hack", "unidade": "un"}, client=self.cb).status_code, 400)

    def test_grupo_base_geral_libera_editar_base(self):
        from django.contrib.auth.models import Group
        self.ana.groups.add(Group.objects.get(name="Base geral de insumos e composições"))
        r = self.post("/api/insumos", {"escopo": "base", "descricao": "Telha", "unidade": "un"})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIsNone(Insumo.objects.get(pk=r.json()["id"]).obra_id)

    def test_composicao_valida_insumos_e_duplica_para_obra(self):
        meu = S.salvar_insumo(self.obra, self.ana, {"descricao": "Bloco especial", "unidade": "un"})
        cimento = Insumo.objects.get(obra=None, codigo="I-0101")
        r = self.post("/api/composicoes", {"descricao": "Muro", "unidade": "m²", "itens": [{"insumoId": meu.pk, "coef": 12}, {"insumoId": cimento.pk, "coef": "0,1"}]})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(Composicao.objects.get(pk=r.json()["id"]).codigo, "CP-0001")
        self.assertEqual(self.post("/api/composicoes", {"descricao": "Vazia", "unidade": "m²", "itens": []}).status_code, 400)
        self.assertEqual(self.post("/api/composicoes", {"descricao": "Rep", "unidade": "m²", "itens": [{"insumoId": cimento.pk, "coef": 1}, {"insumoId": cimento.pk, "coef": 2}]}).status_code, 400)
        base = Composicao.objects.get(obra=None, codigo="C-0008")
        r = self.post(f"/api/composicoes/{base.pk}/duplicar")
        copia = Composicao.objects.get(pk=r.json()["id"])
        self.assertEqual((copia.obra_id, copia.itens.count()), (self.obra.pk, base.itens.count()))
        # Base geral não pode usar insumo de uma obra
        with self.assertRaises(S.RegraNegocio):
            S._itens_composicao(base, self.obra, [{"insumoId": meu.pk, "coef": 1}])
        # Insumo em uso não pode ser excluído
        self.assertEqual(self.c.delete(f"/api/insumos/{meu.pk}").status_code, 400)

    def test_importar_insumos_e_composicoes_tudo_ou_nada(self):
        linhas = [{"codigo": "M-1", "descricao": "Bloco 1", "unidade": "un", "tipo": "Material", "preco": "3,5"},
                  {"codigo": "M-2", "descricao": "Ajudante", "unidade": "h", "tipo": "mão de obra", "preco": 19}]
        r = self.post("/api/catalogo/importar", {"tipo": "insumos", "escopo": "obra", "linhas": linhas})
        self.assertEqual(r.json()["criados"], 2)
        r = self.post("/api/catalogo/importar", {"tipo": "insumos", "escopo": "obra", "linhas": linhas[:1] + [{"codigo": "M-3", "descricao": "", "unidade": "un"}]})
        self.assertEqual(r.status_code, 400)
        self.assertIn("Linha 3", r.json()["erro"])
        self.assertFalse(Insumo.objects.filter(codigo="M-3").exists())
        comp = [{"codigocomposicao": "S-1", "descricaocomposicao": "Muro", "unidadecomposicao": "m²", "codigoinsumo": "M-1", "coeficiente": 12},
                {"codigocomposicao": "S-1", "codigoinsumo": "M-2", "coeficiente": "0,8"},
                {"codigocomposicao": "S-1", "codigoinsumo": "I-0101", "coeficiente": "0,1"}]
        r = self.post("/api/catalogo/importar", {"tipo": "composicoes", "escopo": "obra", "linhas": comp})
        self.assertEqual(r.status_code, 200, r.content)
        c = Composicao.objects.get(obra=self.obra, codigo="S-1")
        self.assertEqual(c.custo_unitario, Decimal("12") * Decimal("3.5") + Decimal("0.8") * 19 + Decimal("0.1") * 34)
        r = self.post("/api/catalogo/importar", {"tipo": "composicoes", "escopo": "obra", "linhas": [{"codigocomposicao": "S-2", "descricaocomposicao": "X", "unidadecomposicao": "m", "codigoinsumo": "NAO-EXISTE", "coeficiente": 1}]})
        self.assertIn("NAO-EXISTE", r.json()["erro"])

    def test_importar_orcamento(self):
        linhas = [{"etapa": "Alvenaria", "codigocomposicao": "C-0008", "quantidade": 100},
                  {"etapa": "Serviços preliminares", "servico": "Projeto", "unidade": "vb", "quantidade": 1, "precounitario": 3000}]
        r = self.post("/api/orcamento/importar", {"linhas": linhas})
        self.assertEqual(r.status_code, 200, r.content)
        e = r.json()["estado"]
        self.assertEqual(len(e["orcamento"]), 2)
        self.assertEqual([i["etapa"] for i in e["orcamento"]], ["Serviços preliminares", "Alvenaria"])
        self.assertEqual(len(next(i for i in e["orcamento"] if i["codigo"] == "C-0008")["insumos"]), 6)
        r = self.post("/api/orcamento/importar", {"linhas": [{"etapa": "Pisos", "codigocomposicao": "C-9999", "quantidade": 1}]})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(ItemOrcamento.objects.filter(obra=self.obra).count(), 2)

    def test_estoque_nao_aceita_entrada_manual(self):
        cimento = Insumo.objects.get(obra=None, codigo="I-0101")
        r = self.post("/api/materiais", {"insumoId": cimento.pk})
        self.assertEqual(r.status_code, 400)
        self.assertIn("nota fiscal", r.json()["erro"])

    def test_editar_quantidade_do_servico(self):
        comp = Composicao.objects.get(obra=None, codigo="C-0013")
        item = S.adicionar_item(self.obra, dict(etapa="Pisos", composicaoId=comp.pk, qtd=10))
        r = self.post(f"/api/orcamento/{item.pk}", {"qtd": 25, "precoUnit": 1})
        self.assertEqual(r.status_code, 200)
        item.refresh_from_db()
        self.assertEqual(item.quantidade, Decimal("25"))
        self.assertNotEqual(item.preco_unitario, Decimal("1"))  # preço de composição não é digitado

    def test_excluir_obra_com_cadastro_proprio(self):
        S.carregar_exemplo(self.obra)
        ins = S.salvar_insumo(self.obra, self.ana, {"descricao": "Só meu", "unidade": "un"})
        S.salvar_composicao(self.obra, self.ana, {"descricao": "Meu", "unidade": "un", "itens": [{"insumoId": ins.pk, "coef": 1}]})
        S.excluir_obra(self.obra)
        self.assertFalse(Insumo.objects.filter(pk=ins.pk).exists())
        self.assertTrue(Insumo.objects.filter(obra=None).exists())
