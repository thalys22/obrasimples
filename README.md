# Prumo · controle de obra (Django)

> Antes chamado ObraSimples. Endereço: **https://prumoobras.vercel.app** (o antigo, obrasimples.vercel.app, continua funcionando). O repositório no GitHub ainda se chama `obrasimples`.

Controle de obra para pequenas construtoras, agora com **login, banco de dados e painel de administração**.

- Cada usuário entra com usuário e senha e tem **a própria obra**. Um usuário não vê a obra de outro.
- Você (administrador) cria, bloqueia e troca a senha dos usuários, e vê os dados de todas as obras em `/admin`.
- As regras de negócio (custo médio, baixa de estoque, limite de 100% nas medições, pagamentos automáticos) rodam no servidor. Ninguém consegue burlar pelo navegador.
- **Quem cria e libera obras é o administrador.** Ninguém ganha obra automaticamente: um usuário sem obra liberada vê só um aviso ao entrar. Para dar uma obra de exemplo a alguém, crie a obra e use a ação *Apagar dados e carregar o exemplo*.

---

## 1. Rodar no seu computador (para conhecer)

Precisa do Python 3.10 ou mais novo instalado ([python.org](https://www.python.org/downloads/)).

No Windows, abra o **Prompt de Comando** dentro da pasta `obrasimples_web` e rode:

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
set DJANGO_DEBUG=1
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

No Mac/Linux troque as linhas 2 e 4 por `source .venv/bin/activate` e `export DJANGO_DEBUG=1`.

Abra http://127.0.0.1:8000 e entre com o usuário que você criou no `createsuperuser`.

> `DJANGO_DEBUG=1` é só para o seu computador. Nunca use em produção.

---

## 2. Controlar usuários

Entre em **/admin** (ou pelo seu avatar no canto superior direito → *Administração*).

| Para… | Faça |
|---|---|
| Criar um testador | *Usuários → Adicionar usuário*. Defina usuário e senha. Depois preencha nome e sobrenome (aparecem no app) e vincule uma obra a ele (linha abaixo). |
| Bloquear o acesso | Abra o usuário e desmarque **Ativo**. Ele não consegue mais entrar e os dados dele ficam guardados. |
| Trocar a senha de alguém | Abra o usuário → link *"este formulário"* no campo Senha. |
| Dar acesso ao /admin para outra pessoa | Marque **Membro da equipe** (vê o admin) e, se quiser, **Superusuário** (pode tudo). |
| Vincular uma obra a alguém | *Obras* → abra a obra → escolha o **Dono** ou adicione a pessoa em **Outros usuários com acesso**. Para uma obra nova, *Adicionar obra*, escolha o dono e salve (ela começa vazia). Para excluir uma obra e todos os lançamentos dela, marque-a na lista e use a ação *Excluir*. |
| Entender cada permissão | Abra o usuário: a seção *Acesso ao painel de administração* explica Membro da equipe, Superusuário, Grupos e Permissões. |
| Ver a obra de um testador | *Obras* lista todas, com dono e total orçado. Notas, consumos, medições e pagamentos têm filtro **por usuário** na lateral. |
| Zerar ou recarregar o exemplo de uma obra | Em *Obras*, marque a obra, escolha a ação no menu *Ação* e clique *Ir*. |

O próprio usuário troca a senha dele pelo avatar → *Trocar senha*. Não há cadastro aberto: só entra quem você criar.

---

## 2.1. Orçamento: insumos, composições e etapas

O orçamento é montado em cadeia, e cada elo é um cadastro com código único:

1. **Insumo** (aba *Cadastros*): material, mão de obra, equipamento ou empreitada, com código, unidade e preço de referência.
2. **Composição de serviço**: quanto de cada insumo vai em 1 unidade do serviço (coeficiente). O custo sai da soma dos insumos.
3. **Serviço na etapa** (aba *Orçamento*): escolha a etapa, a composição e a quantidade. O sistema calcula o preço e a quantidade prevista de cada insumo.

Regras:

- **Base geral × obra.** Insumos e composições sem obra formam a *base geral* (todas as obras usam). Só o superusuário ou quem estiver no grupo **Base geral de insumos e composições** altera a base geral. Os demais cadastram itens só da obra deles, ou duplicam uma composição da base para a obra e ajustam.
- **Biblioteca inicial.** O sistema já vem com 38 insumos e 21 composições comuns (migração `0004`). Os coeficientes e preços são **aproximados**: confira e ajuste antes de usar em orçamento real.
- **Preço congelado.** Ao entrar no orçamento, o serviço guarda uma cópia dos insumos e preços daquele dia. Mudar o preço de um insumo depois não altera o orçado, a não ser que você use *atualizar pela composição* no serviço.
- **Por verba.** Serviços sem composição (taxa, projeto, empreitada global) entram só com o valor.
- **Etapas.** Escolhidas da lista padrão ou criadas pelo botão *Nova etapa*. Não há etapa em texto livre, o que evita duplicatas como "Terraplanagem" e "Terraplenagem".
- **Estoque ligado ao insumo, em três telas.** *Saldo de estoque* (consulta), *Notas fiscais* (lançar e consultar) e *Baixa de estoque*. O saldo só sobe com nota fiscal ou outro documento de entrada (recibo, fatura); não existe entrada manual, e o material nasce sozinho na primeira nota que usa o insumo. Cada item da nota pode apontar para o serviço do orçamento para o qual foi comprado ("comprado para"). O **gasto** do serviço é só a baixa de estoque, a custo médio; comprado e gasto aparecem lado a lado e nunca se somam. Perdas, quebras, ajustes e devoluções são baixas sem serviço, exigem motivo e não entram no gasto de nenhum serviço.
- **Importação.** Insumos e composições se atualizam pelo código (tudo ou nada: se uma linha tiver erro, nada é gravado). A importação de orçamento acrescenta serviços sem apagar os que já existem.

## 3. Colocar no ar na Vercel (recomendado)

O site atualiza sozinho a cada envio ao GitHub. O banco é PostgreSQL (Neon), porque na Vercel arquivos gravados não ficam guardados e o SQLite perderia os dados.

1. Em https://vercel.com/new, importe o repositório **thalys22/obrasimples**. A Vercel reconhece o Django sozinha.
2. **Antes de clicar Deploy**, abra *Environment Variables* e crie:

   | Nome | Valor |
   |---|---|
   | `DJANGO_SECRET_KEY` | uma frase longa e aleatória (50+ caracteres) |
   | `DJANGO_SUPERUSER_USERNAME` | seu usuário de administrador, ex.: `thalys` |
   | `DJANGO_SUPERUSER_EMAIL` | seu e-mail |
   | `DJANGO_SUPERUSER_PASSWORD` | a senha do administrador (só você digita) |

3. Clique **Deploy**. A primeira publicação **vai falhar** com a mensagem "Na Vercel é preciso um banco PostgreSQL". É esperado.
4. No projeto, aba **Storage** → **Create Database** → **Neon** (Postgres) → plano gratuito → conecte ao projeto. Ele cria a variável `DATABASE_URL`.
5. Aba **Deployments** → no último → **⋯ → Redeploy**. Agora a publicação cria as tabelas e o seu administrador.
6. Abra o endereço `.vercel.app` do projeto e entre com o usuário e a senha do passo 2.

Depois de entrar, você pode apagar a variável `DJANGO_SUPERUSER_PASSWORD` da Vercel. O usuário já foi criado e a senha fica guardada (criptografada) no banco.

**Atualizar depois**: qualquer envio para a branch `main` do GitHub publica sozinho. Mudanças no banco (migrações) são aplicadas na publicação.

**Backup**: o Neon tem restauração e cópias no painel dele. Também dá para exportar a obra em Excel pelo próprio app.

## 4. Alternativa: PythonAnywhere

O PythonAnywhere tem plano gratuito que roda Django e guarda o banco SQLite. É suficiente para a fase de testes. Confira no site as regras atuais do plano gratuito (por exemplo, renovações periódicas do site pelo painel).

1. Crie uma conta em https://www.pythonanywhere.com (plano *Beginner*). Seu endereço será `SEUUSUARIO.pythonanywhere.com`.
2. Aba **Consoles** → *Bash*. Baixe o código do GitHub (o repositório é privado, então o GitHub pede usuário e um *token* no lugar da senha: crie em GitHub → Settings → Developer settings → Personal access tokens, com permissão de leitura do repositório):
   ```
   git clone https://github.com/thalys22/obrasimples.git obrasimples_web
   ```
3. Ainda no console, rode, trocando `SEUUSUARIO`:
   ```
   cd obrasimples_web
   mkvirtualenv --python=python3.10 obrasimples
   pip install -r requirements.txt
   python -c "import secrets; print(secrets.token_urlsafe(50))"
   ```
   **Copie a chave** que aparecer (é a sua `DJANGO_SECRET_KEY`). Depois:
   ```
   export DJANGO_SECRET_KEY='cole-a-chave-aqui'
   export DJANGO_ALLOWED_HOSTS='SEUUSUARIO.pythonanywhere.com'
   python manage.py migrate
   python manage.py collectstatic --noinput
   python manage.py createsuperuser
   ```
4. Aba **Web** → *Add a new web app* → *Manual configuration* → *Python 3.10*.
5. Ainda na aba Web:
   - **Virtualenv**: `/home/SEUUSUARIO/.virtualenvs/obrasimples`
   - **Static files**: URL `/static/` → Directory `/home/SEUUSUARIO/obrasimples_web/staticfiles`
   - **Force HTTPS**: ligado
6. Clique no link do **WSGI configuration file**, apague tudo e cole:
   ```python
   import os, sys
   path = '/home/SEUUSUARIO/obrasimples_web'
   if path not in sys.path:
       sys.path.insert(0, path)
   os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
   os.environ['DJANGO_SECRET_KEY'] = 'cole-a-mesma-chave-aqui'
   os.environ['DJANGO_ALLOWED_HOSTS'] = 'SEUUSUARIO.pythonanywhere.com'
   os.environ['DJANGO_CSRF_TRUSTED'] = 'https://SEUUSUARIO.pythonanywhere.com'
   from django.core.wsgi import get_wsgi_application
   application = get_wsgi_application()
   ```
7. Volte na aba Web e clique **Reload**. Acesse `https://SEUUSUARIO.pythonanywhere.com`.

**Atualizar depois**: no console, `cd obrasimples_web && git pull`, depois rode `python manage.py migrate` e `python manage.py collectstatic --noinput` no console (com os `export` do passo 3) e clique **Reload**.

**Backup**: o banco é o arquivo `db.sqlite3`. Baixe uma cópia pela aba Files de vez em quando.

### Outros servidores

Funciona em qualquer hospedagem Python (Render, Railway, uma VPS). Comando de início: `gunicorn config.wsgi`. Para usar PostgreSQL, defina `DATABASE_URL`.

---

## 5. Variáveis de ambiente

| Variável | Para quê |
|---|---|
| `DJANGO_SECRET_KEY` | Obrigatória em produção. Chave longa e secreta. |
| `DJANGO_DEBUG` | `1` só no seu computador. Em produção, deixe sem definir. |
| `DJANGO_ALLOWED_HOSTS` | Domínio do site, ex.: `seuusuario.pythonanywhere.com` |
| `DJANGO_CSRF_TRUSTED` | Mesmo domínio com `https://` na frente |
| `DATABASE_URL` | Endereço do PostgreSQL. Na Vercel é obrigatória (o Neon preenche). Sem ela, fora da Vercel, usa SQLite. |
| `DJANGO_SUPERUSER_USERNAME` / `_EMAIL` / `_PASSWORD` | Criam o administrador na primeira publicação (`build.py`). |
| `DJANGO_SSL_REDIRECT` | `1` se o servidor não forçar HTTPS sozinho |

---

## 6. Estrutura

```
config/            configurações do Django
obras/models.py    tabelas: obra, etapas, insumos, composições, orçamento, materiais, notas, consumos, contratos, medições, pagamentos
obras/biblioteca.py  insumos e composições da biblioteca inicial (valores aproximados)
obras/services.py  regras de negócio (tudo que altera dados passa por aqui)
obras/views.py     API JSON usada pelo app (/api/...)
obras/admin.py     painel de administração
obras/tests.py     testes automáticos (python manage.py test obras)
build.py           roda a cada publicação na Vercel: migrações e administrador
pyproject.toml     dependências e configuração da Vercel
frontend/app.html  o aplicativo (página única)
templates/         telas de login e troca de senha
```

## 7. Limites desta versão

- Todos os usuários com acesso a uma obra têm os mesmos poderes nela (exceto apagar tudo e importar, que são só do dono). Papéis por módulo (engenharia, suprimentos, financeiro) ficam para a próxima fase.
- Não há "esqueci minha senha" por e-mail: o administrador redefine.
- Não há histórico de quem alterou o quê, além de quem aprovou cada medição.


## Base SINAPI (consulta)

O app `sinapi` guarda composições, insumos e preços do SINAPI por UF, mês e regime (somente leitura). No Orçamento, "Adicionar serviço → Pelo SINAPI" busca a composição, mostra os insumos e preços (com aviso quando o preço é de São Paulo ou falta) e copia tudo para a obra. Composições e insumos do SINAPI não são editáveis (use Duplicar). A UF e o regime padrão ficam em Dados da obra. Para carregar um mês, **no seu computador** (não na Vercel), com `DATABASE_URL` apontando para o banco:

```
pip install -r requirements-etl.txt
python manage.py carregar_sinapi --arquivo SINAPI_Referencia_2026_09.xlsx --base 2026-09 --uf SE BA --regime sd cd
```

A carga é tudo ou nada, confere o custo de cada composição contra o publicado e não repete o mesmo arquivo.
