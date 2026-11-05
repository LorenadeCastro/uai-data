<p align="center"><img src="docs/logo.png" alt="Uai Data — Explore. Analise. Descubra." width="420"></p>

# Uai Data

Painéis de dados **open source**, **100% Python** e **sem servidor**, no estilo do Metabase: você descreve os
painéis em YAML, o GitHub Actions consulta o PostgreSQL, cifra os resultados e publica um site estático no
GitHub Pages — com login e senha, organizações, perfis de permissão e exportação para Excel, PDF e CSV.

```
PostgreSQL ──▶ GitHub Actions (uai build) ──▶ GitHub Pages (site estático, dados cifrados)
                    ▲                                   │
         painéis em YAML (Git)                 login no navegador (Web Crypto)
```

| | |
|---|---|
| Linguagem | Python (≥ 3.10). O navegador roda cerca de mil linhas de JavaScript, sem etapa de build, distribuídas junto com o pacote |
| Banco | PostgreSQL (SQLAlchemy + psycopg 3). SQLite para testes |
| Hospedagem | GitHub Pages + GitHub Actions. Nenhum servidor |
| Gestão de dependências | Poetry |
| Acesso | Login e senha, organizações com administradores, perfis (`viewer`, `analyst`, `editor` ou os seus) |
| Visualizações | número, velocímetro, barras (vertical, horizontal, empilhada), linha, área, dispersão, pizza, rosca, mapa de calor, funil, treemap, cascata, tabela e tabela dinâmica |
| Saídas | Excel (.xlsx), PDF, CSV, PNG, impressão e link de compartilhamento |

## Início rápido (2 minutos, sem PostgreSQL)

```bash
git clone https://github.com/SEU-USUARIO/uai-data && cd uai-data
poetry install
poetry run uai init ../meus-paineis --admin voce --admin-name "Seu Nome" --github seu-usuario-github \
    --uai-git https://github.com/SEU-USUARIO/uai-data.git      # de onde o projeto novo instala o Uai Data
cd ../meus-paineis
poetry install
poetry run uai serve        # http://localhost:8000
```

`--uai-git` aceita a URL do repositório (ou um caminho local, como `../uai-data`, para desenvolver). Quando o pacote
estiver no PyPI, basta omiti-lo.

O `init` cria um projeto completo com um painel de demonstração (16 tipos de visualização), três usuários de exemplo
(editora, analista e leitora, com senhas aleatórias mostradas uma única vez) e os workflows do GitHub.

## Usando com PostgreSQL: exemplo com os dados do SIAFI

O template `siafi` usa o repositório [`splor-mg/dados-siafi-2026`](https://github.com/splor-mg/dados-siafi-2026)
(execução da despesa, receita, restos a pagar e outras bases):

```bash
poetry run uai init paineis-siafi --template siafi --admin voce --github seu-usuario-github \
    --repo sua-org/paineis-siafi --uai-git https://github.com/SEU-USUARIO/uai-data.git
cd paineis-siafi && poetry install
docker compose up -d                                    # PostgreSQL local
git clone https://github.com/splor-mg/dados-siafi-2026 ../dados-siafi-2026
poetry run uai load ../dados-siafi-2026 --database siafi    # 1,2 milhão de linhas em ~10 s (COPY)
poetry run uai check --connect                          # roda cada card e mostra linhas e tempo
poetry run uai serve
```

Na publicação, o workflow gerado sobe um PostgreSQL temporário dentro do Actions, baixa o repositório de dados
(`DATA_REPO_TOKEN` se for privado), carrega, gera o site e descarta o banco. Para usar um PostgreSQL seu, aponte
`UAI_DB_SIAFI` para ele e remova as etapas de carga.

## Publicando no GitHub

1. Crie o repositório, envie o projeto e vá em **Settings → Pages → Source: GitHub Actions**.
2. Em **Settings → Secrets and variables → Actions**, crie `UAI_MASTER_KEY` (o `init` mostra o valor; `uai keygen`
   gera outro) e a URL de cada banco (`UAI_DB_...`, formato `postgresql://usuario:senha@host:5432/banco`).
3. Ative a proteção da `main` (veja [SECURITY.md](SECURITY.md)). Pronto: a cada push, todo dia útil às 06:00 (horário de
   Brasília) ou quando o servidor de dados avisar, o site é refeito.

Para o servidor de dados avisar que há dados novos:

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Accept: application/vnd.github+json" \
  https://api.github.com/repos/SUA-ORG/SEU-REPO/dispatches -d '{"event_type":"data-updated"}'
```

## Pessoas, organizações e permissões

Cada **organização** tem pelo menos um **administrador**, que decide o que cada pessoa pode fazer por meio de
**perfis**:

| Permissão | Quer dizer |
|---|---|
| `view` | ver os painéis |
| `download` | baixar Excel, PDF, CSV e PNG |
| `share` | gerar link de compartilhamento (somente leitura) |
| `create` | criar painéis novos e explorar as tabelas do banco |
| `edit` | editar painéis existentes |

```bash
uai user add maria --name "Maria Souza" --github maria-souza     # login e senha
uai org create financas --name "Finanças" --admin maria --database siafi
uai org member financas joao analyst                             # joao passa a ser 'analyst'
uai org profile financas auditor --perm view --perm download     # perfil novo
uai org admin financas joao                                      # mais um administrador
uai org remove financas joao                                     # a chave dos painéis é trocada no próximo build
uai user passwd maria                                            # a própria pessoa troca a senha
uai user reset maria                                             # administrador redefine quem esqueceu
```

Um painel pode ser `private: true` (só quem for listado em `access.grants`, além dos administradores) ou dar
permissões extras a uma pessoa ou perfil (`@analyst`). Detalhes em [docs/referencia.md](docs/referencia.md).

No navegador, o administrador vê a página **Pessoas e permissões**, e quem tem `create` vê **Explorar dados**
(tabelas e colunas, nunca os dados) com o botão **Criar painel com esta tabela**.

## Um painel em YAML

```yaml
title: Execução da despesa
organization: splor
database: siafi
filters:
  - {column: mes_cod, label: Mês}
  - {column: grupo_desc, label: Grupo de despesa}
cards:
  - id: empenhado
    title: Empenhado
    viz: number
    source: {table: execucao}
    measures: [{column: vlr_empenhado, agg: sum, name: empenhado, format: currency}]
    y: [empenhado]
    width: 4
  - id: evolucao
    title: Evolução mensal
    viz: line
    source: {table: execucao}
    dimensions: [mes_cod]
    measures:
      - {column: vlr_empenhado, agg: sum, name: empenhado, format: currency, label: Empenhado}
      - {column: vlr_liquidado, agg: sum, name: liquidado, format: currency, label: Liquidado}
    x: mes_cod
    y: [empenhado, liquidado]
    width: 8
```

Sem SQL: você descreve dimensões e medidas e o Uai Data monta a consulta. Os filtros do painel reagrupam os dados
**no navegador**, sem nova consulta ao banco. Valores monetários sempre aparecem com centavos, na tela e no Excel.

## Baixar e compartilhar

* **Baixar ▾**: Excel e PDF do painel inteiro (sem filtros de tela), imprimir/salvar PDF da tela (com filtros) e CSV de todos os cards.
* Em cada card: **Ver tabela**, **CSV** (com os filtros atuais, pronto para o Excel brasileiro: `;` e vírgula decimal) e **PNG**.
* **Compartilhar**: gera um link que abre o painel, somente para ver, sem usuário nem senha. A chave vai no fragmento da URL
  (depois do `#`), que o navegador não envia a servidor nenhum. Aumente `share_epoch` para desativar links antigos.

## Comandos

| Comando | O que faz |
|---|---|
| `uai init` | cria um projeto (`--template demo` ou `siafi`) |
| `uai check [--connect]` | valida a configuração e, com `--connect`, executa cada card |
| `uai load PACOTE -d BANCO` | carrega um Data Package (CSV e CSV.GZ) no banco |
| `uai build` | consulta o banco e gera o site em `site/` |
| `uai serve` | gera e serve em `localhost:8000` |
| `uai user add/passwd/reset/list` | usuários |
| `uai org create/member/admin/remove/profile/list` | organizações e perfis |
| `uai dashboard new org/nome` | cria o arquivo de um painel |
| `uai lock` | atualiza `access.lock.json` (o workflow já faz isso sozinho) |
| `uai guard` | confere permissões de um pull request (usado no CI) |
| `uai keygen` | gera um `UAI_MASTER_KEY` |

## Segurança, em uma frase

Os dados publicados estão cifrados e só abrem para quem tem permissão, mas **quem pode ver pode copiar**, e a força da
senha importa. Leia o [SECURITY.md](SECURITY.md) antes de colocar dados sensíveis.

## Desenvolvimento

```bash
poetry install
poetry run pytest                                    # 25 testes; inclui o JavaScript lendo o que o Python gerou
UAI_TEST_PG=postgresql://postgres:postgres@localhost:5432/postgres poetry run pytest   # inclui o COPY no PostgreSQL
poetry run ruff check .
```

Estrutura: `src/uai_data/` (`config`, `crypto`, `access`, `queries`, `builder`, `exports`, `guard`, `loader`, `cli`) e
`src/uai_data/web/` (o aplicativo do navegador: `app.js`, `viz.js`, `data.js`, `crypto.js`).

## Licença

MIT. Veja [LICENSE](LICENSE).
