# Prumo · Integração com o SINAPI (design para a próxima sessão)

Status: **desenho revisado com o arquivo real `SINAPI_Referência_2026_09.xlsx` (mês de referência 09/2026, emitido em 09/10/2026). Fase 1 implementada em 15/10/2026 (ver seção 16); Fase 2 pendente.** Escrito em 14/10/2026, depois do commit `5c4c141` (orçamento amarrado por insumo → composição → serviço na etapa). A Fase 0 (verificações) está concluída quanto ao arquivo; ficam pendentes os itens da seção 12.

> Cópia do documento mantido no Project "App - Controle de obra" (claude.ai). Se houver divergência, confira o Project.

## 0. O que o arquivo real mudou no desenho

Resumo para quem só quer saber o que mudou em relação à primeira versão deste documento. Detalhes nas seções 4, 6 e 7.

| # | Achado (medido no arquivo) | Efeito no desenho |
|---|---|---|
| 1 | **Um único arquivo traz as 27 UFs.** Não há download por UF. | A carga recebe um arquivo e uma lista de UFs (`--uf SE BA`); o resto é ignorado. |
| 2 | Há **3 regimes**, em abas separadas: SD (sem desoneração), CD (com desoneração) e SE (sem encargos sociais). Os preços de insumos e custos de composições existem nos três. | `Referencia.regime` é obrigatório. Medi que **só os 184 insumos de mão de obra têm preço diferente entre os regimes**; material e equipamento são idênticos. |
| 3 | **Os coeficientes são independentes de UF e de regime**, e ficam todos na aba `Analítico` (56.568 itens, 10.599 composições). | Respondida a pergunta aberta: `ComposicaoItem` **não** precisa de `referencia`. Só preço e custo variam por referência. |
| 4 | **O código da composição nas abas de custo (CSD/CCD/CSE) é uma fórmula `HYPERLINK`.** Lido com `data_only=True` vira 0 nas 10.599 linhas. | O ETL tem que extrair o código do texto da fórmula (o número em `MATCH(<codigo>,...)`). Fiz isso: 10.599 de 10.599 extraídos, e o conjunto bate 100% com o `Analítico`. |
| 5 | **Preço em branco = não houve coleta mínima na UF naquele mês.** Em SE são **36,5% dos insumos** (1.779 de 4.878); em BA, 7,4%; em SP, 0%. | O SINAPI cobre o buraco usando o preço de **São Paulo** (é o que a coluna `%AS` mede). Reproduzi isso e o custo recalculado passou a bater (item 6). O ETL precisa aplicar o mesmo fallback e **marcar a origem do preço**. |
| 6 | Recalculando `soma(coeficiente × preço)` recursivamente e comparando com o custo publicado, **com o fallback para SP**: SE 99,2% dentro de `max(R$0,02; 0,5%)`, os 71 restantes ficam dentro de 5% e **nenhum passa de 5%**. BA: 99,4% dentro da tolerância, 49 dentro de 5%, nenhum acima. Sem o fallback, 3.758 composições de SE (das que usam preço de SP) passavam de 5% de erro. | A conferência de custo (6.4) é viável, mas com **tolerância absoluta + relativa**, não 1% fixo (causa: preços publicados com 2 casas; composições de centavos distorcem a % relativa). |
| 7 | Em **SE, 62% das composições com custo (5.228 de 8.443) usam algum preço de SP** (`%AS` > 0); 2.070 têm `%AS` ≥ 50% e 491 são 100% SP. | A interface **não pode** apresentar o preço de Sergipe como se fosse local. Mostrar a origem e o `%AS`. |
| 8 | **2.155 composições são `SEM CUSTO`** e aparecem com custo 0/vazio. Em SE, 8.443 têm custo > 0; nenhuma delas depende de insumo sem preço nacional. | A busca lista por padrão só composições com custo na referência escolhida. |
| 9 | **1.246 insumos usados no `Analítico` não existem nas abas de preço**: todos `SEM PREÇO` em âmbito nacional. Por outro lado, 1.995 insumos das abas de preço não são usados em nenhuma composição. | O cadastro de insumos do SINAPI precisa vir da **união** das abas de preço com o `Analítico` (6.124 códigos). |
| 10 | **Mão de obra e equipamento já vêm como composições auxiliares** (ex.: 88316 SERVENTE COM ENCARGOS COMPLEMENTARES, unidade H; composições de equipamento em CHP/CHI). **Profundidade máxima 5, sem ciclos**, todas as 34.583 referências a auxiliares resolvem dentro da mesma aba. | O achatamento recursivo é seguro. Reproduzir o custo **não exigiu aplicar os fatores horista/mensalista** das linhas 6-7: os encargos já estão embutidos nos insumos. Não precisamos desses fatores. |
| 11 | 172 grupos. Parte são composições **internas, não orçáveis**: "Depreciação, Juros, Impostos e Seguros, Manutenção…" (906), "Custos Horários Produtivo e Improdutivo dos Equipamentos" (438), "Livro SINAPI: Cálculos e Parâmetros" (376). | A busca padrão exclui esses grupos (lista configurável). |
| 12 | Só **18 unidades de composição** e **21 de insumo**, 7 classificações de insumo. | Mapas de unidade e tipo ficam pequenos e completos (seção 7.4). |

## 1. Objetivo

Permitir que o usuário monte o orçamento escolhendo composições **direto do SINAPI** (com insumos, coeficientes e preços por UF, data-base e regime), além dos insumos e composições criados manualmente.

Princípio central: **o SINAPI é uma base de consulta separada. Ao usar uma composição, o Prumo COPIA os dados para o cadastro da obra.** Nunca há referência viva entre o orçamento e a tabela SINAPI.

Por que copiar e não referenciar:
- o preço congelado no orçamento (já implementado em `InsumoPrevisto` e `_congelar`) continua valendo sem mudança;
- as tabelas SINAPI podem ser podadas ou recarregadas sem quebrar nenhum orçamento (nenhuma FK aponta para elas);
- o resto do produto (estoque, consumo, previsto × usado, importação) funciona igual, porque a composição SINAPI vira uma `Composicao` comum.

## 2. Estado atual do código (ponto de partida)

Repo `thalys22/obrasimples`, branch `main`, commit `5c4c141`. Deploy automático na Vercel (`prumoobras.vercel.app`), banco Neon via pooler.

- `obras/models.py`: `Etapa`, `Insumo` (obra nula = base geral; `codigo` único por escopo), `Composicao`, `ItemComposicao`, `ItemOrcamento` (com `etapa` FK, `composicao`, `codigo`), `InsumoPrevisto` (cópia de coeficiente e preço), `Material.insumo`.
- `obras/services.py`: `salvar_insumo`, `salvar_composicao`, `_itens_composicao`, `duplicar_composicao`, `_congelar`, `adicionar_item`, `atualizar_pela_composicao`, `importar_*`, `catalogo()` (alimenta o `estado`).
- `obras/biblioteca.py`: biblioteca inicial aproximada (38 insumos, 21 composições, migração `0004`).
- Frontend: `frontend/app.html` (página única). Funções relevantes: `renderOrcamento`, `renderCadastros`, `abrirInsumo`, `abrirComposicao`, `handleAddOrcamento`, `orcDraft`.
- Migrações existentes: `0001` a `0004`.
- Testes: 43 (`DJANGO_DEBUG=1 python manage.py test obras`), passam em SQLite e PostgreSQL 16.

## 3. Arquitetura

### 3.1 Fase 1: módulo separado, mesmo projeto e mesmo banco

Criar um app Django **`sinapi`**, com tabelas próprias e **somente leitura** para o usuário. O resto do Prumo só conversa com ele pela camada de serviço (`sinapi/servico.py`), nunca pelos models.

Por que não um servidor à parte já: um segundo deploy, autenticação entre serviços, versionamento de API e uma segunda latência (cold start da Vercel mais a chamada) não se justificam enquanto só o Prumo consome. Os números do arquivo reforçam: o conjunto de SE+BA cabe em dezenas de MB (seção 6.5), longe de exigir banco próprio. A interface da camada de serviço é desenhada como se fosse uma API; se o SINAPI virar produto próprio, troca-se a implementação por um cliente HTTP sem mexer no Prumo.

### 3.2 Fase 2 (só se necessário): serviço separado

Gatilhos: mais de um produto consome, ou você quer vender a API, ou o volume exige banco próprio. Aí o módulo `sinapi` vira um serviço com endpoints equivalentes à camada de serviço (seção 5) e o backend do Prumo o chama com chave em variável de ambiente. **O navegador nunca chama a base diretamente** (evita expor a chave e problemas de CORS).

## 4. Modelo de dados do app `sinapi` (revisado)

Mudança de decisão em relação à versão anterior: **guardar as linhas do `Analítico` como vieram (com a hierarquia de composições auxiliares) e achatar na leitura**, em vez de achatar na carga. Motivos medidos: o `Analítico` tem 56.568 linhas; achatado todas as composições viram 145.823 linhas (2,6×). A leitura de uma única composição na importação é barata (profundidade máx. 5, no máximo 57 insumos distintos depois de achatar). Além disso, a hierarquia preservada permite exibir "SERVENTE COM ENCARGOS COMPLEMENTARES" como no original e conferir contra o arquivo linha a linha.

| Tabela | Campos principais |
|---|---|
| `Referencia` | `uf` (2 letras), `data_base` (primeiro dia do mês), `regime` (`sd`, `cd`, `se` = sem desoneração, com desoneração, sem encargos sociais), `carregada_em`. Único por (`uf`, `data_base`, `regime`). |
| `Insumo` | `codigo` (inteiro, único), `descricao`, `unidade`, `classificacao` (texto original: MATERIAL, MAO DE OBRA, ENCARGOS COMPLEMENTARES, EQUIPAMENTO (AQUISIÇÃO), EQUIPAMENTO (LOCAÇÃO), SERVIÇOS, ESPECIAIS), `tipo` (já mapeado para o Prumo), `sem_preco_nacional` (bool; os 1.246 casos). União das abas de preço e do `Analítico`. |
| `PrecoInsumo` | `referencia`, `insumo`, `preco` (**nulo permitido**), `origem_preco` (`local` \| `sp` \| nulo), `coleta` (`C` coletado \| `CR` coeficiente de representatividade, texto original da coluna Origem de Preço). Já com o **fallback para SP aplicado** (`origem_preco = sp` quando o preço local estava em branco). Os preços de SP usados só no fallback **não** são gravados como referência própria, a menos que SP seja uma UF carregada. |
| `Composicao` | `codigo` (inteiro, único), `descricao`, `unidade`, `grupo`, `situacao_nacional` (COM CUSTO / SEM CUSTO / EM ESTUDO), `orcavel` (bool; falso para grupos internos, ver seção 0 item 11). |
| `ComposicaoItem` | `composicao`, `tipo_item` (`insumo` \| `composicao`), `insumo` (FK nula), `composicao_filha` (FK nula), `coeficiente`. **Linha do `Analítico` como está; independente de UF e regime.** Check de integridade: exatamente um dos dois FKs preenchido. |
| `CustoComposicao` | `referencia`, `composicao`, `custo_publicado` (nulo se vazio/0), `pct_as` (fração do custo obtida com preços de SP, de 0 a 1). Usado para exibição e conferência. |
| `Carga` | `referencia`, `arquivo`, `sha256`, `status`, `linhas`, `avisos` (texto/JSON), `criada_em` — auditoria e idempotência. |

Índices: `Composicao` por busca textual e por `grupo`; `PrecoInsumo (referencia, insumo)`; `CustoComposicao (referencia, composicao)`; `ComposicaoItem (composicao)`.

Observação sobre regimes: como só mão de obra muda de preço entre regimes, seria possível guardar uma única linha para os demais. **Não vale a complexidade**: são 4.878 preços por UF e regime, e guardar tudo mantém a consulta simples.

Busca: no PostgreSQL, `pg_trgm` + `unaccent` (confirmar se o Neon permite as extensões; criar com `CreateExtension` só quando `connection.vendor == "postgresql"`). No SQLite (testes), fallback com `icontains` sobre texto normalizado. As descrições vêm em maiúsculas e algumas sem acento; normalizar nos dois lados.

## 5. Contrato da camada de serviço (`sinapi/servico.py`)

```
referencias_disponiveis() -> [{uf, data_base, regime}]
buscar_composicoes(q, uf, data_base, regime, grupo=None, limite=20, deslocamento=0)
    -> {total, itens:[{codigo, descricao, unidade, grupo, custo, pct_as}]}
obter_composicao(codigo, uf, data_base, regime)
    -> {codigo, descricao, unidade, referencia:{uf,data_base,regime}, custo, pct_as,
        itens:[{codigo_insumo, descricao, unidade, tipo, coef, preco|None, origem_preco}],
        estrutura:[...linhas do Analítico, com composições auxiliares, para exibição...],
        avisos:[ "N insumos sem preço nesta referência", "X% do custo usa preços de São Paulo" ]}
```

Regras: busca com mínimo de 2 caracteres, paginada (máx. 50 por página), sempre filtrada por uma `Referencia` existente; por padrão lista só `orcavel` e com `custo_publicado` na referência (parâmetro para incluir "sem custo"); `obter_composicao` devolve `preco = None` quando faltar preço (nunca zero). `itens` vem **achatado** (soma de coeficientes por insumo, multiplicando pelos coeficientes das auxiliares).

## 6. Carga dos dados (ETL)

### 6.1 Onde roda

**Fora da função da Vercel.** A carga é um *management command* rodado localmente ou num GitHub Actions, apontando para o banco de produção. Motivos: limite de tamanho do pacote e de tempo das funções, e dependências pesadas de planilha que não devem entrar no runtime. O arquivo tem 13,6 MB e 12 abas.

- `requirements-etl.txt` separado (ex.: `openpyxl`), **fora** do `requirements.txt` de produção.
- Leitura em modo `read_only`. A leitura das abas de custo exige **duas passadas**: uma com `data_only=False` só para extrair o código da fórmula, outra com `data_only=True` para os valores (as linhas vêm na mesma ordem; validar com assert que o número de linhas bate).
- Para carga em lote no Neon, preferir a **conexão direta** (sem pooler) e transações por arquivo.
- **Tempo e memória da carga não foram medidos.** Medir na Fase 1.

### 6.2 Layout do arquivo (validar cabeçalho, falhar com mensagem clara se mudar)

- Abas usadas: `ISD`, `ICD`, `ISE` (insumos) · `CSD`, `CCD`, `CSE` (custos de composição) · `Analítico` (estrutura). Ignorar `Menu`, `Busca` (fórmulas de busca do Excel) e `Analítico com Custo` (ferramenta de fórmulas).
- Preços de insumos (`ISx`): cabeçalho na linha 10 (`Classificação, Código do Insumo, Descrição do Insumo, Unidade, Origem de Preço`, depois uma coluna por UF), dados a partir da linha 11. Linhas 1-9: título, "Mês de Referência: MM/AAAA", regime, e os fatores de encargos (não usados).
- Custos (`CSx`): cabeçalho na linha 10 (`Grupo, Código da Composição, Descrição, Unidade`, depois um par `Custo (R$)` / `%AS` por UF), dados a partir da linha 11. Código em fórmula (seção 0 item 4).
- `Analítico`: cabeçalho na linha 10 (`Grupo, Código da Composição, Tipo Item, Código do Item, Descrição, Unidade, Coeficiente, Situação`). A linha de **cabeçalho da composição** tem `Tipo Item` vazio e não tem coeficiente; as linhas seguintes são itens (`INSUMO` ou `COMPOSICAO`).
- **Localizar colunas de UF pelo texto do cabeçalho, não por posição.** Primeira validação do loader: mês de referência da aba bate com o argumento `--base`; as 27 UFs existem; contagens esperadas (neste arquivo: 4.878 insumos com preço, 10.599 composições, 56.568 itens).
- Valores de `Situação` vistos: `COM PREÇO`, `SEM PREÇO` (insumo); `COM CUSTO`, `SEM CUSTO`, `EM ESTUDO` (composição, e itens do tipo composição). 4 itens têm coeficiente zero ou nulo: registrar no relatório, não descartar em silêncio.

### 6.3 Comando

```
python manage.py carregar_sinapi --arquivo SINAPI_Referencia_2026_09.xlsx \
    --base 2026-09 --uf SE BA --regime sd cd
```

- Idempotente: se o `sha256` do arquivo já foi carregado para a mesma `Referencia`, não faz nada.
- `bulk_create` em lotes; uma transação por arquivo; tudo ou nada.
- Ordem: (1) validar cabeçalhos; (2) carregar `Insumo` (união preços + `Analítico`); (3) `Composicao` e `ComposicaoItem` (estrutura, independente de referência; só reescreve se o `sha256` mudou); (4) detectar ciclos e profundidade > 8 (falha a carga); (5) `PrecoInsumo` com fallback SP; (6) `CustoComposicao`; (7) conferência.
- Imprime um relatório: linhas lidas, insumos e composições novos, composições sem itens, unidades fora do mapa, % de insumos sem preço local por UF, % de preços vindos de SP, divergências de custo.
- **Primeira versão: arquivo baixado manualmente** (a automação do download vem depois; não verificei se o site da Caixa permite download automático).

### 6.4 Conferência de custo (obrigatória antes de dar a carga como boa)

Para cada composição com `custo_publicado`, recalcular `soma(coeficiente × preço efetivo)` recursivamente (preço efetivo = local, ou SP quando o local está em branco) e comparar.

- **Tolerância: `|calculado − publicado| ≤ max(R$ 0,02; 0,5% do publicado)`.** Motivo medido: os preços do arquivo têm 2 casas e o SINAPI calcula com precisão maior; em composições de centavos (ex.: 91689 SERRA CIRCULAR, publicado R$ 0,01) o erro relativo chega a 95% com diferença de um centavo.
- Resultado esperado para este arquivo, regime SD, como referência para os testes da carga: **SE 8.372 dentro da tolerância, 71 até 5%, 0 acima; BA 8.394 / 49 / 0.** Nos regimes CD e SE do arquivo (sem encargos) aparecem 1 a 2 casos acima de 5% por UF: aceitos com aviso, não bloqueiam a carga.
- Critério de bloqueio sugerido: mais de 1% das composições fora de 5% **ou** qualquer composição com custo publicado e sem custo calculável.
- Divergência vira aviso listado no relatório, não erro silencioso.
- Conferir manualmente 5 composições conhecidas contra o arquivo original (sugestão: 104658, 105002, 88316, 88309 e uma de revestimento).
- Nenhum item órfão (todo `Tipo Item = COMPOSICAO` tem a filha definida; neste arquivo, 0 órfãos); contagens batem com as do arquivo.

**Consequência para o produto:** o custo que o Prumo calcula a partir dos coeficientes e preços copiados pode diferir do publicado em até ~0,5%. Mostrar na prévia o **"Custo SINAPI publicado"** ao lado do calculado; o orçamento usa o calculado (é o que a mesma composição vai gerar nos insumos previstos).

### 6.5 Retenção e tamanho (estimativa, não medida)

- Escopo inicial: **SE e BA**, regimes **sd** e **cd**. O regime `se` (sem encargos sociais) só muda mão de obra e não parece útil para obra privada; deixar fora até alguém pedir.
- Linhas por referência (UF × regime × mês): 4.878 preços + 10.599 custos ≈ **15,5 mil**. Estrutura (uma vez): 6,1 mil insumos, 10,6 mil composições, 56,6 mil itens.
- Escopo inicial (2 UFs × 2 regimes × 1 mês): ≈ 62 mil linhas por referência somadas + 73 mil de estrutura ≈ **135 mil linhas**. Pelas minhas contas, algo entre 20 e 30 MB com índices. Seis meses de histórico: ≈ 400 mil linhas, **cerca de 50 a 60 MB**. Estimativa de cabeça; **medir depois da primeira carga** e comparar com o limite do plano Neon (conferir o limite no painel; não assumir).
- Guardar as últimas 6 referências por UF e regime. Como nenhuma FK do Prumo aponta para essas tabelas, podar as antigas é seguro.

## 7. Mudanças no Prumo

### 7.1 Campos novos (migração `obras 0005`)

- `Insumo`: `fonte` (`proprio` | `sinapi` | `tcpo`), `codigo_fonte` (texto), `uf`, `data_base`, `regime`, `sem_preco` (bool), `origem_preco` (`local` | `sp` | vazio).
- `Composicao`: `fonte`, `codigo_fonte`, `uf`, `data_base`, `regime`, `custo_publicado` (decimal nulo), `pct_as` (decimal nulo).
- `ItemOrcamento`: `origem` (texto, ex.: `SINAPI 87878 · SE · 09/2026 · sem desoneração`), preenchido em `_congelar`. Assim o rótulo fica congelado junto com o preço, mesmo se a composição for atualizada depois.
- `Obra`: `uf` e `regime_sinapi` (padrões para a busca), editáveis em *Dados da obra*.

### 7.2 Códigos

O código SINAPI não deve colidir com os próprios: `codigo = "SINAPI-<n>"` (mantém a unicidade existente por obra), `codigo_fonte = "<n>"` para localizar. O TCPO usa o mesmo mecanismo com `fonte = "tcpo"`, só como importação feita pelo usuário (ver 11).

### 7.3 Importação para a obra (`services.importar_sinapi_composicao`)

Transação:
1. Chama `obter_composicao` (já achatado).
2. Para cada insumo, cria ou localiza o `Insumo` da obra (`fonte=sinapi`, `codigo_fonte`), normalizando unidade e tipo. Preço ausente → `preco=0` e `sem_preco=True`. `origem_preco` copiado.
3. Cria a `Composicao` da obra com os itens e coeficientes, e `custo_publicado` / `pct_as`.
4. Idempotente: se a obra já tem essa composição na mesma referência, devolve a existente; se for outra data-base, pede para usar "atualizar".
5. Retorna `composicaoId` e a lista de avisos.

Escopo: **sempre na obra** (a base geral continua só do administrador). Fica por decidir se compensa um comando de administrador para promover uma composição SINAPI à base geral.

**Mão de obra e equipamento:** as composições auxiliares de mão de obra (H) e de equipamento (CHP/CHI) são achatadas até os insumos. O resultado traz o insumo de mão de obra (ex.: servente horista) **mais** insumos de `ENCARGOS COMPLEMENTARES` (alimentação, EPI, transporte, exames; 56 insumos, unidades H e MES). Para o estoque isso é irrelevante (não são itens comprados), então o tipo desses insumos deve ser `mao-de-obra` e eles não devem gerar alertas de falta de material.

### 7.4 Regras e mapas

- Coeficientes e insumos de origem SINAPI ficam **travados para edição** (rastreabilidade). Para ajustar, o usuário usa *Duplicar*, que gera uma composição `proprio`, com `Cópia de SINAPI-xxxxx` na observação.
- O **preço** de um insumo SINAPI pode ser preenchido à mão quando estiver ausente (é exceção ao travamento, e muda `sem_preco` para falso).
- **Atualizar para nova data-base** (`atualizar_sinapi(obra, composicao_id, data_base)`): rebusca coeficientes e preços e atualiza a `Composicao` e os `Insumo` da obra; os serviços já no orçamento **não mudam** até o usuário usar *Atualizar pela composição* em cada um (comportamento já existente).
- **Mapa de unidades** (completo para este arquivo). Composições: `UN, M2, M, H, M3, CHI, CHP, T, KG, MES, UNXKM, TXKM, M3XKM, MXKM, M2XKM, KGXKM, LXKM, L`. Insumos: `UN, M, M2, KG, MES, H, L, M3, CJ, PAR, CENTO, JG, UNXMES, T, SC25KG, KWH, MIL, 100M, M2XMES, MXMES, 310ML`. Mapear para o padrão do Prumo (`M2→m²`, `M3→m³`, `H→h`, `KG→kg`, `UN→un`, `T→t`, `L→l`, `M→m`, `MES→mês`, `KWH→kWh`…). As unidades compostas (`M3XKM`, `UNXMES`…) e `CHP/CHI/CJ/PAR/CENTO/MIL/JG/SC25KG` ficam como vieram, em minúsculas, até haver decisão de produto. Comparar sem diferenciar maiúsculas (existe `M2xMES` com caixa mista no `Analítico`). Unidade fora do mapa entra no relatório.
- **Mapa de tipos** (classificação do insumo → tipo do Prumo): `MATERIAL → material` (4.365) · `MAO DE OBRA → mao-de-obra` (184) · `ENCARGOS COMPLEMENTARES → mao-de-obra` (56) · `EQUIPAMENTO (AQUISIÇÃO)` e `EQUIPAMENTO (LOCAÇÃO) → equipamento` (245) · `SERVIÇOS → empreitada` (25; são serviços terceirizados como "abertura para encaixe de cuba") · `ESPECIAIS → material` (3: energia elétrica e tarifa de água, em KWH e M3; **decisão aberta**, pode merecer tipo próprio ou ficar como material).

## 8. API do Prumo (backend próprio, exige login e obra)

```
GET  /api/sinapi/referencias
GET  /api/sinapi/composicoes?q=&uf=&base=&regime=&grupo=&offset=
GET  /api/sinapi/composicoes/<codigo>?uf=&base=&regime=     (prévia, não grava nada)
POST /api/sinapi/importar   {codigo, uf, base, regime}      -> {composicaoId, avisos, estado}
POST /api/sinapi/atualizar  {composicaoId, base}            -> {avisos, estado}
```

Os dados do SINAPI **não entram no `estado`** (para não inflar a resposta); só a composição importada entra, pelo `catalogo()` normal. Limitar a frequência de busca por usuário.

## 9. Interface

1. **Orçamento → Adicionar serviço:** terceira opção ao lado de "Pela composição" e "Por verba": **"Pelo SINAPI"**. UF, mês e regime pré-preenchidos pelos padrões da obra. Campo de busca com atraso (debounce), lista paginada (código, descrição, unidade, custo), painel de prévia com os insumos, coeficientes e preços, destacando insumos **sem preço**. Botão *Usar este serviço*: importa para a obra e já seleciona a composição, pedindo a quantidade.
2. **Cadastros:** seção "Buscar no SINAPI" para importar sem adicionar serviço ainda. Etiqueta `SINAPI 09/2026 · SE` nas composições e insumos de origem SINAPI, no lugar de "desta obra". Botão *Atualizar para a data-base nova*.
3. **Aviso de insumos sem preço** antes de importar: o usuário escolhe preencher depois, usar outra referência ou cancelar.
4. **Aviso de preço de São Paulo.** Na prévia: "X% do custo desta composição usa preços de São Paulo, porque o SINAPI não coletou preço em Sergipe neste mês" (para SE isso será comum: 62% das composições). Por insumo, etiqueta "preço de SP".
5. **Rótulo de fonte** visível no serviço do orçamento (`origem`) e a frase "Fonte: SINAPI/Caixa" na prévia.
6. Busca padrão esconde composições internas (equipamento por hora, livro de parâmetros) e sem custo; um filtro avançado as mostra.
7. Mobile: a prévia abre no mesmo painel modal já usado em Cadastros.

## 10. Testes

- **Fixture pequena feita à mão no formato do arquivo real** (não commitar o arquivo oficial inteiro, 13,6 MB): uma aba por tipo, com cabeçalho na linha 10, uma composição com auxiliar dentro de auxiliar, uma `SEM CUSTO`, um insumo `SEM PREÇO`, um insumo com preço em branco em SE e preenchido em SP, e **o código da composição como fórmula `HYPERLINK`** (o teste precisa cobrir esse caso, porque é o que quebra silenciosamente).
- **Achatamento:** auxiliar simples, auxiliar dentro de auxiliar, mesmo insumo por dois caminhos (soma), ciclo (falha clara), limite de profundidade.
- **Carga:** idempotência por `sha256`; tudo ou nada; conferência de custo com a tolerância `max(R$0,02; 0,5%)`; fallback para SP marca `origem_preco`; unidade fora do mapa; cabeçalho trocado falha com mensagem clara.
- **Serviço:** busca respeita a referência; paginação; `preco = None` quando ausente; busca padrão exclui composição sem custo e grupos internos.
- **Importação:** cria insumos e composição na obra; idempotente; preço ausente marca `sem_preco`; usuário sem obra recebe 400; usuário não acessa obra alheia; composição SINAPI não pode ser editada, mas pode ser duplicada.
- **Atualização:** nova data-base muda cadastro, **não** muda serviços já orçados.
- **Estado:** `estado` não contém dados do SINAPI.
- **PostgreSQL:** a busca com `pg_trgm` precisa de teste em PostgreSQL (o SQLite só cobre o fallback).
- **Navegador (Playwright):** buscar, ver prévia, importar, adicionar ao orçamento, conferir insumos previstos.
- **Teste com o arquivo real (manual, fora do CI):** carregar SE e BA, e conferir o relatório contra os números da seção 6.4.

## 11. Fora de escopo e riscos

- **TCPO:** conteúdo pago da Editora PINI. **Não** incluir como base geral. Apenas aceitar importação feita pelo próprio usuário (planilha no formato do modelo), com `fonte = tcpo` e o código guardado como referência. Confirmar nos termos da licença antes de divulgar isso como recurso.
- **Termos de uso do SINAPI:** os dados são públicos, mas as condições de reutilização e redistribuição da Caixa **não foram lidas**. Conferir antes de oferecer como parte de produto pago. O arquivo traz metodologia própria (grupo "Livro SINAPI"); citar a fonte em toda tela que exibir dados.
- **Cobertura de preço em Sergipe:** 36,5% dos insumos sem preço local no mês (09/2026). Se o produto prometer "preço de Sergipe", isso é falso para boa parte das composições. A promessa correta é "preço SINAPI para a regional, com fallback de São Paulo identificado".
- **Preços de mão de obra** mudam entre regimes (e só eles). Um usuário que compare orçamentos em regimes diferentes verá diferença só na mão de obra. Documentar na tela e recomendar revisão de quem orça.
- **Mudança de layout dos arquivos:** o ETL valida cabeçalhos e contagens e falha com mensagem clara, não importa lixo. A dependência da fórmula `HYPERLINK` para o código é frágil: se a Caixa trocar a fórmula, o loader deve falhar (assert de 100% de códigos extraídos), não pular linhas.
- **Manutenção mensal:** alguém precisa carregar o mês novo (manual no início; automatizar depois).
- **Insumos fora de composição:** 1.995 insumos têm preço mas não aparecem em nenhuma composição. Ficam carregados; uma busca de insumo avulso do SINAPI (para orçar por verba) é possível mas **não faz parte desta versão**.

## 12. Plano em fases

**Fase 0 (feita nesta sessão): verificações no arquivo real.** Itens resolvidos: layout das abas, regimes e UFs, código em fórmula, coeficientes independentes de UF e regime, ausência de ciclos e profundidade máxima 5, preço em branco e fallback para SP, conferência de custo (seção 6.4), inventário de unidades e classificações.
**Ainda pendente da Fase 0 (nenhum depende do arquivo):**
1. Ler os termos de uso da Caixa sobre reutilização e redistribuição.
2. Conferir o limite de armazenamento do plano Neon e se `pg_trgm` e `unaccent` estão disponíveis.
3. Verificar se o download do arquivo na página da Caixa pode ser automatizado (o ambiente de execução não alcança a maioria dos sites; talvez precise ser testado fora dele).
4. Obter um segundo arquivo (outro mês) para validar que o layout se mantém antes de cravar o loader.

**Fase 1: base SINAPI e carga**
App `sinapi` (modelos, migração), comando `carregar_sinapi`, extração do código da fórmula, achatamento na leitura, fallback para SP, conferência de custo, camada de serviço, testes com a fixture. Carregar SE e BA em ambiente local primeiro; medir tempo, memória e tamanho no banco.

**Fase 2: integração no Prumo**
Migração `0005`, `importar_sinapi_composicao`, endpoints, aba "Pelo SINAPI", rótulo de fonte e de origem do preço, travamento de edição, testes e fluxo no navegador.

**Fase 3: atualização e padrões da obra**
`Obra.uf` e `regime_sinapi`, botão de atualizar data-base, aviso de preços ausentes completo.

**Fase 4: automação**
GitHub Actions agendado para detectar e carregar o mês novo; alerta quando o layout mudar; poda das referências antigas.

## 13. Critérios de aceite

- Buscar "alvenaria" devolve resultados em menos de 1 segundo, com paginação, sem baixar a base inteira.
- Importar uma composição SINAPI cria insumos e composição na obra, e a prévia mostra os mesmos coeficientes do arquivo original.
- A carga de SE e BA (regime sd) reproduz os números da seção 6.4 (dentro da tolerância: 8.372 e 8.394; nenhuma composição acima de 5%).
- Para uma amostra de 5 composições, o custo calculado pelo Prumo bate com o publicado dentro de `max(R$0,02; 0,5%)`.
- Composição cujo custo depende de preço de SP **mostra** o `%AS` e a etiqueta do insumo.
- Adicionar o serviço ao orçamento produz insumos previstos corretos e funciona o comparativo previsto × usado do estoque.
- Reimportar o mesmo mês não duplica nada; carregar mês novo não altera nenhum orçamento existente.
- Insumo sem preço nunca é tratado como zero em silêncio.
- Todos os testes antigos e novos passam em SQLite e PostgreSQL.

## 14. Decisões para confirmar no início da próxima sessão

| Decisão | Recomendação |
|---|---|
| UFs iniciais | SE e BA |
| Regimes iniciais | `sd` e `cd`; `se` (sem encargos) fora |
| Regime padrão da obra | Sem desoneração (confirmar com o uso real) |
| Guardar estrutura ou achatar na carga | Guardar o `Analítico` como está e achatar na leitura (2,6× menos linhas) |
| Fallback de SP | Aplicar na carga, gravar `origem_preco` e mostrar ao usuário |
| Onde a composição importada fica | Na obra (não na base geral) |
| Editar composição SINAPI | Travar; permitir só *Duplicar* |
| Tipo para `ESPECIAIS` (energia, água) | Material por ora |
| Unidades compostas (`M3XKM`, `UNXMES`…) | Manter como vieram |
| Servidor separado | Não agora; módulo isolado com interface de serviço |

## 15. Como retomar o ambiente

- Testes: `DJANGO_DEBUG=1 python manage.py test obras`.
- PostgreSQL local para testes: binários em `/usr/lib/postgresql/16/bin`, rodando como usuário `pgtest` (precisa ser recriado se o ambiente for novo); apontar com `DATABASE_URL=postgres://postgres@127.0.0.1:<porta>/<banco>`.
- Teste de interface: Playwright com Chromium já instalado em `/opt/pw-browsers`; a biblioteca `xlsx` do navegador vem de CDN que o ambiente pode bloquear, então servir uma cópia local na rota do teste.
- Deploy: `git push origin main` dispara a Vercel; conferir o status pela API de status de commit do GitHub (o ambiente não alcança `vercel.app`).
- O arquivo SINAPI usado na análise foi anexado à conversa; não está no repositório. Para reanalisar, pedir o arquivo de novo ou baixar da Caixa.

## 16. Fase 1 implementada (15/10/2026)

Código: `sinapi/` (`models.py`, `leitor.py`, `carga.py`, `servico.py`, `mapas.py`, comando `carregar_sinapi`), migração `sinapi/0001`, `requirements-etl.txt`.

**Medido com o arquivo real (SE e BA, regimes sd e cd, mês 09/2026):**
- Conferência de custo: SE/sd 8.372 dentro da tolerância, 71 até 5%, 0 acima; BA/sd 8.394 / 49 / 0 (idêntico ao desenho). cd: SE 8.361/81/1, BA 8.385/56/2 (aceitos com aviso; limite de bloqueio 1%).
- Tempo 34 a 41 s; pico de memória 214 MB; segunda execução com o mesmo arquivo: 1,4 s ("nada a fazer").
- Tamanho: banco inteiro 31 MB no PostgreSQL 16 (maiores tabelas: itens 7,1 MB, custos 6,1 MB, composições 4,9 MB, preços 2,9 MB). Estimativa antiga de 20 a 30 MB confirmada para o escopo inicial.
- Contagens: 10.599 composições (1.720 não orçáveis: 906+438+376), 6.124 insumos (1.246 sem classificação por só existirem no Analítico), 56.568 itens; SE/sd com 1.779 de 4.878 preços vindos de SP.
- Busca "alvenaria" em SE: 461 resultados em 28 ms; `obter_composicao` em 56 ms (PostgreSQL local).

**Desvios do desenho:**
1. Sem `pg_trgm`/`unaccent`: a busca usa o campo `Composicao.busca` (texto normalizado) com `contains` por palavra. Com 10,6 mil composições é rápido e funciona igual em SQLite e PostgreSQL, sem depender de extensão do Neon. Reavaliar se o catálogo crescer muito.
2. `Carga` é única por (`referencia`, `sha256`); a estrutura (Analítico) só é regravada quando chega um `sha256` novo.
3. SP é lido sempre (para o fallback) mas só vira `Referencia` se pedida em `--uf`.
4. Unidades `M/MES` e `DIA` (4 composições e 1) estavam fora do mapa e foram adicionadas como "mantidas como vieram".
5. O comando valida o mês das abas contra `--base`, mas **não** valida contagens fixas (4.878/10.599/56.568): relata as contagens e confere que CSx e Analítico têm as mesmas composições.

**Ainda não verificado:** termos de uso da Caixa, limite de armazenamento e extensões do Neon, download automático, segundo mês de arquivo (estabilidade do layout), teste de carga no Neon real (só PostgreSQL local).

## 17. Fase 2 implementada (15/10/2026)

- Migração `obras/0006_sinapi_campos`: `Insumo`/`Composicao` ganham `fonte`, `codigo_fonte`, `uf`, `data_base`, `regime` (+ `sem_preco`/`origem_preco` no insumo, `custo_publicado`/`pct_as` na composição); `ItemOrcamento.origem`; `Obra.uf` (padrão SE) e `regime_sinapi` (padrão sd). (O desenho dizia 0005; essa já era do estoque.)
- **Achado medido que mudou o schema:** com coeficiente de 6 casas, ~10% das composições (40 de 400 amostradas) saíam da tolerância de custo; com 8 casas, 1 em 400. Ficou em 10 casas (`ItemComposicao` e `InsumoPrevisto`). Além disso 1.018 composições e 192 insumos têm descrição acima de 200 caracteres: descrições (insumo, composição, serviço do orçamento, material) passaram para 400.
- Insumo já existente na obra com outra data-base é mantido (com aviso); composição já importada em outra data-base exige "atualizar" (Fase 3, não feita).
- Verificado no navegador com o arquivo real (SE/sd): busca, prévia com insumos e etiquetas "SP"/"sem preço", uso no orçamento com origem congelada, cadastro com custo publicado e %SP, edição bloqueada. 101 testes (obras + sinapi) em SQLite e PostgreSQL 16.

## 18. Alagoas incluída (15/10/2026)

Escopo inicial agora é **SE, BA e AL** (regimes sd e cd). Nenhuma mudança de código: a UF é parâmetro da carga. Medido com o arquivo 09/2026: AL/sd 8.368 dentro da tolerância, 71 até 5%, 4 acima de 5%; AL/cd 8.362/79/2. As 4 acima são composições de centavos (R$ 0,25 a R$ 0,57, diferença de até 3 centavos), abaixo do limite de bloqueio de 1%. AL/sd: 1.622 de 4.878 preços (33%) vêm de São Paulo. Carga das 3 UFs: 26 s.

## 19. Carga pelo site (15/10/2026)

Pedido: carregar o SINAPI sem terminal. Decisões: só administrador (mesma regra da base geral) e leitura do xlsx no navegador.

- **Por quê no navegador:** o arquivo (13,6 MB) passa do limite de 4,5 MB por envio de uma função da Vercel. O SheetJS que o app já usa (0.18.5) lê as abas necessárias em 5 a 8 s (medido em Node) e expõe a fórmula `HYPERLINK` (10.599 de 10.599 códigos). Pico de memória medido: ~690 MB lendo 5 abas de uma vez; o app lê uma etapa por vez para ficar abaixo disso.
- **Fluxo:** `iniciar` → várias `parte` (≤ ~1,2 MB cada; o servidor recusa mais de 2,3 MB) → `estrutura` → uma `referencia` por UF e regime → `concluir`. As partes ficam em `CargaParte` e são apagadas no fim (e as com mais de 1 dia, no próximo início). A estrutura só é regravada se o sha256 for novo; cada referência é gravada por inteiro ou não é gravada.
- **Medido (PostgreSQL local, dados reais):** estrutura 7,7 s; cada UF+regime 1,6 s; envio das 44 partes 1 s. No navegador (SQLite local): arquivo lido em 2 s, carga completa de SE, BA e AL nos dois regimes em 23 s, resultados idênticos ao comando; reenvio do mesmo arquivo pula tudo (14 s, só leitura).
- **Risco não verificado:** o tempo máximo de uma função na Vercel em produção. A etapa mais longa (estrutura, 7,7 s local) pode ficar mais lenta falando com o Neon. Se der erro de tempo, a etapa é atômica e pode ser repetida; o remédio é aumentar o limite de duração da função na Vercel (não configurei por não poder verificar). O comando `carregar_sinapi` continua como alternativa.
- O administrador não precisa ter obra para carregar.
