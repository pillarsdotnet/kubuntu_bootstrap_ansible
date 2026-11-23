# shellcheck shell=bash  # sourced fragment, not a script: no shebang by design
# Load ble.sh without attaching. The guard is $- (shell flags), not $_: a $_
# typo here left ble.sh silently unloaded until 2026-10-18. zzz_ble_attach.sh
# attaches at the very end of startup, after zz_atuin.sh registers its hooks.
# shellcheck source=/dev/null  # a system file the role installs; not in
# this repository and not present in CI, so there is nothing to follow.
[[ $- == *i* ]] && source -- /usr/share/blesh/ble.sh --attach=none
