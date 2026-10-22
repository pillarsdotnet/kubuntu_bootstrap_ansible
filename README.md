# `kubuntu_bootstrap_ansible`

`Ansible` playbooks to bootstrap and configure `Kubuntu` nodes, including
`Tailscale` networking and a `Kubernetes` cluster with `Calico`.

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

## Secrets: `Ansible Vault`

Sensitive values — currently `tailscale_api_key` and `sources_apt_auth` —
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

### 2. Get a `Tailscale` API key

1. Sign in at <https://login.tailscale.com/admin/settings/keys>
2. Under **API keys**, click **Generate API key**
3. Give it a description (e.g. `ansible-kubernetes`) and set an appropriate
   expiry
4. Copy the key — it starts with `tskey-api-`

> The API key is used by the `kubernetes` role to approve the `Kubernetes`
> VIP (`10.254.0.1/32`) as an enabled subnet route on each control plane
> node, enabling `Tailscale` HA failover between them.

### 3. Get deb.griffo.io credentials

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

### 4. Create the vault file

```bash
ansible-vault create group_vars/all/vault.yml
```

This opens your `$EDITOR`. Enter the following content, substituting
your actual values:

```yaml
---
tailscale_api_key: "tskey-api-REPLACE_WITH_YOUR_KEY"
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

### 5. Re-keying or rotating the vault password

If you need to change the vault password (e.g. after a key rotation):

```bash
ansible-vault rekey group_vars/all/vault.yml
```

---

## Running the playbook

```bash
# Full setup (bootstrap → hibernation → sources → tailscale → kubernetes → printing)
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

---

## Environment Profiles: VDI and High-Risk Deployments

For VDI environments or systems where supply chain security is a concern, you can filter
repositories and packages to exclude high-risk or unnecessary sources.

### Profiles

- **`standard`** (default): Install all repositories and packages. Suitable for stable,
  physically-controlled workstations. Set via `ansible-playbook setup.yml`

- **`vdi`**: Filter out repositories that ship alpha or beta builds, or code no
  distribution has reviewed — `Launchpad` `PPA` sources, snapshot/nightly/staging suites, and
  third-party rebuilds of software maintained by someone else. Vendor repositories for the vendor's own
  software (`Docker`, `Google`, `HashiCorp`, `Tailscale`, `1Password`, `Mozilla`, …) are kept:
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
ansible-playbook setup.yml -e "environment_profile=vdi"

# Standard profile (all repos/packages installed)
ansible-playbook setup.yml -e "environment_profile=standard"

# Or explicitly set skip lists
ansible-playbook setup.yml \
  -e "skip_repos=[github-desktop,steam,libreoffice-frexh]" \
  -e "skip_packages=[steam,waydroid]"
```

### Customizing filtered repositories and packages

The lists live in `roles/sources/defaults/main.yml`, which **is** tracked in git:

| Variable              | Default         | Purpose                                              |
| --------------------- | --------------- | ---------------------------------------------------- |
| `environment_profile` | `"standard"`    | Which profile to apply                               |
| `vdi_skip_repos`      | 17 repositories | Dropped under the `vdi` profile                      |
| `vdi_skip_packages`   | 3 packages      | Dropped under the `vdi` profile                      |
| `skip_repos`          | `[]`            | Extra repositories to drop on this host, any profile |
| `skip_packages`       | `[]`            | Extra packages to drop on this host, any profile     |

`skip_repos`/`skip_packages` are **added to** whatever the profile contributes, so
`-e "environment_profile=vdi" -e "skip_repos=[steam]"` applies both. Set them per host
in `host_vars/<hostname>.yml`, or edit the `vdi_*` lists to change the fleet-wide
policy. (They deliberately do _not_ live in `group_vars/all.yml`: that file is
untracked, so anything defined only there is undefined on every other clone — which is
what produced `'environment_profile' is undefined`.)

Only packages that exist _nowhere but_ a skipped repository belong in `vdi_skip_packages`.
`LibreOffice`, `PipeWire`, `TLP` and `OBS` are in the Ubuntu archive too, so dropping their
`PPA` just pins them back to the distribution build rather than removing the software.

After updating the filter lists, re-run the playbook to regenerate the sources:

```bash
# Re-run sources only with new filter lists
ansible-playbook sources.yml -e "environment_profile=vdi"
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
# the tailscale, printing and sources roles are not gated, so skip them by tag
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
- Services will not be automatically started (`tailscale`, `CUPS`, `NetworkManager`, etc.)
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
```

Then run the linter over the whole repository:

```bash
.venv/bin/ansible-lint
```

New code should lint clean against the `production` profile before committing.

---

## `Kubernetes` VIP and `Tailscale` subnet routing

After the `kubernetes` role runs, each control plane node will have:

- `10.254.0.1/32` bound to a `dummy-k8svip` interface (persistent via
  `systemd-networkd`)
- The route advertised to `Tailscale` via `tailscale set --advertise-routes`
- The route approved in the `Tailscale` admin console via the API

When you add further control plane nodes (`cp-1`, `cp-2`, …), re-running
the playbook will advertise and approve the VIP route on those nodes too.
`Tailscale` will automatically fail over between advertisers if a node goes
down.

> **Note:** `Tailscale` subnet route HA failover requires the route to be
> approved on **each** advertising node individually in the admin console.
> The role does this automatically when `tailscale_api_key` is set.
