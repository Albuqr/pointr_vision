# Testkit — verificações do Pointr

Esta cópia acompanha o projeto. A configuração está em `testkit.config.json` na raiz,
sobreposta aos padrões de `testkit/defaults.json`. Os testes de navegador usam páginas
públicas, sem login ou papéis. Requisitos: Bash, Python 3.10+ e Node 22.12+.

## Grupos disponíveis

| Grupo | Verificações | Ferramentas |
|---|---|---|
| `python` | lint, formatação, tipos, testes, cobertura, SAST e dependências, conforme configuração | ruff, mypy, pytest, bandit, pip-audit |
| `security` | segredos no histórico, análise estática e dependências vulneráveis | gitleaks, semgrep, osv-scanner |
| `links` | links da documentação Markdown | lychee/linkinator |
| `web` | fumaça, acessibilidade, segurança HTTP, responsividade, performance e links internos | Playwright, axe-core |
| `lighthouse` | orçamentos de performance, acessibilidade, boas práticas e SEO | Lighthouse CI |
| `api` | contrato OpenAPI e robustez | Schemathesis |
| `node` | instalação, lint, formatação, tipos, testes e build | scripts do projeto |

Os scripts `node` e `api` continuam disponíveis para execução explícita ou detecção,
mas não têm jobs no workflow deste projeto. `web` e `lighthouse` ficam para o Stage 5.

## Uso

```bash
bash testkit/bin/run-all.sh --validate
bash testkit/bin/run-all.sh --detect
bash testkit/bin/run-all.sh links           # apenas o grupo escolhido
```

Sem argumentos, o orquestrador executa os grupos habilitados/detectados. Neste repo,
os testes devem ser direcionados aos arquivos alterados e seus importadores (D-062);
a suíte completa só roda quando solicitada pelo desenvolvedor.

Para verificar a compilação e descobrir os testes de navegador sem iniciar o app:

```bash
cd testkit/web
npm ci
npm run typecheck
npx playwright test --list
```

Para iniciar apenas um teste contra um app de teste já disponível, a partir da raiz:

```bash
export TESTKIT_BASE_URL=http://localhost:3000
bash testkit/bin/checks/web-e2e.sh smoke.spec.ts --project=chromium
```

O script instala as dependências e os navegadores configurados antes de testar.
Para Lighthouse, use `bash testkit/bin/run-all.sh lighthouse` com a mesma URL.

## Configuração

Declare em `testkit.config.json` apenas os valores que mudam em relação a
`testkit/defaults.json`. Strings aceitam `${VARIAVEL}` e `${VARIAVEL:-padrão}`;
chaves que começam com `$` são comentários.

- **Páginas:** `web.publicPages` alimenta fumaça, acessibilidade, responsividade,
  performance, CORS, conteúdo misto e a fila inicial da varredura de links.
- **App local:** configure `web.baseUrl`, `web.startCommand` e, opcionalmente,
  `web.setupCommand`, `web.readyPath` e `web.startTimeoutSeconds`. O kit inicia o app,
  espera a URL ficar pronta e encerra o processo ao final.
- **App já iniciado:** `TESTKIT_BASE_URL` sobrescreve `web.baseUrl` e dispensa iniciar o app.
- **Navegadores:** `web.browsers` seleciona Chromium, Firefox e/ou WebKit.
  `TESTKIT_CHROMIUM_PATH` permite usar um Chromium já instalado.
- **Checks:** `web.checks.<grupo>: false` desliga um grupo. Ajustes adicionais ficam em
  `web.accessibility`, `web.security`, `web.responsive`, `web.performance` e `web.crawl`.
- **Erros conhecidos:** `web.ignoreConsoleErrors` e `web.ignoreRequestFailures` aceitam regex.
- **Comandos:** `python.commands.<etapa>` e `node.commands.<etapa>` substituem comandos;
  `null` desliga a etapa. `python.coverageMin` define a cobertura mínima.
- **API:** configure `api.openapi` e, opcionalmente, `api.baseUrl`. O cabeçalho livre
  `TESTKIT_API_AUTH_HEADER` continua disponível; não há criação de sessão pelo kit.

Variáveis locais podem ficar em `.env.testkit` (ignorado pelo Git), seguindo
`testkit/env.testkit.example`. Variáveis já definidas no ambiente têm precedência.

## CI e relatórios

O workflow está em `../.github/workflows/testkit.yml`: valida e detecta os grupos,
depois executa `python`, `security`, `links`, `web` e `lighthouse` quando aplicável.
`TESTKIT_BASE_URL` pode ser definida nas variáveis do GitHub ou na execução manual.
O segredo opcional `TESTKIT_ENV` fornece o conteúdo de `.env.testkit`.

Relatórios ficam em `testkit-reports/`: resumo Markdown, JUnit, cobertura, SARIF,
Lighthouse, log do servidor e relatório HTML do Playwright com artefatos de falha.
No CI, os jobs que geram artefatos os publicam em Artifacts.

## Limitações

- Segurança HTTP e performance devem usar o build de produção: servidores de
  desenvolvimento podem omitir cabeçalhos ou servir JavaScript sem otimização.
- Schemathesis envia requisições reais, inclusive escrita. Use um ambiente de teste;
  `DELETE` fica excluído por padrão.
- A varredura ignora links de saída e exclusão configurados em `web.crawl.excludePatterns`.
- Esta cópia foi reduzida para o Pointr. Uma futura sincronização com o kit original
  pode restaurar os recursos removidos; revisar o diff continua necessário.
