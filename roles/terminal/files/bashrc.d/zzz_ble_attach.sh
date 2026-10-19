# Attach ble.sh last, after every other snippet has registered its hooks.
[[ ! ${BLE_VERSION-} ]] || ble-attach
