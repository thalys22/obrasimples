# Prumo (repo `obrasimples`)

App de controle de obra para pequenas construtoras. Django 5.1 + banco PostgreSQL (Neon) em produção, SQLite local. Deploy na Vercel: `git push origin main` publica sozinho em https://prumoobras.vercel.app.

Fale com o usuário em português (Brasil). O dono do projeto prefere crítica direta e baseada em fatos: aponte falhas sem rodeios e só valide o que os dados sustentam.

## Comandos

- Rodar local: `export DJANGO_DEBUG=1 && python manage.py migrate && python manage.py runserver`
- Testes: `DJANGO_DEBUG=1 python manage.py test obras` (43 testes; devem passar em SQLite e PostgreSQL 16)
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

## Próximo trabalho: integração com o SINAPI

O desenho completo, já validado com o arquivo real `SINAPI_Referência_2026_09.xlsx`, está em **`docs/sinapi-integracao.md`**. Leia antes de começar. Resumo: app Django separado `sinapi` (somente leitura), carga por comando `carregar_sinapi` fora da Vercel, composição copiada para a obra ao usar (nunca referência viva), preço de São Paulo usado como fallback quando falta preço local e sempre identificado na tela. Nada disso está implementado ainda.
