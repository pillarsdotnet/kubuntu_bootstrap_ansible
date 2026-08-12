# kubuntu_bootstrap_ansible

Ansible playbooks to bootstrap and configure Kubuntu nodes, including
Tailscale networking and a Kubernetes cluster with Calico.

## Repository layout

Some files are intentionally excluded from git and must be created locally
on the machine you run Ansible from. This keeps secrets off the remote
server and out of version control.

| Path | In git? | Purpose |
|------|---------|---------|
| `group_vars/all.yml` | No | Group-wide variables (hosts, ports, etc.) |
| `group_vars/vault.yml` | No | Encrypted secrets (Ansible Vault) |
| `host_vars/<hostname>.yml` | No | Per-host variables |
| `inventory.yml` | No | List of hosts to configure |
---

## Inventory

The `kubernetes` role uses group membership to decide what to configure on
each host. Create an inventory file (e.g. `inventory.yml`) that reflects
your cluster topology.

### Group structure

```
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

Connection details (Ansible SSH user, port, etc.) go in
`host_vars/<hostname>.yml`, which is excluded from git.

---

## Secrets: Ansible Vault

Sensitive values — currently `tailscale_api_key` — live in
`group_vars/vault.yml`, which is an Ansible Vault-encrypted file.
The file is excluded from git via `group_vars/.gitignore` so it never
leaves your local machine.

### 1. Choose a vault password

Pick a strong password and store it in a file **outside** this repository:

```bash
mkdir -p ~/.ansible
python3 -c "import secrets; print(secrets.token_urlsafe(32))" > ~/.ansible/vault_pass
chmod 600 ~/.ansible/vault_pass
```

To avoid typing `--vault-password-file` on every command, add this to
`ansible.cfg` in the project root (create the file if it does not exist):

```ini
[defaults]
vault_password_file = ~/.ansible/vault_pass
```

### 2. Get a Tailscale API key

1. Sign in at <https://login.tailscale.com/admin/settings/keys>
2. Under **API keys**, click **Generate API key**
3. Give it a description (e.g. `ansible-kubernetes`) and set an appropriate
   expiry
4. Copy the key — it starts with `tskey-api-`

> The API key is used by the `kubernetes` role to approve the Kubernetes
> VIP (`10.254.0.1/32`) as an enabled subnet route on each control plane
> node, enabling Tailscale HA failover between them.

### 3. Create the vault file

```bash
ansible-vault create group_vars/vault.yml
```

This opens your `$EDITOR`. Enter the following content, substituting
your actual key:

```yaml
---
tailscale_api_key: "tskey-api-REPLACE_WITH_YOUR_KEY"
```

Save and close the editor. The file is now AES256-encrypted on disk.

To verify it was created correctly:

```bash
ansible-vault view group_vars/vault.yml
```

To edit it later:

```bash
ansible-vault edit group_vars/vault.yml
```

### 4. Re-keying or rotating the vault password

If you need to change the vault password (e.g. after a key rotation):

```bash
ansible-vault rekey group_vars/vault.yml
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

- **`vdi`**: Filter repositories and packages flagged as high-risk for VDI/shared
  environments. This profile is customizable — see "Customizing Filtered Repos" below.

### Running with environment profiles

```bash
# Install using VDI profile (filters high-risk repos and packages)
ansible-playbook setup.yml -e "environment_profile=vdi"

# Standard profile (all repos/packages installed)
ansible-playbook setup.yml -e "environment_profile=standard"

# Or explicitly set skip lists
ansible-playbook setup.yml \
  -e "skip_repos=[github-desktop,font-manager-staging,libreoffice-frexh]" \
  -e "skip_packages=[steam,waydroid]"
```

### Customizing filtered repos and packages

When you run with `environment_profile=vdi`, the playbook references `skip_repos` and
`skip_packages` lists defined in `group_vars/all.yml`. Edit that file to customize
which repositories and packages are filtered for your use case.

After updating the filter lists, re-run the playbook to regenerate the sources:

```bash
# Re-run sources only with new filter lists
ansible-playbook sources.yml -e "environment_profile=vdi"
```

This will:
1. Remove any previously-installed repos that are now in the skip list
2. Uninstall any packages that are now in the skip list (if `autoremove: true`)
3. Write the filtered set of `.sources` files to `/etc/apt/sources.list.d/`

### WSL-1 and VDI Environment Compatibility

When using this playbook with WSL-1 (Windows Subsystem for Linux) or other virtualized environments,
certain tasks will be automatically skipped because they require Linux kernel features that are
unavailable in WSL-1 (such as iptables/netfilter for firewall rules).

**The playbook does not silently fail — it explicitly skips incompatible tasks.** Each skipped
task is documented in `docs/WSL1_COMPATIBILITY.md`, which explains:

- Which kernel features are unavailable and why
- The impact of skipping each task
- Suggested workarounds (e.g., using Windows Firewall instead of UFW)

To understand which tasks are being skipped and why, read `docs/WSL1_COMPATIBILITY.md` before running on WSL-1:

```bash
# Before running on WSL-1, review incompatibilities
cat docs/WSL1_COMPATIBILITY.md

# Run with VDI profile to auto-skip incompatible tasks
ansible-playbook setup.yml -e "environment_profile=vdi"
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

WSL1 lacks systemd and netfilter kernel support, which blocks several playbook tasks:
- UFW firewall rules require netfilter/iptables kernel modules
- Service management (systemd_service) cannot start/restart services
- systemd packages cannot complete post-installation configuration

To run the playbook on WSL1, skip these operations:

```bash
ansible-playbook setup.yml --skip-tags requires_netfilter,requires_systemd
```

This will complete successfully with the following limitations:
- Firewall rules will not be configured
- Services will not be automatically started (tailscale, CUPS, NetworkManager, etc.)
- systemd-dependent packages will be partially installed but not configured

For full functionality, upgrade to WSL2 (which includes Hyper-V nested virtualization
and systemd support). See the [WSL2 installation guide](https://learn.microsoft.com/en-us/windows/wsl/install).

---

## Linting

Ansible itself comes from the system package, but the linter is pinned in
`requirements.txt` so it is reproducible. Set up (or refresh) a local tooling
venv with [uv](https://docs.astral.sh/uv/):

```bash
uv venv
uv pip install -r requirements.txt
```

Then run the linter over the whole repo:

```bash
.venv/bin/ansible-lint
```

New code should lint clean against the `production` profile before committing.

---

## Kubernetes VIP and Tailscale subnet routing

After the `kubernetes` role runs, each control plane node will have:

- `10.254.0.1/32` bound to a `dummy-k8svip` interface (persistent via
  `systemd-networkd`)
- The route advertised to Tailscale via `tailscale set --advertise-routes`
- The route approved in the Tailscale admin console via the API

When you add further control plane nodes (`cp-1`, `cp-2`, …), re-running
the playbook will advertise and approve the VIP route on those nodes too.
Tailscale will automatically fail over between advertisers if a node goes
down.

> **Note:** Tailscale subnet route HA failover requires the route to be
> approved on **each** advertising node individually in the admin console.
> The role does this automatically when `tailscale_api_key` is set.
