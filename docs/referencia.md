# Referência dos arquivos YAML

```
uai.yml                      configuração do site e dos bancos
access/users.yml             usuários (gerado por `uai user add`; não edite as chaves)
access/<organizacao>.yml     administradores, perfis e membros de uma organização
access.lock.json             épocas das chaves (gravado pelo workflow; não edite)
dashboards/<org>/<painel>.yml
```

## uai.yml

| Campo | Padrão | Descrição |
|---|---|---|
| `name`, `tagline` | Uai Data | nome e lema exibidos no site |
| `repo`, `branch` | — , `main` | `dono/repositorio`; habilita os botões **Editar** e **Novo painel** |
| `locale`, `currency` | `pt-BR`, `BRL` | formatação de números e moeda |
| `csv_sep`, `csv_decimal` | `;`, `,` | CSV para o Excel brasileiro |
| `site_salt` | obrigatório | evita adivinhar os nomes dos arquivos de login (não é segredo) |
| `site_admins` | `[]` | administradores do site: criam organizações e alteram a configuração |
| `databases.<nome>.dsn_env` | — | **nome** da variável de ambiente (secret) com a URL do banco |
| `databases.<nome>.statement_timeout_s` | 120 | tempo máximo de cada consulta |
| `catalog_schemas` | `[public]` | schemas listados em **Explorar dados** |
| `max_rows_per_card` | 50000 | teto de linhas por card (erro claro se passar) |
| `pbkdf2_iterations` | 600000 | custo da senha dos novos usuários |

## access/<organizacao>.yml

```yaml
name: Finanças
admins: [maria]                    # pelo menos um; têm todas as permissões
databases: [siafi]                 # bancos que os painéis da organização podem consultar
allow_sql: false                   # true libera cards com `sql:`
profiles:
  viewer:  [view]
  analyst: [view, download, share]
  editor:  [view, download, share, create, edit]
  auditor: [view, download]        # perfis seus
members:
  joao: analyst
  ana: editor
```

Permissões: `view`, `download`, `share`, `create`, `edit`.

## dashboards/<org>/<painel>.yml

| Campo | Descrição |
|---|---|
| `title`, `description`, `tags` | texto do painel |
| `organization` | precisa ser o nome da pasta |
| `database` | nome em `uai.yml → databases` (e liberado na organização) |
| `filters` | lista de `{column, label, type: select\|text}`; valem para os cards que têm a coluna |
| `access.private` | `true`: só os listados em `grants` e os administradores veem |
| `access.grants` | `{maria: [view, edit], "@analyst": [view]}` — permissões extras por pessoa ou perfil (`@perfil`) |
| `share_epoch` | aumente para invalidar links de compartilhamento já enviados |
| `cards` | lista de cards |

### Card

| Campo | Descrição |
|---|---|
| `id`, `title`, `description` | `id` em minúsculas, números, `-` e `_` |
| `viz` | tipo de visualização (tabela abaixo) |
| `source` | `{table: schema.tabela}` ou `{sql: "select ..."}` (só com `allow_sql`) |
| `dimensions` | colunas de agrupamento |
| `measures` | `{column, agg, name, label, format}` — `agg`: `sum`, `count`, `avg`, `min`, `max`, `count_distinct`; `format`: `currency`, `number`, `integer`, `percent`, `text`. `count` sem `column` conta linhas |
| `where` | `[{column, op, value}]` — `op`: `=`, `!=`, `>`, `>=`, `<`, `<=`, `in`, `not_in`, `like`, `is_null`, `not_null`, `between` |
| `x`, `series`, `y` | quais dimensões/medidas desenhar (`y` usa o `name` das medidas) |
| `rows`, `columns` | só para `pivot` |
| `sort`, `top` | `[{by, dir: asc\|desc}]` e limite de linhas |
| `max_value` | só para `gauge` |
| `width` (1–12), `height` (px) | tamanho na grade de 12 colunas |
| `filters` | `all` (padrão), `none` ou lista das colunas de filtro que o card acompanha |

> **Filtros e tamanho**: para o filtro funcionar sem consultar o banco, o card guarda um agrupamento por *dimensões + colunas
> de filtro*. Em cards com muitas dimensões, limite `filters: [coluna, ...]` para manter o card pequeno.
> `count_distinct` não pode ser reagrupado no navegador: use `filters: none` nesse card.

### Visualizações

| `viz` | Precisa de |
|---|---|
| `number` | 1 medida em `y` |
| `gauge` | 1 medida em `y` e `max_value` |
| `bar`, `hbar`, `line`, `area` | `x` (dimensão) e `y` (1 ou mais medidas) ou `series` (1 medida) |
| `stacked_bar` | `x`, `series` e 1 medida em `y` |
| `scatter` | 2 medidas em `y` (eixo X e eixo Y); 1 dimensão rotula os pontos |
| `pie`, `donut`, `funnel`, `waterfall` | `x` e 1 medida em `y` |
| `heatmap` | `x`, `series` e 1 medida em `y` |
| `treemap` | 1 ou mais dimensões (hierarquia, na ordem) e 1 medida em `y` |
| `table` | qualquer combinação; ordena clicando nos títulos |
| `pivot` | `rows`, `columns` e 1 medida em `y` (com totais quando a medida é soma) |

Mais de 8 categorias em uma série de cores viram "Outros" (nunca uma 9ª cor).
