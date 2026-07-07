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
