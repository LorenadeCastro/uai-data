# Segurança no Uai Data

O Uai Data não tem servidor. Isso muda o que "login" e "permissão" significam, e é importante saber
exatamente o que é garantido e o que não é.

## Como o login funciona

O site publicado no GitHub Pages é público (qualquer um que souber a URL baixa os arquivos), mas **os dados
dos painéis só existem cifrados**:

```
senha ──PBKDF2-SHA256 (600 mil iterações)──▶ chave ──AES-256-GCM──▶ chave privada RSA-3072 do usuário
                                                                        │ RSA-OAEP-SHA256
                                                                        ▼
                                                 chave de dados (DK) de cada painel autorizado
                                                                        │ AES-256-GCM
                                                                        ▼
                                                 dados do painel (um arquivo por card)
```

* A senha nunca é gravada nem enviada: ela só abre a chave privada **dentro do navegador**.
  Senha errada falha na verificação do AES-GCM.
* No build, o Uai Data entrega a DK de cada painel apenas aos usuários autorizados (cifrada com a chave
  pública deles). Quem não tem permissão não tem a chave: mesmo baixando todos os arquivos do site, não lê nada.
* As chaves dos painéis são derivadas (HKDF) de um segredo do projeto, o `UAI_MASTER_KEY`, que vive
  só no GitHub Secrets. Os nomes de pastas e arquivos do site são identificadores opacos.

## O que cada permissão garante

| Permissão | Garantia | Como |
|---|---|---|
| `view` | **Criptográfica** | Sem a chave do painel não há como ler os dados. |
| `download` (xlsx/pdf) | **Criptográfica** | Excel e PDF usam uma chave própria, entregue só a quem tem `download`. |
| `download` (csv/png da tela) | Interface | Quem vê os dados consegue copiá-los; esconder o botão não impede. |
| `share` | Interface | O link contém a chave do painel e abre em modo leitura. Quem tem `view` consegue montar o link manualmente. |
| `create` / `edit` | **Verificada no CI** | Mudanças em painéis são pull requests; o *guard* confere o autor com as regras da branch principal. |
| Administrar a organização | **Verificada no CI** | Só o administrador altera `access/<org>.yml` e as permissões de um painel. |

> Em resumo: **quem pode ver pode copiar**. Use `view` com a mesma cautela que daria a alguém acesso de
> leitura ao banco.

## Revogação

Remover alguém de uma organização (ou tirar a permissão) **troca a chave do painel** no próximo build
(`access.lock.json` registra a "época" da chave). O que a pessoa já baixou ou guardou continua com ela, mas ela não
abre os dados novos. Para invalidar links de compartilhamento, aumente `share_epoch` no painel.

## Limites que você precisa conhecer

1. **Senha fraca é o elo mais fraco.** Os arquivos de login são públicos; um atacante pode tentar adivinhar a
   senha offline. O PBKDF2 encarece cada tentativa, mas não salva "123456". Exija frases longas (a CLI recusa
   senhas com menos de 10 caracteres).
2. **O site é público**: quem souber a URL vê que existe um Uai Data, o tamanho dos arquivos e a quantidade de
   usuários. Nomes de usuário não aparecem (o nome do arquivo de login é um hash com `site_salt`).
3. **Edição é via Git.** Não há editor dentro do navegador; os botões "Editar" e "Novo painel" abrem o editor do
   GitHub. Para as regras valerem, ative a proteção da branch principal (veja abaixo).
4. **Dados em tempo quase real, não real.** Painéis refletem o último build (agendado, manual ou disparado por
   `repository_dispatch`).
5. **Perdeu o `UAI_MASTER_KEY`?** Gere outro (`uai keygen`) e publique: todos os painéis são recifrados e os links de
   compartilhamento antigos deixam de funcionar. Nada mais se perde.
6. **Esqueceu a senha?** Um administrador roda `uai user reset LOGIN`. Como a chave privada é cifrada pela senha,
   isso gera um novo par de chaves; no próximo build a pessoa volta a ter acesso a tudo.
7. **Consultas nativas (`sql:`)** só rodam em organizações com `allow_sql: true`, sempre em transação
   somente leitura e com *timeout*. Mesmo assim, use um usuário de banco com acesso restrito (só `SELECT`).

## Configuração recomendada do repositório

* **Settings → Branches → proteção da `main`**: exigir pull request, exigir o check **Guarda de permissões** e exigir
  revisão de *code owners* (o `CODEOWNERS` gerado pelo `uai init` cobre `access/`, `uai.yml` e `.github/`).
* **Secrets**: `UAI_MASTER_KEY` e a(s) URL(s) do banco (`UAI_DB_*`). Nunca coloque senhas de banco em `uai.yml`.
* Se a `main` for protegida, permita que o `github-actions[bot]` grave `access.lock.json` (ou rode `uai lock` e
  envie o arquivo junto com mudanças de acesso).
* O workflow `guard.yml` usa `pull_request_target` **sem executar código do PR**: ele só lê os arquivos do PR como
  dados. Não altere isso.

## Reportar vulnerabilidades

Abra um *security advisory* privado no repositório ou escreva para os mantenedores. Não publique detalhes antes de
haver correção.
