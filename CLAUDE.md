# Prumo (repo `obrasimples`)

App de controle de obra para pequenas construtoras. Django 5.1 + banco PostgreSQL (Neon) em produção, SQLite local. Deploy na Vercel: `git push origin main` publica sozinho em https://prumoobras.vercel.app.

Fale com o usuário em português (Brasil). O dono do projeto prefere crítica direta e baseada em fatos: aponte falhas sem rodeios e só valide o que os dados sustentam.

## Comandos

- Rodar local: `export DJANGO_DEBUG=1 && python manage.py migrate && python manage.py runserver`
- Testes: `DJANGO_DEBUG=1 python manage.py test obras sinapi` (`obras` + `sinapi`: 112 testes; devem passar em SQLite e PostgreSQL 16; os do `sinapi` precisam de openpyxl e são pulados sem ele)
- Para testar em PostgreSQL: `DATABASE_URL=postgres://usuario@127.0.0.1:<porta>/<banco>`

## Estrutura

- `obras/models.py`: modelos. Orçamento em cadeia: `Insumo` (código único) → `Composicao`/`ItemComposicao` → `ItemOrcamento` (por `Etapa`), com preço congelado em `InsumoPrevisto`. `obra` nula em `Insumo`/`Composicao` = base geral.
- `obras/services.py`: **todas as regras de negócio**, dentro de transações. As views só chamam daqui. Cada mutação devolve o `estado` inteiro da obra (`estado()` e `catalogo()`).
- `obras/views.py`, `obras/urls.py`: API JSON em `/api/...`.
- `obras/biblioteca.py`: insumos e composições iniciais (valores aproximados, não são SINAPI/TCPO).
- `obras/admin.py`, `admin_usuarios.py`, `grupos.py`: painel `/admin` e permissões.
- `frontend/app.html`: o app inteiro em uma página (renderOrcamento, renderCadastros, painel lateral).
- `build.py`: roda na Vercel (migrate + createsuperuser a partir de variáveis de ambiente).
- `README.md`: manual do administrador. Mantenha atualizado quando mudar o fluxo.

## Regras

- Regra de negócio vai em `obras/services.py`, nunca só no frontend.
- Migrações novas: confira com `makemigrations --check`. Dados existentes não podem ser perdidos (veja `0003` como exemplo de migração de dados).
- Nunca peça nem grave senhas, `DJANGO_SECRET_KEY` ou `DJANGO_SUPERUSER_PASSWORD`. O dono as digita na Vercel.
- Não faça `git push` sem o pedido do dono: cada push no `main` faz deploy em produção.
- Teste o fluxo de tela com Playwright quando mexer no frontend; a biblioteca `xlsx` do navegador vem de CDN, então sirva uma cópia local no teste se a rede bloquear.

## SINAPI

Desenho em **`docs/sinapi-integracao.md`**. **Fase 1 implementada** (app `sinapi`, somente leitura): modelos, `carregar_sinapi` (rodar fora da Vercel, `pip install -r requirements-etl.txt`), `sinapi/servico.py` (única porta de entrada; o resto do Prumo não importa os models) e 27 testes com planilha-fixture montada em `sinapi/tests.py`. A carga real de SE+BA (sd, cd) foi medida: 34-41 s, ~214 MB de memória, ~31 MB no PostgreSQL; reproduz 8.372/71/0 (SE) e 8.394/49/0 (BA). **Fase 2 implementada**: `services.importar_sinapi_composicao` (copia composição e insumos achatados para a obra, códigos `SINAPI-<n>`), migração `obras/0006` (campos de fonte, `ItemOrcamento.origem`, `Obra.uf`/`regime_sinapi`, coeficiente com 10 casas, descrições com 400), endpoints `/api/sinapi/*` (sem `estado` nas buscas), aba "Pelo SINAPI" no Orçamento. Composição/insumo SINAPI são travados (só Duplicar; só o preço ausente pode ser preenchido). **Carga pelo site** (página do Django admin `/admin/sinapi/referencia/carregar/`, `sinapi/admin.py` + `templates/admin/sinapi/referencia/carregar.html`; só quem pode editar a base geral): o navegador lê o xlsx com SheetJS e envia partes (`/api/sinapi/carga/*`, tabela de passagem `CargaParte`, `sinapi/carga_web.py`); a gravação reutiliza `carga.gravar_estrutura`/`gravar_referencia`, as mesmas do comando. Falta a Fase 3: atualizar para nova data-base.

Comando: `python manage.py carregar_sinapi --arquivo <xlsx> --base 2026-09 --uf SE BA --regime sd cd` (idempotente por sha256; tudo ou nada).
