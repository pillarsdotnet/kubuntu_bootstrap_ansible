# WSL service policy

WSL is treated as a client environment, not a general-purpose Linux server.
Windows/`WSLg` supply the network, clock, printing and desktop integration.
Linux servers and hardware-management daemons are stopped, disabled and
persistently masked by `roles/bootstrap/tasks/wsl_services.yml`. Associated
sockets and paths are covered so they cannot reactivate those services.

The policy runs during bootstrap and again after the package-installing roles
in `setup.yml`. The printing role skips WSL, and bootstrap skips native
Bluetooth and Wi-Fi configuration there. Native Linux, including native Linux
VDI hosts, is unchanged. Hosts without `systemd` skip service enforcement.

Only installed units are touched; missing packages are not an error.
`bootstrap_wsl_disabled_units` in `roles/bootstrap/defaults/main.yml` is the
complete policy, including units not running at inventory time. Override that
list in host variables for intentional Linux-side servers or hardware
passthrough. Removing a unit from the list does not automatically unmask or
start it: restore such services explicitly when changing a host's purpose.
Native Linux printing configuration remains skipped on WSL.

## Inventory: 2026-10-20

The inspected instance reports **Ubuntu 26.04.1 LTS**, kernel
`6.18.54.1-microsoft-standard-WSL2`, inside a Windows 11 VDI. Before enforcement,
31 system services and 8 services in the current user's `systemd` manager were
running. This is an inventory of `systemd` services, not arbitrary processes or
services inside containers or other users' sessions.

After applying the policy, 12 system services and the same 8 user services
remain running. Nineteen previously running system services were stopped;
40 installed service/socket/path/timer units are disabled and persistently masked.

### System services

| Service                       | Policy           | Reason                                                                                      |
| ----------------------------- | ---------------- | ------------------------------------------------------------------------------------------- |
| `atd.service`                 | Keep             | Deferred jobs remain useful in WSL.                                                         |
| `avahi-daemon.service`        | Disable and mask | No Linux-side LAN service discovery in this client profile.                                 |
| `chrony.service`              | Disable and mask | Use WSL/`Hyper-V` host clock integration rather than a separate NTP daemon.                 |
| `containerd.service`          | Disable and mask | No Linux container runtime in this client profile.                                          |
| `cron.service`                | Keep             | Scheduled Linux jobs remain useful.                                                         |
| `cups-browsed.service`        | Disable and mask | Printer discovery belongs on Windows.                                                       |
| `cups.service`                | Disable and mask | Printing belongs on Windows.                                                                |
| `dbus.service`                | Keep             | System IPC and service activation.                                                          |
| `docker.service`              | Disable and mask | No Linux `Docker` server in this client profile.                                            |
| `fail2ban.service`            | Disable and mask | No Linux-side fail2ban server in this WSL client profile; this unit runs `fail2ban-server`. |
| `getty@tty1.service`          | Disable and mask | WSL terminals do not need a virtual-console login prompt.                                   |
| `mariadb.service`             | Disable and mask | No local database server in this client profile.                                            |
| `named.service`               | Disable and mask | Use WSL/Windows DNS, not a local `BIND` server.                                             |
| `networkd-dispatcher.service` | Disable and mask | `systemd-networkd` is inactive; Windows/WSL own networking here.                            |
| `NetworkManager.service`      | Disable and mask | All observed interfaces are unmanaged; Windows/WSL own connectivity.                        |
| `nginx.service`               | Disable and mask | No local web/reverse-proxy server in this client profile.                                   |
| `polkit.service`              | Keep             | Authorization for D-Bus clients and system utilities.                                       |
| `rsyslog.service`             | Keep             | Preserve Linux logging and consumers of `syslog` files.                                     |
| `rtkit-daemon.service`        | Disable and mask | Host-side `WSLg` handles audio; no local real-time audio daemon needed.                     |
| `systemd-journald.service`    | Keep             | Core system logging.                                                                        |
| `systemd-logind.service`      | Keep             | Login/session tracking.                                                                     |
| `systemd-machined.service`    | Keep             | On-demand machine registration infrastructure; not itself a VM/container runtime.           |
| `systemd-resolved.service`    | Keep             | Preserve Linux resolver clients and integration with WSL DNS.                               |
| `systemd-udevd.service`       | Keep             | Device events, including WSL virtual devices and potential passthrough.                     |
| `udisks2.service`             | Disable and mask | No Linux desktop automatic disk mounting in this profile.                                   |
| `unattended-upgrades.service` | Disable and mask | Updates are managed explicitly in this WSL client profile.                                  |
| `user@1000.service`           | Keep             | User service manager.                                                                       |
| `uuidd.service`               | Keep             | Socket-activated UUID allocation for Linux clients.                                         |
| `virtlockd.service`           | Disable and mask | No `libvirt` VM host in this client profile.                                                |
| `virtlogd.service`            | Disable and mask | No `libvirt` VM host in this client profile.                                                |
| `wpa_supplicant.service`      | Disable and mask | Windows owns Wi-Fi authentication.                                                          |

The policy also covers installed `libvirt` services and activation sockets even
when their main service was not running during inventory. Nested virtualization
can work in WSL (`/dev/kvm` exists here); disabling `libvirt` is a client-profile
choice, not a claim that WSL cannot run virtual machines. The same distinction applies to
`Docker`, databases, web servers and `BIND`.

`apt-daily-upgrade.timer` and `apt-daily-upgrade.service` are also disabled
and masked: `unattended-upgrades.service` is only the shutdown helper, not
the scheduled upgrade launcher. Package-list refreshes remain enabled; install
security updates manually or through the `runbook`.

### Current user's services

All eight are retained for Linux applications, credentials, accessibility and
`WSLg` desktop integration.

| Service                          | Purpose                                        |
| -------------------------------- | ---------------------------------------------- |
| `at-spi-dbus-bus.service`        | Application accessibility IPC.                 |
| `dbus.service`                   | User-session IPC.                              |
| `gnome-keyring-daemon.service`   | Secret Service and credential storage.         |
| `gpg-agent.service`              | Cryptographic agent and passphrase caching.    |
| `xdg-desktop-portal-gtk.service` | GTK portal backend for Linux GUI applications. |
| `xdg-desktop-portal.service`     | Desktop integration portal.                    |
| `xdg-document-portal.service`    | Document access for sandboxed applications.    |
| `xdg-permission-store.service`   | Portal permission storage.                     |
