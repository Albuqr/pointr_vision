#!/usr/bin/env bash
# Instala o testkit em um projeto.
#   bash install.sh /caminho/do/projeto [--ci github|gitlab|none] [--force]
# Copia o kit para <projeto>/testkit, cria testkit.config.json e .env.testkit (se não existirem),
# adiciona segredos e relatórios ao .gitignore e instala o workflow de CI.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET=""; CI_PROVIDER="github"; FORCE=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --ci) CI_PROVIDER="$2"; shift 2 ;;
    --force) FORCE=1; shift ;;
    -h|--help) sed -n '2,6p' "$0"; exit 0 ;;
    *) TARGET="$1"; shift ;;
  esac
done
[[ -n "$TARGET" ]] || { echo "uso: bash install.sh /caminho/do/projeto [--ci github|gitlab|none] [--force]"; exit 2; }
TARGET="$(cd "$TARGET" && pwd)"
DEST="$TARGET/testkit"

if [[ -d "$DEST" && $FORCE -eq 0 ]]; then
  echo "[testkit] $DEST já existe. Use --force para atualizar (sua configuração na raiz não é tocada)."
  exit 1
fi

echo "[testkit] Copiando kit para $DEST"
mkdir -p "$DEST"
# Copia tudo exceto dependências locais e o próprio instalador.
tar -C "$SRC" --exclude='./web/node_modules' --exclude='./.bin' --exclude='./install.sh' -cf - . | tar -C "$DEST" -xf -
chmod +x "$DEST"/bin/*.sh "$DEST"/bin/checks/*.sh "$DEST"/bin/lib/*.py

if [[ ! -f "$TARGET/testkit.config.json" ]]; then
  # Configuração inicial mínima conforme o que foi detectado.
  python3 - "$TARGET" <<'PY'
import json, os, sys, pathlib
root = pathlib.Path(sys.argv[1])
cfg = {"$comentario": "Veja testkit/testkit.config.example.json e testkit/examples/ para todas as opções.",
       "project": {"name": root.name}}
pkg = root / "package.json"
if pkg.exists():
    scripts = json.loads(pkg.read_text()).get("scripts", {})
    start = "start" if "start" in scripts else ("dev" if "dev" in scripts else None)
    has_ui = any(d in json.loads(pkg.read_text()).get("dependencies", {}) for d in ("react", "vue", "next", "svelte", "@angular/core", "express", "fastify", "nuxt", "astro"))
    if start and has_ui:
        cfg["web"] = {"baseUrl": "${TESTKIT_BASE_URL:-http://localhost:3000}", "startCommand": f"npm run {start}", "publicPages": ["/"]}
cfg["auth"] = {"strategy": "none", "roles": []}
(root / "testkit.config.json").write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")
print("[testkit] testkit.config.json criado")
PY
fi
[[ -f "$TARGET/.env.testkit" ]] || { cp "$SRC/env.testkit.example" "$TARGET/.env.testkit.example"; echo "[testkit] .env.testkit.example criado (copie para .env.testkit e preencha)"; }

touch "$TARGET/.gitignore"
for line in ".env.testkit" "testkit-reports/" "testkit/web/node_modules/" "testkit/.bin/"; do
  grep -qxF "$line" "$TARGET/.gitignore" || echo "$line" >> "$TARGET/.gitignore"
done

case "$CI_PROVIDER" in
  github)
    mkdir -p "$TARGET/.github/workflows"
    if [[ -f "$TARGET/.github/workflows/testkit.yml" && $FORCE -eq 0 ]]; then echo "[testkit] workflow já existe, mantido"
    else cp "$SRC/ci/github/testkit.yml" "$TARGET/.github/workflows/testkit.yml"; echo "[testkit] .github/workflows/testkit.yml instalado"; fi ;;
  gitlab)
    echo "[testkit] Adicione ao .gitlab-ci.yml:"; echo "  include:"; echo "    - local: testkit/ci/gitlab/testkit.gitlab-ci.yml" ;;
  none) ;;
  *) echo "[testkit] --ci deve ser github, gitlab ou none"; exit 2 ;;
esac

echo
echo "[testkit] Pronto. Próximos passos:"
echo "  1. Ajuste testkit.config.json (exemplos em testkit/examples/)"
echo "  2. Preencha .env.testkit com contas de teste e cole o conteúdo no segredo TESTKIT_ENV do CI"
echo "  3. Rode: bash testkit/bin/run-all.sh --validate && bash testkit/bin/run-all.sh"
