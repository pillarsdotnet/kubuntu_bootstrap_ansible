# `kubuntu_bootstrap_ansible`

`Ansible` playbooks to bootstrap and configure `Kubuntu` nodes, including
a `Kubernetes` cluster with `Calico`.

## Repository layout

Some files are intentionally excluded from git and must be created locally
on the machine you run `Ansible` from. This keeps secrets off the remote
server and out of version control.

| Path                       | In git? | Purpose                                   |
| -------------------------- | ------- | ----------------------------------------- |
| `group_vars/all/vars.yml`  | No      | Group-wide variables (hosts, ports, etc.) |
| `group_vars/all/vault.yml` | No      | Encrypted secrets (`Ansible Vault`)       |
| `host_vars/<hostname>.yml` | No      | Per-host variables                        |
| `inventory.yml`            | No      | List of hosts to configure                |

---

## Inventory

The `kubernetes` role uses group membership to decide what to configure on
each host. Create an inventory file (e.g. `inventory.yml`) that reflects
your cluster topology.

### Group structure

```text
kubernetes
├── cp       ← runs control_plane.yml (kubeadm init, Calico, VIP)
└── worker   ← runs worker.yml (kubeadm join)
```

Hosts in **both** `cp` and `worker` are initialised as a control plane and
then have the `node-role.kubernetes.io/control-plane:NoSchedule` taint
removed, so they can also schedule regular workloads.

### Examples

**Current setup — dedicated control plane and worker:**

```yaml
all:
  children:
    kubernetes:
      children:
        cp:
          hosts:
            bobse16:
        worker:
          hosts:
            homelab:
```

**Single node — control plane that also runs workloads:**

```yaml
all:
  children:
    kubernetes:
      children:
        cp:
          hosts:
            bobse16:
        worker:
          hosts:
            bobse16:
```

**HA control plane — three control planes, two dedicated workers:**

```yaml
all:
  children:
    kubernetes:
      children:
        cp:
          hosts:
            cp-1:
            cp-2:
            cp-3:
        worker:
          hosts:
            homelab:
            worker-2:
```

Connection details (`Ansible` SSH user, port, etc.) go in
`host_vars/<hostname>.yml`, which is excluded from git.

---

## Backing up what git does not carry

`inventory.yml`, `host_vars/` and `group_vars/all/` are excluded from version
control on purpose, so they never reach the public mirror. The consequence is
easy to miss: the roles here would survive the loss of the machine holding
them, and the configuration that aims those roles at real hosts would not.
"Absent from the mirror" and "backed up" are different properties.

```bash
./tools/backup-site-config.sh <ssh-destination> [remote-directory]
```

The script archives those paths, encrypts the archive with the same vault
password this repository already uses, proves it survives a decrypt before
sending it, copies it to the destination, and compares checksums rather than
trusting that `scp` said nothing. Re-run it after changing any of those files.

Two things are worth stating plainly:

- **The vault password is not in the archive**, and including it would make
  the encryption decorative. The backup is therefore recoverable only while
  that password exists somewhere other than the machine being backed up.
  Keep it in a password manager, not only in `~/.ansible/vault_pass`.
- **Encryption is not optional here even for a host you control.** An
  estate's inventory on a publicly reachable machine is worse than no copy
  of it.

To restore, fetch the newest archive, `ansible-vault decrypt` it, and unpack
it at the root of a checkout.

## Secrets: `Ansible Vault`

Sensitive values — currently `sources_apt_auth` —
live in `group_vars/all/vault.yml`, which is encrypted with `Ansible Vault`.
The directory is excluded from git via `group_vars/.gitignore` so it never
leaves your local machine.

The file sits under `group_vars/all/`, not at `group_vars/vault.yml`:
`Ansible` only loads `group_vars` entries whose name matches a group, and no
group is called "vault", so a top-level `vault.yml` is silently ignored.
Everything in a `group_vars/all/` directory loads for every host.

### 1. Choose a vault password

Pick a strong password and store it in a file **outside** this repository:

```bash
mkdir -p ~/.ansible
python3 -c "import secrets; print(secrets.token_urlsafe(32))" > ~/.ansible/vault_pass
chmod 600 ~/.ansible/vault_pass
```

The project's `ansible.cfg` already points `vault_password_file` at
`~/.ansible/vault_pass`, so no flag is needed once that file exists.

### 2. Get deb.griffo.io credentials

Since 2026-10-01, deb.griffo.io requires a subscription to download
packages (`apt update` and browsing stay free). After subscribing at
<https://deb.griffo.io/>, the login (the email address paid with) and
password arrive by email. They go in `sources_apt_auth` below, which the
sources role writes to `/etc/apt/auth.conf.d/griffo.conf` on every host.

If the vault has no `griffo` entry, the sources role skips the repository rather
than installing one that would 401 on every download: no
`griffo.sources` file is written, and one left behind by an earlier
credentialed run is removed by the unmanaged-sources cleanup. On a
`resolute` host, whose archive carries no `uv` at all, the `uv` package is
skipped along with the repository; on `stonking` the archive's own (older) `uv`
installs instead.

### 3. Create the vault file

```bash
ansible-vault create group_vars/all/vault.yml
```

This opens your `$EDITOR`. Enter the following content, substituting
your actual values:

```yaml
---
sources_apt_auth:
  griffo:
    machine: "deb.griffo.io"
    login: "REPLACE_WITH_SUBSCRIPTION_EMAIL"
    password: "REPLACE_WITH_SUBSCRIPTION_PASSWORD"
```

Save and close the editor. The file is now AES256-encrypted on disk.

To verify it was created correctly:

```bash
ansible-vault view group_vars/all/vault.yml
```

To edit it later:

```bash
ansible-vault edit group_vars/all/vault.yml
```

### 4. Re-keying or rotating the vault password

If you need to change the vault password (e.g. after a key rotation):

```bash
ansible-vault rekey group_vars/all/vault.yml
```

---

## Running the playbook

```bash
# Full setup (bootstrap → hibernation → sources → kubernetes → printing)
ansible-playbook setup.yml

# Kubernetes only
ansible-playbook setup.yml --tags kubernetes

# Dry run
ansible-playbook setup.yml --check --diff
```

If you did **not** configure `vault_password_file` in `ansible.cfg`, add
`--ask-vault-pass` to any of the above commands:

```bash
ansible-playbook setup.yml --ask-vault-pass
```

### The first run against a fresh host needs `-K`

`roles/bootstrap` grants the `ansible` user `sudo` without a password by writing
`/etc/sudoers.d/10-installer`, but writing that file itself needs `become` -
so the very first run against a newly installed host has no way in and fails
during fact gathering:

```text
module_stdout: "sudo: interactive authentication is required"
```

Supply the `ansible` account's password once with `-K`:

```bash
ansible-playbook setup.yml --limit newhost -K
```

That run replaces the installer's own `10-installer` - which grants the `sudo`
group password-authenticated access only - with a `NOPASSWD` rule, and every
later run against the host works without `-K`. On a desktop install the
`ansible` account is the primary user created by the installer, so the password
is the one chosen during installation.

The wording of the error varies by release. `Ubuntu` 25.10 and later ship
`sudo-rs` rather than the original `sudo`, and it reports a missing password as
"interactive authentication is required" where `sudo` said "a password is
required".

---

## Hibernation

`hibernation.yml` reserves a partition for hibernation on hosts that have one:
it comments the partition out of `/etc/fstab` so nothing else claims it, swaps
it on just before hibernating and off again after resume, and stops
`systemd-logind` refusing to hibernate over its memory check.

Name the partition in `host_vars/<hostname>.yml`, with the output of
`lsblk -o NAME,UUID,SIZE,TYPE` or `blkid`:

```yaml
hibernation_uuid: 1ce71583-93fb-4b91-a9fc-b3efb897fadf
```

### Opting a host out

`roles/hibernation` runs only when `hibernation_uuid` holds a 36-character
value, and `hibernation.yml` prompts for a UUID only when the variable is
undefined. Any other non-blank value therefore does both jobs at once: it
suppresses the prompt and skips the role. This repository spells it
`"disabled"`:

```yaml
# No hibernation partition on this host.
hibernation_uuid: "disabled"
```

Leaving the variable out works too, but only by accident. At a terminal the
play stops and waits for someone to type a UUID. Where `stdin` is not
interactive - `cron`, CI, `< /dev/null` - `ansible.builtin.pause` does not
block: it warns `Not waiting for response to prompt as stdin is not
interactive`, returns an empty answer, and the role skips on that. So the run
does not hang, but it either asks a question with no answer or leans on a
warning to get past it. Saying `"disabled"` once states the intent instead.

For a one-off run the same value works on the command line, though an extra
variable applies to every host in that run, hibernating ones included:

```bash
ansible-playbook setup.yml -e hibernation_uuid=disabled
```

Do **not** set the variable to an empty value. `hibernation_uuid:` with nothing
after the colon is `null` rather than a string, and the length test fails the
play outright:

```text
A 'when' expression failed: The filter plugin 'ansible.builtin.length' failed:
object of type 'NoneType' has no len()
```

---

## Networked scanners

`roles/printing` points the `SANE` `net` backend at hosts running `saned`, so
`skanpage`, `skanlite` and anything else built on `SANE` find a scanner that is
physically attached to another machine. Name those hosts in
`host_vars/<hostname>.yml`, which `git` excludes:

```yaml
printing_sane_net_hosts: ["10.0.0.2"]
```

The role writes `/etc/sane.d/net.conf` and makes sure `net` is enabled in
`/etc/sane.d/dll.conf`. The default is an empty list, and the role then leaves
both files alone, so hosts with no networked scanner need no entry.

Keep the address current. The `net` backend blocks on `TCP` connect rather than
reporting an error, so an address that no longer answers hangs every `SANE`
client on the machine at startup with no message. A scanner is also remembered
a second time, per user, in `~/.local/state/skanpagestaterc` and
`~/.local/state/skanlitestaterc` as a full device name with the address embedded:

```ini
[general]
deviceName=net:10.0.0.2:airscan:e0:EPSON ET-2980 Series (USB)
```

Those files are outside this repository's remit. A client that still hangs
after `net.conf` is correct is opening the remembered device, so fix the
address there too, in both the `deviceName` and the `[Options For ...]` group
headers that carry the per-device settings.

### Sharing a `USB` scanner as `eSCL`

`roles/printing` installs `ipp-usb`, which presents a printer that speaks
`IPP`-over-`USB` as a local `IPP` service - and, the part that is easy to
miss, as a local `eSCL` scanner too. That is how a scanner with no network
connection of its own ends up reachable as a `net:` device, which looks like a
network scanner and is not one.

The role owns `/etc/ipp-usb/ipp-usb.conf`. `interface` defaults to `loopback`,
which is right for a desktop. A host that should serve the scanner to other
machines says so in `host_vars/<hostname>.yml`:

```yaml
printing_ipp_usb_interface: "all"
printing_ipp_usb_ipv6: "disable"
```

Clients then reach it at `http://<host>:65431/eSCL` without the `saned` proxy
above, and `avahi` advertises it as `_uscan._tcp` so an `eSCL` client finds it
unaided. `Windows` does not use that path; it discovers over `WS-Discovery`.

**The port range must span at least two ports.** `ipp-usb` requires
`http-min-port` to be strictly less than `http-max-port` and exits at startup
otherwise. A one-port range is not how the port is pinned and does not need to
be - `ipp-usb` takes the lowest free port in the range, so with one device
attached the minimum is always the one it uses. The role asserts this rather
than letting the daemon fail.

**`ipv6` is the only exposure control the daemon has.** There is no interface
list and no access control beyond `all` or `loopback`, so on a host that
shares the endpoint, turning `IPv6` off is what keeps it off a globally
routable address. Anything narrower needs a host firewall.

The file is a `dpkg` `conffile`, so a future upgrade keeps this version and
leaves a `.dpkg-dist` beside it. A newly added setting will not appear here by
itself.

## Monitoring a UPS

`roles/nut` installs `Network UPS Tools` and points it at a `UPS` on the host's
own `USB` port, so `upsmon` can halt the machine before the battery runs out.
It is off everywhere by default. Enable it in `host_vars/<hostname>.yml`, which
`git` excludes, using the identity that `nut-scanner` reports **on that host**:

```bash
sudo nut-scanner -U
```

```yaml
nut_enabled: true
nut_ups_name: "tripplite"
nut_ups_description: "Tripp Lite SMART1500LCDT"
nut_vendorid: "09AE"
nut_productid: "3016"
nut_serial: "..."
nut_upsmon_password: !vault |
  ...
```

Copy the driver name from `nut-scanner` rather than inferring it from the
model: `Tripp Lite` alone is split between `usbhid-ups` and `tripplite_usb` by
protocol generation, not by product line. The passwords have no defaults, and
the role refuses to run without `nut_upsmon_password`; generate one with
`ansible-vault encrypt_string` so the file `git` excludes is still encrypted
at rest. Setting `nut_admin_password` as well adds an account for `upscmd`, which
is what the role sends instant commands through.

The beeper is the one piece of state here that does not live in a file. It is
stored in the `UPS` itself, survives a restart of every daemon on the host, and
anyone walking past can change it by holding the front-panel `MUTE` button. So
the role reads `ups.beeper.status` and sends a command only when it disagrees
with what the host asked for:

```yaml
nut_beeper_state: "disabled" # or "enabled", or "" to leave it alone
nut_admin_password: !vault | # required for either non-empty value
  ...
```

Setting it to `disabled` silences the beeper **completely** — the overload and
critical-fault alarms as well as the on-battery chirp. It is not an
on-battery-only mute, and on a host wired to the surge-only outlets it removes
the only indication that the battery side has faulted.

Two things about this role exist because of what it cost to get right the
first time, and both are documented at length in
`roles/nut/tasks/main.yml`.

The first is that the packaging has a genuine ordering problem. `upsd` exits
fatally when `ups.conf` defines no `UPS`, which is the state a fresh install is
in, so the `postinst` leaves the package half-configured; and the configuration
cannot be written first, because those files are `dpkg` `conffiles` whose
owning group the `postinst` creates. The role masks the units across the install, which
`deb-systemd-invoke` honours by skipping them, and unmasks them once there is
something to read.

The second is that a `UPS` already plugged in when the package is installed
never gets the shipped `udev` rule applied, keeps a `root:root` device node,
and makes the driver report `insufficient permissions on everything` — a
permissions fault that reads like a missing device. The role re-triggers an
`add` event on that one device.

Expect the first connection to take a minute. A `UPS` can refuse to serve its
`HID` report descriptor for several attempts running: on `homelab` the `Tripp
Lite` answered 2 of 6 consecutive tries, and the kernel's own `HID` driver
failed the same read with `can't add hid device: -110`. The driver unit is
built for that, with `Restart=always` and no start limit, so the role waits
five minutes for a reading rather than trusting that the daemons came up.

### Low-power mode while on battery

The role can drop a host's draw for the duration of an outage, through
`upsmon`'s `NOTIFYCMD`. Off by default; enable it per host:

```yaml
nut_power_mode_enabled: true
nut_power_mode_rapl_pl1_watts: 45
nut_power_mode_rapl_pl2_watts: 65
nut_power_mode_max_freq_mhz: 1600
nut_power_mode_epp: "power"
nut_power_mode_stop_services: ["forgejo-runner.service"]
nut_power_mode_restore_delay: 60
```

Every lever is off until set, and each is **saved before it is changed and
restored from the saved copy**, so a value set by hand or by another role comes
back as it was and this role needs to know nothing about who else owns the same
knob. Only services found running are stopped, and only those are started
again.

Two things are worth knowing before picking numbers.

**A frequency ceiling has to be below the base clock to do anything** on a host
that already runs with turbo off. `intel_pstate` clamps the policy maximum to
base when `no_turbo` is set, so a higher figure is accepted and silently
ignored — `scaling_min_freq` is the real floor. On `homelab`, where
`roles/diagnostics` disables turbo for the `Vmin Shift` mitigation, base is
3200 MHz and the floor is 800 MHz.

**Stopping discretionary work is usually the largest lever by far.** Measured
idle draw on `homelab` is 72 W; a queue of `CI` builds takes it to several
times that. Capping power and frequency bounds the worst case, but not starting
the work at all is what actually buys runtime.

The restore is deliberately deferred rather than immediate. Mains returning is
not the same as mains being back, and without the delay a supply that blinks
would stop and start those services on every blink. A second outage inside the
window cancels the pending restore, so the host stays down low.

`nut_notify_cmd` and `nut_power_mode_enabled` claim the same hook, and `upsmon`
has exactly one `NOTIFYCMD`, so the role refuses both at once rather than
picking a winner.

Finally, note what the role does not buy on its own. Monitoring proves the
battery side is healthy, but a host wired to the `SURGE PROTECTED` outlets
loses power at the same instant `upsmon` sees the outage, so the shutdown it
orders never runs. Only the `BATTERY/SURGE PROTECTED` outlets make the
shutdown command meaningful.

### Letting the `UPS` power down with the host

Once a host has halted on low battery there is nothing left for the `UPS` to
protect, and every further minute of inverting is charge it will want back on
the way up. `nut_allow_killpower` lets it cut its own output and re-energise
when mains returns.

`NUT` ships this locked, and it is narrower than it sounds. `upsmon` writes
`POWERDOWNFLAG` only on a low-battery shutdown, and the packaged
`/usr/lib/systemd/system-shutdown/nutshutdown` hook runs `upsdrvctl shutdown`
only when that flag is present - it logs `SKIP: Not in FSD (killpower) mode`
otherwise. **An ordinary reboot does not cut the outlets.**

Check one thing in firmware first: that the board powers on by itself once
`AC` returns. The `UPS` re-energises after `ups.delay.start` seconds, and a
board set to stay off leaves the outlets live and the machine dark.

### Driver flags, and why a changed option may not take

`nut_driver_flags` carries driver options that take no value. It is separate
from `nut_driver_extra` because `NUT` parses a flag as its name alone, so
`pollonly = true` is a setting called `pollonly` with a value, which the
driver does not have.

```yaml
nut_driver_flags: ["pollonly"]
nut_allow_killpower: true
```

The driver reads `ups.conf` only when it starts, and the enumerator rebuilds
the unit's drop-ins when a section changes without recycling a running driver.
A changed option was therefore written, reported as changed, and ignored. The
role now restarts the driver instance on a configuration change **and**
compares the configured intent against the live `driver.flag` value, recycling
the driver when they disagree - so a host whose file was already correct still
converges, rather than reporting success over a driver running yesterday's
settings.

Expect a restart to cost time on an unreliable unit. A `UPS` can refuse its
`HID` report descriptor for many attempts running, which is why the driver
unit is `Restart=always` with no start limit, and why the role waits minutes
for a reading rather than trusting that the daemons came up.

---

## Serving `SMB` shares

`roles/fileserver` serves shares to `Windows` machines on the `LAN`. Off
everywhere by default: it opens a listening service and creates writable
accounts, which is not something to do to a host that did not ask.

```yaml
fileserver_enabled: true
fileserver_users:
  - name: "backup"
    password: !vault | # see "Secrets" above
      ...
fileserver_shares:
  - name: "filehistory"
    comment: "Windows File History"
    users: ["backup"]
    ro_users: ["laptop"]
fileserver_hosts_allow: ["127.0.0.1", "10.0.0.0/24", "::1", "fe80::/10"]
fileserver_interfaces: ["lo", "wlo1"]
```

Each account becomes a system user with no shell and a locked shadow
password: its `Samba` password lives in `Samba`'s own database, so an account
that owns every file written through its share still cannot log in to the
host. `users` may read and write and owns the directory; `ro_users` may
connect and read, enforced through `read list`. The directory stays
group-writable because the owning account needs that, so `Samba` is the
enforcement point for `ro_users` - sound for accounts with no shell, which
these deliberately do not have.

**`host_vars` is authoritative for passwords.** Change a vaulted value, re-run
the role, and the account follows: the role tests the configured password the
way a client does and resets it only when that fails. A password changed by
hand with `smbpasswd` is reverted on the next run, so either tell the vault
about it or drop that account from `fileserver_users` and manage it yourself.

### Both host lists have to name both address families

`hosts allow` and `hosts deny` written as `IPv4` expressions leave an `IPv6`
hole, because `Samba` allows a client that matches **neither** list. Measured
on a host with `10.0.0.0/24` and `0.0.0.0/0` in force: a connection to its
globally routable `IPv6` address listed the shares. `fileserver_hosts_deny`
therefore names `::/0` as well, and a host wanting `IPv6` clients on the `LAN`
lists those prefixes in `fileserver_hosts_allow`.

`fileserver_interfaces` adds `bind interfaces only`, which keeps the shares
off container and `Kubernetes` bridges. Be precise about what it does not do:
it restricts by **interface**, not by address scope, so a global `IPv6`
address on a listed interface stays bound. The host lists gate that, and
behind `NAT` the router gates it from outside. It also does not survive an
interface rename - a host moved from wireless to wired stops serving until
the list is updated.

### One share per purpose, and per machine

`wbadmin` overwrites its whole target on every run and keeps exactly one
system image per location. Two machines aimed at one share overwrite each
other, and `File History` versions in the same folder go with them. Give each
machine its own pair.

### What the role deliberately does not do

**It cannot bound a share's size** on a host whose volume group has no free
extents and whose root filesystem carries no quota feature: there is nowhere
to put a volume of its own and no project quota to apply. The shares then
share a filesystem with everything else, and `fileserver_space_alarm` is the
compensating control. It **fails** its unit rather than only logging, so a
missed warning stays in `systemctl --failed` instead of scrolling past - but
it is a warning, not a limit, and the difference matters.

**It does not make the host discoverable unaided.** `Windows` 10 and 11
dropped the `NetBIOS` browsing `nmbd` offers and use `WS-Discovery` instead,
and the `wsdd` package ships the binary with no unit at all, so the role
provides one.

### Consolidating one share into another

`fileserver_replicate` copies one share into another as timestamped
snapshots, sharing unchanged files with the previous one as hard links:

```yaml
fileserver_replicate:
  - source: "laptop-windowsimage"
    dest: "windowsimage"
```

Snapshots land as `<dest>/2026-11-24T233045Z/`. Three interlocks exist because
the obvious version of each is wrong:

- **A source still being written is skipped.** `Windows` streams a system
  image for minutes at a time, and copying mid-write captures a torn file that
  looks like a backup and is not one. Nothing is copied until the newest file
  has been untouched for `fileserver_replicate_quiet_minutes`.
- **A snapshot that would breach the free-space floor is refused**, not
  started. A half-written snapshot is worse than no snapshot.
- **Pruning only ever considers the script's own timestamps.** The destination
  is a live share with its own client writing into it, and a prune that walked
  everything would delete somebody's real backup.

Keep `fileserver_replicate_keep` low. A system image is rewritten whole each
run, so it shares no hard links with its predecessor and every snapshot costs
full size.

**This is consolidation, not redundancy.** Both copies land on the same
filesystem. Where that filesystem is a linear span with no parity, one drive
failure takes the original and every snapshot together. It guards against a
machine losing its own backup, not against the host losing a disk.

## Environment Profiles: VDI and High-Risk Deployments

For VDI environments or systems where supply chain security is a concern, you can filter
repositories and packages to exclude high-risk or unnecessary sources.

### Profiles

- **`standard`** (default): Install all repositories and packages. Suitable for stable,
  physically-controlled workstations. Set via `ansible-playbook setup.yml`

- **`vdi`**: Filter out repositories that ship alpha or beta builds, or code no
  distribution has reviewed — `Launchpad` `PPA` sources, snapshot/nightly/staging suites, and
  third-party rebuilds of software maintained by someone else. Vendor repositories for the vendor's own
  software (`Docker`, `Google`, `HashiCorp`, `1Password`, `Mozilla`, …) are kept:
  their provenance is accountable. This profile is customizable — see "Customizing
  filtered repositories and packages" below.

The profile is a **trust** setting, not a capability one. Kernel-capability skipping
for WSL is detected automatically and needs no profile — see
`docs/WSL1_COMPATIBILITY.md`.

On WSL with `systemd`, bootstrap also stops, disables and masks services outside
the default client profile, including `BIND`, `MariaDB`, `nginx`, `Docker`/`containerd`,
`libvirt`, Linux printing and hardware-management daemons. Setup reapplies this
policy after package installation. See [WSL services](docs/WSL_SERVICES.md) for
the inventory, rationale and `bootstrap_wsl_disabled_units` override.

### Running with environment profiles

```bash
# Install using VDI profile (filters high-risk repos and packages)
ansible-playbook setup.yml -e "sources_environment_profile=vdi"

# Standard profile (all repos/packages installed)
ansible-playbook setup.yml -e "sources_environment_profile=standard"

# Or explicitly set skip lists
ansible-playbook setup.yml \
  -e "sources_skip_repos=[github-desktop,steam,libreoffice-frexh]" \
  -e "sources_skip_packages=[steam,waydroid]"
```

### Customizing filtered repositories and packages

The lists live in `roles/sources/defaults/main.yml`, which **is** tracked in git:

| Variable                      | Default         | Purpose                                              |
| ----------------------------- | --------------- | ---------------------------------------------------- |
| `sources_environment_profile` | `"standard"`    | Which profile to apply                               |
| `sources_vdi_skip_repos`      | 17 repositories | Dropped under the `vdi` profile                      |
| `sources_vdi_skip_packages`   | 3 packages      | Dropped under the `vdi` profile                      |
| `sources_skip_repos`          | `[]`            | Extra repositories to drop on this host, any profile |
| `sources_skip_packages`       | `[]`            | Extra packages to drop on this host, any profile     |

`sources_skip_repos`/`sources_skip_packages` are **added to** whatever the profile contributes, so
`-e "sources_environment_profile=vdi" -e "sources_skip_repos=[steam]"` applies both. Set them per host
in `host_vars/<hostname>.yml`, or edit the `vdi_*` lists to change the fleet-wide
policy. (They deliberately do _not_ live in `group_vars/all.yml`: that file is
untracked, so anything defined only there is undefined on every other clone — which is
what produced `'sources_environment_profile' is undefined`.)

Only packages that exist _nowhere but_ a skipped repository belong in `sources_vdi_skip_packages`.
`LibreOffice`, `PipeWire`, `TLP` and `OBS` are in the Ubuntu archive too, so dropping their
`PPA` just pins them back to the distribution build rather than removing the software.

After updating the filter lists, re-run the playbook to regenerate the sources:

```bash
# Re-run sources only with new filter lists
ansible-playbook sources.yml -e "sources_environment_profile=vdi"
```

This will:

1. Remove any previously-installed repositories that are now in the skip list
2. Uninstall any packages that are now in the skip list (if `autoremove: true`)
3. Write the filtered set of `.sources` files to `/etc/apt/sources.list.d/`

### WSL-1 and VDI Environment Compatibility

When using this playbook on WSL-1 (Windows Subsystem for Linux), tasks in the
`bootstrap` role that require unavailable kernel features (`iptables`/`netfilter`,
`systemd`) are skipped automatically — WSL-1 is detected from the kernel release, so
there is no flag to remember. `NetworkManager` reloads are skipped on WSL-1 **and**
WSL-2, since Windows owns the network on both.

**The playbook does not silently fail — it explicitly skips incompatible tasks.** Each skipped
task is documented in `docs/WSL1_COMPATIBILITY.md`, which explains:

- Which kernel features are unavailable and why
- The impact of skipping each task
- Suggested workarounds (e.g., using Windows Firewall instead of UFW)

To understand which tasks are being skipped and why, read `docs/WSL1_COMPATIBILITY.md` before running on WSL-1:

```bash
# Before running on WSL-1, review incompatibilities
cat docs/WSL1_COMPATIBILITY.md

# The bootstrap role skips what WSL-1 cannot do on its own; the tagged tasks in
# the printing and sources roles are not gated, so skip them by tag
ansible-playbook setup.yml --skip-tags requires_netfilter,requires_systemd
```

### Future Enhancement: Local Security Scanning

Microsoft Defender ATP (`mdatp`) is currently skipped in VDI profiles due to enterprise
licensing requirements. Future work should evaluate lightweight local security scanning
tools as alternatives:

- Filesystem integrity checking (e.g., `aide`, `tripwire`, `samhain`)
- Malware scanning (e.g., `clamav`, `chkrootkit`)
- Vulnerability scanning (e.g., `lynis`, `openscap`)
- Supply chain verification (e.g., `trivy` for container/package scanning)

These can be evaluated and conditionally added to VDI profiles based on risk posture.

---

## Running on WSL1 (Windows Subsystem for Linux v1)

WSL1 lacks `systemd` and `netfilter` kernel support, which blocks several playbook tasks:

- UFW firewall rules require `netfilter`/`iptables` kernel modules
- Service management (`systemd_service`) cannot start/restart services
- `systemd` packages cannot complete post-installation configuration

To run the playbook on WSL1, skip these operations:

```bash
ansible-playbook setup.yml --skip-tags requires_netfilter,requires_systemd
```

This will complete successfully with the following limitations:

- Firewall rules will not be configured
- Services will not be automatically started (`CUPS`, `NetworkManager`, etc.)
- `systemd`-dependent packages will be partially installed but not configured

For full functionality, upgrade to WSL2 (which includes `Hyper-V` nested virtualization
and `systemd` support). See the [WSL2 installation guide](https://learn.microsoft.com/en-us/windows/wsl/install).

---

## Linting

`Ansible` itself comes from the system package, but the linter is pinned in
`requirements.txt` so it is reproducible. Set up (or refresh) a local tooling
`venv` with [`uv`](https://docs.astral.sh/uv/):

```bash
uv venv
uv pip install -r requirements.txt
.venv/bin/ansible-galaxy collection install -r requirements.yml
```

The collection install matters even though `ansible` itself comes from the
system package. The `venv` carries `ansible-core` alone, and `ansible-lint`
resolves module names during its syntax check, so without the collections in
`requirements.yml` it fails on the first non-builtin module it meets. A
workstation hides this, because the `apt` package ships the collections
already -- it shows up only in CI.

Then run the linter over the whole repository:

```bash
.venv/bin/ansible-lint
```

New code should lint clean against the `production` profile before committing.

---

## `Kubernetes` VIP

After the `kubernetes` role runs, each control plane node has `10.254.0.1/32`
bound to a `dummy-k8svip` interface (persistent via `systemd-networkd`).
Worker nodes reach the VIP through `iptables` DNAT rules that redirect it to
the first control plane node's address, restored at boot by the
`k8s-iptables-restore` unit.
