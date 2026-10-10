#!/usr/bin/env bash
# SSH forced command for the CI deploy key: the only thing that key can do on the server.
#
# Installed by Ansible (roles/app) as /usr/local/bin/reluai-deploy-gate, owned by root, and
# bound to the CI key in the deploy user's authorized_keys:
#
#   command="/usr/local/bin/reluai-deploy-gate",restrict ssh-ed25519 AAAA... reluai-ci-deploy
#
# Whatever the client asks to run arrives in SSH_ORIGINAL_COMMAND and is never executed. The
# one accepted request is
#
#   deploy <40-character commit SHA>
#
# and the commit must already be on the main branch of the GitHub repository. Everything else
# is refused and logged. So a leaked CI key can at most redeploy code that is already on
# main: no shell, no other commands, no port or agent forwarding, no unreviewed commits.
#
# Changing this file in the repository has no effect on a server until Ansible is run again.
set -euo pipefail

readonly ROOT=/opt/reluai
readonly BRANCH=main
readonly TAG=reluai-deploy-gate
client="${SSH_CLIENT:-local}"
client="${client%% *}"

log() { logger -t "${TAG}" -- "$*" 2> /dev/null || true; }
refuse() {
  log "refused: $1 (client ${client})"
  echo "refused: $1" >&2
  exit 1
}

request="${SSH_ORIGINAL_COMMAND:-}"
if [[ ! "${request}" =~ ^deploy\ ([0-9a-f]{40})$ ]]; then
  refuse "unsupported command '${request:0:120}'; only 'deploy <commit sha>' is allowed"
fi
sha="${BASH_REMATCH[1]}"

# One deploy at a time, whether it comes from CI or from someone on the server.
exec 9> /run/lock/reluai-deploy.lock
flock -n 9 || refuse "another deploy is already running"

cd "${ROOT}"
# Repository hooks are switched off so nothing in .git can run as part of the checkout.
git_() { git -c core.hooksPath=/dev/null "$@"; }

git_ fetch --quiet origin "${BRANCH}"
git_ cat-file -e "${sha}^{commit}" 2> /dev/null || refuse "unknown commit ${sha}"
git_ merge-base --is-ancestor "${sha}" "origin/${BRANCH}" \
  || refuse "commit ${sha} is not on ${BRANCH}"

log "deploying ${sha} (client ${client})"
git_ -c advice.detachedHead=false checkout --quiet --detach "${sha}"
exec "${ROOT}/infra/scripts/deploy.sh" "${sha}"
