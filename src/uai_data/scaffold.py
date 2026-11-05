"""Cria um projeto novo (`uai init`): configuração, organização, painel de exemplo e workflows."""

from __future__ import annotations

import random
import secrets
import sqlite3
from pathlib import Path

UAI_YML = """\
# Configuração do site Uai Data
name: __NAME__
tagline: Explore. Analise. Descubra.
repo: __REPO__            # dono/repositório no GitHub — habilita os botões "Editar" e "Novo painel"
branch: main
locale: pt-BR
currency: BRL
csv_sep: ";"              # CSV pensado para abrir direto no Excel brasileiro
csv_decimal: ","
site_salt: __SALT__       # não é segredo; evita que os nomes dos arquivos de login sejam adivinhados
site_admins: [__ADMIN__]  # quem pode criar organizações e alterar a configuração do site

# Bancos de dados. A URL de conexão NUNCA vai neste arquivo: ela vem de uma variável de ambiente
# (no GitHub: Settings → Secrets and variables → Actions).
databases:
  demo:
    dsn_env: UAI_DB_DEMO      # demo: sqlite:///demo/vendas.db   |   real: postgresql://usuario:senha@host:5432/banco
    statement_timeout_s: 120

catalog_schemas: [public]     # schemas listados na página "Explorar dados"
"""

ORG_YML = """\
# Organização: o administrador decide o que cada pessoa pode fazer.
name: __ORG_NAME__
admins: [__ADMIN__]            # administradores têm todas as permissões e gerenciam as pessoas
databases: [__DBS__]              # bancos que os painéis desta organização podem consultar
allow_sql: false               # true libera cards com 'sql:' (consulta nativa). Use com banco de acesso restrito.

# Perfis = conjuntos de permissões. Crie os que quiser.
#   view = ver · download = baixar (xlsx/pdf/csv/png) · share = gerar link · create = criar painel · edit = editar painel
profiles:
  viewer:  [view]
  analyst: [view, download, share]
  editor:  [view, download, share, create, edit]

# Quem usa qual perfil (os logins precisam existir em access/users.yml)
members:
__MEMBERS__
"""

DASHBOARD_YML = """\
title: Vendas — visão geral
organization: __ORG__
description: Painel de demonstração com as principais visualizações do Uai Data.
database: demo
tags: [demo]

# Filtros do painel: valem para todos os cards que tiverem a coluna
filters:
  - {column: ano, label: Ano}
  - {column: regiao, label: Região}
  - {column: produto, label: Produto}

cards:
  - id: faturamento
    title: Faturamento
    viz: number
    source: {table: vendas}
    measures: [{column: valor, agg: sum, name: faturamento, format: currency}]
    y: [faturamento]
    width: 3
    height: 200

  - id: pedidos
    title: Pedidos
    viz: number
    source: {table: vendas}
    measures: [{agg: count, name: pedidos, format: integer}]
    y: [pedidos]
    width: 3
    height: 200

  - id: ticket
    title: Ticket médio
    viz: number
    source: {table: vendas}
    measures: [{column: valor, agg: avg, name: ticket, format: currency}]
    y: [ticket]
    width: 3
    height: 200

  - id: meta
    title: Quantidade vendida × meta
    viz: gauge
    source: {table: vendas}
    measures: [{column: quantidade, agg: sum, name: qtd, format: integer, label: Unidades}]
    y: [qtd]
    max_value: 8000
    width: 3
    height: 200

  - id: evolucao
    title: Evolução mensal
    viz: line
    source: {table: vendas}
    dimensions: [mes]
    measures: [{column: valor, agg: sum, name: faturamento, format: currency, label: Faturamento}]
    x: mes
    y: [faturamento]
    width: 8

  - id: produto-donut
    title: Participação por produto
    viz: donut
    source: {table: vendas}
    dimensions: [produto]
    measures: [{column: valor, agg: sum, name: faturamento, format: currency, label: Faturamento}]
    x: produto
    y: [faturamento]
    width: 4

  - id: por-regiao
    title: Faturamento por região
    viz: bar
    source: {table: vendas}
    dimensions: [regiao]
    measures: [{column: valor, agg: sum, name: faturamento, format: currency, label: Faturamento}]
    x: regiao
    y: [faturamento]
    sort: [{by: faturamento, dir: desc}]
    width: 4

  - id: regiao-produto
    title: Região × produto
    viz: stacked_bar
    source: {table: vendas}
    dimensions: [regiao, produto]
    measures: [{column: valor, agg: sum, name: faturamento, format: currency, label: Faturamento}]
    x: regiao
    series: produto
    y: [faturamento]
    width: 4

  - id: top-vendedores
    title: Top 10 vendedores
    viz: hbar
    source: {table: vendas}
    dimensions: [vendedor]
    measures: [{column: valor, agg: sum, name: faturamento, format: currency, label: Faturamento}]
    x: vendedor
    y: [faturamento]
    sort: [{by: faturamento, dir: desc}]
    top: 10
    width: 4

  - id: calor
    title: Mapa de calor — mês × região
    viz: heatmap
    source: {table: vendas}
    dimensions: [mes, regiao]
    measures: [{column: valor, agg: sum, name: faturamento, format: currency, label: Faturamento}]
    x: mes
    series: regiao
    y: [faturamento]
    width: 8

  - id: funil
    title: Funil por produto
    viz: funnel
    source: {table: vendas}
    dimensions: [produto]
    measures: [{column: quantidade, agg: sum, name: qtd, format: integer, label: Unidades}]
    x: produto
    y: [qtd]
    sort: [{by: qtd, dir: desc}]
    width: 4

  - id: arvore
    title: Treemap — região › produto
    viz: treemap
    source: {table: vendas}
    dimensions: [regiao, produto]
    measures: [{column: valor, agg: sum, name: faturamento, format: currency, label: Faturamento}]
    y: [faturamento]
    width: 6

  - id: cascata
    title: Contribuição por região (cascata)
    viz: waterfall
    source: {table: vendas}
    dimensions: [regiao]
    measures: [{column: valor, agg: sum, name: faturamento, format: currency, label: Faturamento}]
    x: regiao
    y: [faturamento]
    width: 6

  - id: dispersao
    title: Unidades × faturamento por vendedor
    viz: scatter
    source: {table: vendas}
    dimensions: [vendedor]
    measures:
      - {column: quantidade, agg: sum, name: qtd, format: integer, label: Unidades}
      - {column: valor, agg: sum, name: faturamento, format: currency, label: Faturamento}
    y: [qtd, faturamento]       # eixo X = primeira medida, eixo Y = segunda
    width: 6

  - id: area
    title: Faturamento acumulado por produto
    viz: area
    source: {table: vendas}
    dimensions: [mes, produto]
    measures: [{column: valor, agg: sum, name: faturamento, format: currency, label: Faturamento}]
    x: mes
    series: produto
    y: [faturamento]
    width: 6

  - id: pivot
    title: Tabela dinâmica — região × produto
    viz: pivot
    source: {table: vendas}
    dimensions: [regiao, produto]
    measures: [{column: valor, agg: sum, name: faturamento, format: currency, label: Faturamento}]
    rows: [regiao]
    columns: [produto]
    y: [faturamento]
    width: 12
    height: 300

  - id: detalhe
    title: Detalhamento
    viz: table
    source: {table: vendas}
    dimensions: [regiao, produto, vendedor]
    measures:
      - {column: valor, agg: sum, name: faturamento, format: currency, label: Faturamento}
      - {column: quantidade, agg: sum, name: qtd, format: integer, label: Unidades}
      - {column: valor, agg: avg, name: ticket, format: currency, label: Ticket médio}
    sort: [{by: faturamento, dir: desc}]
    width: 12
    height: 420
"""

NEW_DASHBOARD_YML = """\
title: __TITLE__
organization: __ORG__
description: Descreva o objetivo deste painel.
database: __DB__

filters: []

cards:
  - id: exemplo
    title: Exemplo
    viz: bar                 # {viz_types}
    source: {table: schema.tabela}
    dimensions: [coluna_de_categoria]
    measures:
      - {column: coluna_numerica, agg: sum, name: total, format: currency, label: Total}
    x: coluna_de_categoria
    y: [total]
"""

BUILD_WORKFLOW = """\
name: Publicar painéis

on:
  push:
    branches: [main]
  schedule:
    - cron: "0 9 * * 1-5"          # dias úteis, 09:00 UTC — ajuste à frequência dos seus dados
  workflow_dispatch:
  repository_dispatch:
    types: [data-updated]           # o servidor de dados pode disparar este evento (veja o README)

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: pages
  cancel-in-progress: true

jobs:
  build:
    runs-on: ubuntu-latest
    permissions:
      contents: write      # para gravar access.lock.json
      pages: write
      id-token: write
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pipx install poetry
      - run: poetry install --only main
      - name: Gerar o site
        run: poetry run uai build
        env:
          UAI_MASTER_KEY: ${{ secrets.UAI_MASTER_KEY }}
          UAI_DB_DEMO: ${{ secrets.UAI_DB_DEMO }}
          # UAI_DB_PRODUCAO: ${{ secrets.UAI_DB_PRODUCAO }}    # um por banco declarado em uai.yml
      - name: Registrar mudanças de acesso (access.lock.json)
        run: |
          if [ -n "$(git status --porcelain access.lock.json)" ]; then
            git config user.name "uai-data[bot]"
            git config user.email "uai-data@users.noreply.github.com"
            git add access.lock.json
            git commit -m "chore: atualiza access.lock.json [skip ci]"
            git push || echo "::warning::Não consegui gravar access.lock.json (proteção da branch?). Rode 'uai lock' localmente e envie o arquivo."
          fi
      - uses: actions/configure-pages@v5
      - uses: actions/upload-pages-artifact@v3
        with:
          path: site

  deploy:
    needs: build
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - id: deployment
        uses: actions/deploy-pages@v4
"""

GUARD_WORKFLOW = """\
name: Guarda de permissões

# pull_request_target roda o código da branch principal (confiável) — o código do PR nunca é executado.
on:
  pull_request_target:
    branches: [main]

permissions:
  contents: read

jobs:
  guard:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - name: Buscar o PR (somente como dados)
        run: git fetch origin "refs/pull/${{ github.event.number }}/head:pr-head"
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pipx install poetry
      - run: poetry install --only main
      - name: Conferir permissões do autor
        run: poetry run uai guard --base HEAD --head pr-head --actor "${{ github.event.pull_request.user.login }}"
"""

GITIGNORE = """\
site/
.venv/
.env
__pycache__/
*.pyc
"""

PYPROJECT = """\
[tool.poetry]
name = "__SLUG__"
version = "0.1.0"
description = "Painéis Uai Data"
authors = []
package-mode = false

[tool.poetry.dependencies]
python = ">=3.10,<4.0"
__UAI_DEP__
"""

CODEOWNERS = """\
# Complementa o guard: exige revisão de um administrador nos arquivos de acesso.
/access/ @__GITHUB__
/uai.yml @__GITHUB__
/.github/ @__GITHUB__
"""


def new_password() -> str:
    return secrets.token_urlsafe(12)


def create_demo_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    rng = random.Random(42)
    regioes = {"Sudeste": 1.6, "Sul": 1.2, "Nordeste": 1.0, "Centro-Oeste": 0.7, "Norte": 0.5}
    produtos = {"Notebook": 4200, "Monitor": 1300, "Teclado": 220, "Mouse": 120, "Headset": 410}
    vendedores = ["Ana", "Bruno", "Camila", "Diego", "Elisa", "Fábio", "Gabi", "Hugo", "Iara", "João", "Karen", "Léo"]
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE vendas (ano INTEGER, mes TEXT, regiao TEXT, produto TEXT, vendedor TEXT, "
        "valor NUMERIC, quantidade INTEGER)"
    )
    rows = []
    for ano in (2024, 2025):
        for m in range(1, 13):
            for _ in range(60):
                regiao = rng.choices(list(regioes), weights=list(regioes.values()))[0]
                produto = rng.choice(list(produtos))
                qtd = rng.randint(1, 8)
                preco = produtos[produto] * rng.uniform(0.85, 1.15) * (1 + 0.04 * (ano - 2024))
                rows.append((ano, f"{ano}-{m:02d}", regiao, produto, rng.choice(vendedores), round(preco * qtd, 2), qtd))
    con.executemany("INSERT INTO vendas VALUES (?,?,?,?,?,?,?)", rows)
    con.commit()
    con.close()


# ============================================================================ template SIAFI
SIAFI_UAI_YML = """\
# Configuração do site Uai Data — template SIAFI
name: __NAME__
tagline: Explore. Analise. Descubra.
repo: __REPO__            # dono/repositório no GitHub — habilita os botões "Editar" e "Novo painel"
branch: main
locale: pt-BR
currency: BRL
csv_sep: ";"
csv_decimal: ","
site_salt: __SALT__
site_admins: [__ADMIN__]

databases:
  siafi:
    dsn_env: UAI_DB_SIAFI     # URL do PostgreSQL. No Actions: banco temporário (veja o workflow). Local: docker compose up -d
    statement_timeout_s: 300

catalog_schemas: [public]
"""

SIAFI_EXEC = """\
title: Execução da despesa
organization: __ORG__
description: Empenhado, liquidado e pago da execução orçamentária, direto das bases do SIAFI.
database: siafi
tags: [despesa, siafi]

filters:
  - {column: mes_cod, label: Mês}
  - {column: uo_sigla, label: Unidade orçamentária}
  - {column: grupo_desc, label: Grupo de despesa}

cards:
  - id: empenhado
    title: Empenhado
    viz: number
    source: {table: execucao}
    measures: [{column: vlr_empenhado, agg: sum, name: empenhado, format: currency}]
    y: [empenhado]
    width: 4
    height: 170

  - id: liquidado
    title: Liquidado
    viz: number
    source: {table: execucao}
    measures: [{column: vlr_liquidado, agg: sum, name: liquidado, format: currency}]
    y: [liquidado]
    width: 4
    height: 170

  - id: pago
    title: Pago (orçamentário)
    viz: number
    source: {table: execucao}
    measures: [{column: vlr_pago_orcamentario, agg: sum, name: pago, format: currency}]
    y: [pago]
    width: 4
    height: 170

  - id: evolucao
    title: Evolução mensal
    viz: line
    source: {table: execucao}
    dimensions: [mes_cod]
    measures:
      - {column: vlr_empenhado, agg: sum, name: empenhado, format: currency, label: Empenhado}
      - {column: vlr_liquidado, agg: sum, name: liquidado, format: currency, label: Liquidado}
      - {column: vlr_pago_orcamentario, agg: sum, name: pago, format: currency, label: Pago}
    x: mes_cod
    y: [empenhado, liquidado, pago]
    width: 8

  - id: por-grupo
    title: Empenhado por grupo de despesa
    viz: donut
    source: {table: execucao}
    dimensions: [grupo_desc]
    measures: [{column: vlr_empenhado, agg: sum, name: empenhado, format: currency, label: Empenhado}]
    x: grupo_desc
    y: [empenhado]
    width: 4

  - id: top-uo
    title: 15 maiores unidades orçamentárias (empenhado)
    viz: hbar
    source: {table: execucao}
    dimensions: [uo_sigla]
    measures: [{column: vlr_empenhado, agg: sum, name: empenhado, format: currency, label: Empenhado}]
    x: uo_sigla
    y: [empenhado]
    sort: [{by: empenhado, dir: desc}]
    top: 15
    width: 6
    height: 420

  - id: top-funcao
    title: Empenhado por função
    viz: hbar
    source: {table: execucao}
    dimensions: [funcao_desc]
    measures: [{column: vlr_empenhado, agg: sum, name: empenhado, format: currency, label: Empenhado}]
    x: funcao_desc
    y: [empenhado]
    sort: [{by: empenhado, dir: desc}]
    top: 15
    width: 6
    height: 420

  - id: calor
    title: Liquidado por função e mês
    viz: heatmap
    source: {table: execucao}
    dimensions: [mes_cod, funcao_desc]
    measures: [{column: vlr_liquidado, agg: sum, name: liquidado, format: currency, label: Liquidado}]
    x: mes_cod
    series: funcao_desc
    y: [liquidado]
    filters: [grupo_desc, uo_sigla]
    width: 12
    height: 520

  - id: arvore
    title: Empenhado — função › grupo de despesa
    viz: treemap
    source: {table: execucao}
    dimensions: [funcao_desc, grupo_desc]
    measures: [{column: vlr_empenhado, agg: sum, name: empenhado, format: currency, label: Empenhado}]
    y: [empenhado]
    filters: [mes_cod, uo_sigla]
    width: 6
    height: 420

  - id: fonte
    title: Empenhado por fonte de recurso
    viz: donut
    source: {table: execucao}
    dimensions: [fonte_desc]
    measures: [{column: vlr_empenhado, agg: sum, name: empenhado, format: currency, label: Empenhado}]
    x: fonte_desc
    y: [empenhado]
    filters: [mes_cod, grupo_desc]
    width: 6
    height: 420

  - id: pivot
    title: Empenhado — grupo de despesa × mês
    viz: pivot
    source: {table: execucao}
    dimensions: [grupo_desc, mes_cod]
    measures: [{column: vlr_empenhado, agg: sum, name: empenhado, format: currency, label: Empenhado}]
    rows: [grupo_desc]
    columns: [mes_cod]
    y: [empenhado]
    filters: [uo_sigla]
    width: 12
    height: 320

  - id: detalhe
    title: Detalhamento por unidade, função e grupo
    viz: table
    source: {table: execucao}
    dimensions: [uo_sigla, funcao_desc, grupo_desc]
    measures:
      - {column: vlr_empenhado, agg: sum, name: empenhado, format: currency, label: Empenhado}
      - {column: vlr_liquidado, agg: sum, name: liquidado, format: currency, label: Liquidado}
      - {column: vlr_pago_orcamentario, agg: sum, name: pago, format: currency, label: Pago}
    sort: [{by: empenhado, dir: desc}]
    filters: [mes_cod]
    width: 12
    height: 460
"""

SIAFI_RECEITA = """\
title: Receita
organization: __ORG__
description: Previsão e arrecadação (valor contabilizado) por unidade, fonte e classificação da receita.
database: siafi
tags: [receita, siafi]

filters:
  - {column: mes_cod, label: Mês}
  - {column: uo_sigla, label: Unidade orçamentária}

cards:
  - id: previsto-inicial
    title: Previsto inicial
    viz: number
    source: {table: receita}
    measures: [{column: vlr_previsto_inicial, agg: sum, name: previsto_inicial, format: currency}]
    y: [previsto_inicial]
    width: 4
    height: 170

  - id: previsto-atualizado
    title: Previsto atualizado
    viz: number
    source: {table: receita}
    measures: [{column: vlr_previsto_atualizado, agg: sum, name: previsto_atualizado, format: currency}]
    y: [previsto_atualizado]
    width: 4
    height: 170

  - id: contabilizado
    title: Contabilizado
    viz: number
    source: {table: receita}
    measures: [{column: vlr_contabilizado, agg: sum, name: contabilizado, format: currency}]
    y: [contabilizado]
    width: 4
    height: 170

  - id: evolucao
    title: Arrecadação mensal (contabilizado)
    viz: area
    source: {table: receita}
    dimensions: [mes_cod]
    measures: [{column: vlr_contabilizado, agg: sum, name: contabilizado, format: currency, label: Contabilizado}]
    x: mes_cod
    y: [contabilizado]
    width: 8

  - id: fonte
    title: Contabilizado por fonte de recurso
    viz: donut
    source: {table: receita}
    dimensions: [fonte_desc]
    measures: [{column: vlr_contabilizado, agg: sum, name: contabilizado, format: currency, label: Contabilizado}]
    x: fonte_desc
    y: [contabilizado]
    filters: [mes_cod]
    width: 4

  - id: top-uo
    title: 15 maiores unidades (contabilizado)
    viz: hbar
    source: {table: receita}
    dimensions: [uo_sigla]
    measures: [{column: vlr_contabilizado, agg: sum, name: contabilizado, format: currency, label: Contabilizado}]
    x: uo_sigla
    y: [contabilizado]
    sort: [{by: contabilizado, dir: desc}]
    top: 15
    width: 6
    height: 420

  - id: top-receita
    title: 15 maiores classificações de receita
    viz: hbar
    source: {table: receita}
    dimensions: [receita_desc]
    measures: [{column: vlr_contabilizado, agg: sum, name: contabilizado, format: currency, label: Contabilizado}]
    x: receita_desc
    y: [contabilizado]
    sort: [{by: contabilizado, dir: desc}]
    top: 15
    filters: [mes_cod]
    width: 6
    height: 420

  - id: detalhe
    title: Detalhamento por classificação da receita
    viz: table
    source: {table: receita}
    dimensions: [receita_cod_formatado, receita_desc]
    measures:
      - {column: vlr_previsto_atualizado, agg: sum, name: previsto_atualizado, format: currency, label: Previsto atualizado}
      - {column: vlr_contabilizado, agg: sum, name: contabilizado, format: currency, label: Contabilizado}
    sort: [{by: contabilizado, dir: desc}]
    filters: [mes_cod]
    width: 12
    height: 460
"""

SIAFI_RP = """\
title: Restos a pagar
organization: __ORG__
description: Saldo de restos a pagar processados e não processados, por ano de origem e unidade.
database: siafi
tags: [restos a pagar, siafi]

filters:
  - {column: ano_rp, label: Ano de origem}
  - {column: uo_sigla, label: Unidade orçamentária}

cards:
  - id: saldo-rpp
    title: Saldo de restos a pagar processados
    viz: number
    source: {table: restos_pagar}
    measures: [{column: vlr_saldo_rpp, agg: sum, name: saldo_rpp, format: currency}]
    y: [saldo_rpp]
    width: 6
    height: 170

  - id: saldo-rpnp
    title: Saldo de restos a pagar não processados
    viz: number
    source: {table: restos_pagar}
    measures: [{column: vlr_saldo_rpnp, agg: sum, name: saldo_rpnp, format: currency}]
    y: [saldo_rpnp]
    width: 6
    height: 170

  - id: por-ano
    title: Saldo por ano de origem
    viz: bar
    source: {table: restos_pagar}
    dimensions: [ano_rp]
    measures:
      - {column: vlr_saldo_rpp, agg: sum, name: rpp, format: currency, label: Processados}
      - {column: vlr_saldo_rpnp, agg: sum, name: rpnp, format: currency, label: Não processados}
    x: ano_rp
    y: [rpp, rpnp]
    width: 7

  - id: top-uo
    title: 15 maiores saldos por unidade
    viz: hbar
    source: {table: restos_pagar}
    dimensions: [uo_sigla]
    measures: [{column: vlr_saldo_rpnp, agg: sum, name: rpnp, format: currency, label: Não processados}]
    x: uo_sigla
    y: [rpnp]
    sort: [{by: rpnp, dir: desc}]
    top: 15
    width: 5
    height: 420

  - id: detalhe
    title: Detalhamento por unidade e ano de origem
    viz: table
    source: {table: restos_pagar}
    dimensions: [uo_sigla, ano_rp]
    measures:
      - {column: vlr_inscrito_rpnp, agg: sum, name: inscrito, format: currency, label: Inscrito (não proc.)}
      - {column: vlr_saldo_rpp, agg: sum, name: rpp, format: currency, label: Saldo processados}
      - {column: vlr_saldo_rpnp, agg: sum, name: rpnp, format: currency, label: Saldo não processados}
    sort: [{by: rpnp, dir: desc}]
    width: 12
    height: 460
"""

SIAFI_WORKFLOW = """\
name: Publicar painéis

on:
  push:
    branches: [main]
  schedule:
    - cron: "0 9 * * 1-5"           # dias úteis, 09:00 UTC (06:00 em Brasília)
  workflow_dispatch:
  repository_dispatch:
    types: [data-updated]            # o servidor de dados pode disparar quando publicar dados novos

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: pages
  cancel-in-progress: true

jobs:
  build:
    runs-on: ubuntu-latest
    permissions:
      contents: write      # para gravar access.lock.json
      pages: write
      id-token: write
    services:
      postgres:                       # banco temporário: nasce, recebe os CSVs, alimenta o build e some
        image: postgres:16
        env:
          POSTGRES_PASSWORD: postgres
          POSTGRES_DB: siafi
        ports: ["5432:5432"]
        options: >-
          --health-cmd "pg_isready -U postgres" --health-interval 5s --health-timeout 5s --health-retries 10
    env:
      UAI_MASTER_KEY: ${{ secrets.UAI_MASTER_KEY }}
      UAI_DB_SIAFI: postgresql://postgres:postgres@localhost:5432/siafi
    steps:
      - uses: actions/checkout@v4
      - name: Baixar os dados do SIAFI
        uses: actions/checkout@v4
        with:
          repository: splor-mg/dados-siafi-2026
          path: dados
          token: ${{ secrets.DATA_REPO_TOKEN || github.token }}   # repositório privado: crie o secret DATA_REPO_TOKEN
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pipx install poetry
      - run: poetry install --only main
      - name: Carregar os dados no PostgreSQL
        run: poetry run uai load dados --database siafi --index mes_cod --index uo_sigla --index ano_rp
      - name: Gerar o site
        run: poetry run uai build
      - name: Registrar mudanças de acesso (access.lock.json)
        run: |
          if [ -n "$(git status --porcelain access.lock.json)" ]; then
            git config user.name "uai-data[bot]"
            git config user.email "uai-data@users.noreply.github.com"
            git add access.lock.json
            git commit -m "chore: atualiza access.lock.json [skip ci]"
            git push || echo "::warning::Não consegui gravar access.lock.json (proteção da branch?). Rode 'uai lock' localmente e envie o arquivo."
          fi
      - uses: actions/configure-pages@v5
      - uses: actions/upload-pages-artifact@v3
        with:
          path: site

  deploy:
    needs: build
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - id: deployment
        uses: actions/deploy-pages@v4
"""

DOCKER_COMPOSE = """\
# PostgreSQL local para desenvolver: docker compose up -d
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: siafi
    ports: ["5432:5432"]
    volumes: [pgdata:/var/lib/postgresql/data]
volumes:
  pgdata:
"""
