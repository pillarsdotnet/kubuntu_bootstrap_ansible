# Register atuin's hooks and keybindings. Must run after 0_ble.sh (atuin
# detects BLE_VERSION and rides blehook instead of bash-preexec) and before
# zzz_ble_attach.sh, since ble.sh expects to attach after all hooks exist.
[[ $- == *i* ]] && eval "$(atuin init bash)"
