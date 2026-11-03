#!/usr/bin/env bash
# Orquestrador do testkit.
#
#   testkit/bin/run-all.sh                 -> roda tudo que estiver habilitado/detectado
#   testkit/bin/run-all.sh node python     -> roda só as verificações escolhidas
#   testkit/bin/run-all.sh --detect        -> mostra (JSON) o que seria executado
#   testkit/bin/run-all.sh --validate      -> valida testkit.config.json
#
# Verificações: node python security links web lighthouse api
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
CHECKS_DIR="$KIT_DIR/bin/checks"

detect_all() {
  local list=()
  is_enabled node detect_node && list+=(node)
  is_enabled python detect_python && list+=(python)
  list+=(security)
  [[ "$(cfg links.enabled true)" == "true" ]] && list+=(links)
  if is_enabled web detect_web; then
    list+=(web)
    [[ "$(cfg web.performance.lighthouse.enabled true)" == "true" ]] && list+=(lighthouse)
  fi
  is_enabled api detect_api && list+=(api)
  echo "${list[@]}"
}

case "${1:-}" in
  --validate) exec "$PYTHON_BIN" "$KIT_DIR/bin/lib/config.py" validate ;;
  --detect)
    read -r -a found <<< "$(detect_all)"
    "$PYTHON_BIN" -c 'import json,sys; print(json.dumps(sys.argv[1:]))' "${found[@]}"
    exit 0 ;;
  -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
esac

if [[ $# -gt 0 ]]; then checks=("$@"); else read -r -a checks <<< "$(detect_all)"; fi
log "Projeto: $PROJECT_ROOT"
log "Verificações: ${checks[*]}"
: > "$SUMMARY_FILE"

"$PYTHON_BIN" "$KIT_DIR/bin/lib/config.py" validate || exit 2

overall=0
for check in "${checks[@]}"; do
  echo; log "════════ $check ════════"
  case "$check" in
    node)           bash "$CHECKS_DIR/node.sh" ;;
    python)         bash "$CHECKS_DIR/python.sh" ;;
    security)       bash "$CHECKS_DIR/security.sh" ;;
    links)          bash "$CHECKS_DIR/links.sh" ;;
    web)            bash "$CHECKS_DIR/web-e2e.sh" ;;
    lighthouse)     bash "$CHECKS_DIR/lighthouse.sh" ;;
    api)            bash "$CHECKS_DIR/api-contract.sh" ;;
    *) fail_msg "verificação desconhecida: $check"; false ;;
  esac || overall=1
done

echo
if [[ $overall -eq 0 ]]; then ok_msg "Todas as verificações passaram."; else fail_msg "Há verificações com falha (veja $SUMMARY_FILE)."; fi
exit $overall
