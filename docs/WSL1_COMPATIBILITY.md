# WSL-1 and VDI Environment Compatibility

This document describes how the Ansible bootstrap playbook handles incompatibilities with Windows Subsystem for Linux (WSL-1) and virtualized environments (VDI).

## Overview

WSL-1 is a compatibility layer that runs Ubuntu user-space utilities on the Windows kernel. It has significant limitations compared to full Linux:

- **No iptables/netfilter support** — kernel firewall features unavailable
- **Limited systemd support** — service management differs from full Linux
- **No seccomp/AppArmor** — security frameworks not available
- **No device passthrough** — hardware access limited

When deploying to WSL-1 or VDI environments, certain Ansible tasks will fail because they require Linux kernel features that are unavailable. Rather than silently ignoring errors, this playbook uses a declarative tag-based skipping mechanism.

## How It Works

Two independent things are being decided, and they are kept separate:

| Axis | Question | Driven by |
|---|---|---|
| **Capability** | Does this kernel *support* the operation? | Automatic WSL detection (`bootstrap_wsl_version`) |
| **Trust** | Do we *want* this software here? | `environment_profile` (`standard` / `vdi`) |

A WSL-1 host cannot run systemd no matter what profile you pass, and a VDI that
runs Linux natively is fully capable but may still want third-party repos left
out. Conflating the two meant WSL-1 skips only happened if you remembered to
pass `-e environment_profile=vdi`, and passing that on a native VDI wrongly
disabled service management.

### 1. Capability: automatic WSL detection

Nothing to pass. `roles/bootstrap/defaults/main.yml` derives the WSL generation
from the gathered kernel release:

```yaml
bootstrap_wsl_version: >-
  {{ 2 if 'wsl2' in bootstrap_kernel_release
     else 1 if 'microsoft' in bootstrap_kernel_release
     else 0 }}
```

`0` = native Linux (bare metal, VM, or natively-run VDI), `1` = WSL-1,
`2` = WSL-2. WSL-1 kernels read `4.4.0-NNNNN-Microsoft`; WSL-2 kernels read
`…-microsoft-standard-WSL2`. No native Ubuntu kernel contains either string.

### 2. Incompatibility tags

Capability-dependent tasks are tagged with what they need. The vocabulary is
declared in `roles/bootstrap/defaults/main.yml`:

```yaml
wsl1_incompatible_tags:
  - "requires_dbus"
  - "requires_gui"
  - "requires_netfilter"
  - "requires_systemd"
```

- `requires_dbus` — needs a running dbus system bus
- `requires_gui` — needs a graphical session
- `requires_netfilter` — needs the iptables/netfilter subsystem (firewall rules,
  NAT, packet filtering, container networking)
- `requires_systemd` — needs systemd for service management

These are declared in **role defaults**, not `group_vars/all.yml`. That file is
untracked (see README "Repository layout"), so declaring them there left a fresh
clone with nothing defining them, and every gated task died with
`Error while evaluating conditional: 'environment_profile' is undefined`.

`requires_dbus` and `requires_gui` are part of the policy but no task carries
them yet: dbus-dependent work (`bluetooth.yml`, `wifi_powersave.yml`) is already
gated on the service existing in `ansible_facts.services`, and GUI work is gated
on `bootstrap_gui`, which is false unless `display-manager.service` is currently
running — and a host with no systemd has no such service, so WSL-1 reads as
headless on its own. Tag new tasks with them rather than
inventing a parallel mechanism.

### 3. Conditional skipping

A tagged task is skipped when a WSL-1 kernel is detected **and** its tag is in
`wsl1_incompatible_tags`:

```yaml
- name: "Remove any tcp port 22 allow rules"
  community.general.ufw:
    delete: true
    port: 22
    proto: "tcp"
    rule: "allow"
  tags:
    - "requires_netfilter"
  when: >-
    not (bootstrap_wsl_version | int == 1 and
         'requires_netfilter' in wsl1_incompatible_tags)
```

This means:
- On native Linux, including a natively-run VDI: task runs
- On WSL-1: task is skipped automatically, no flags required
- On WSL-2: task runs (real kernel; enable systemd in `/etc/wsl.conf` if needed)

### 4. Where the gates actually are

Only `roles/bootstrap` carries these `when` gates, because role defaults are in
scope for that role's own tasks and handlers. The tagged tasks in
`roles/tailscale`, `roles/printing` and `roles/sources` are tagged but
**not** gated, so on WSL-1 they still need the tag-skip flags:

```bash
ansible-playbook setup.yml --skip-tags requires_netfilter,requires_systemd
```

## Incompatible Tasks by Category

### Firewall / UFW Tasks

**Location:** `roles/bootstrap/tasks/sshd.yml`

Tasks:
- "Remove any tcp port 22 allow rules"
- "Allow tcp port 65432 (SSH)"

**Reason:** WSL-1 kernel doesn't support iptables/netfilter subsystem.

**Impact:** UFW firewall rules cannot be configured. SSH port forwarding rules must be managed via Windows Firewall or network layer instead.

**Workaround:** Use Windows Defender Firewall (WDF) to configure port forwarding and access control. SSH will still work, but at the Windows network boundary rather than within WSL-1.

**Tag:** `requires_netfilter`

---

### Service Management / Systemd Handlers

**Location:** `roles/bootstrap/handlers/main.yml`

Handlers:
- "Reload NetworkManager"
- "Reload symlink-run-utmp"
- "Restart bluetooth.service"
- "Restart ssh.service"
- "Restart ssh.socket"

**Reason:** WSL-1 doesn't properly support systemd service management. Services are in "unknown state" and cannot be reliably restarted or reloaded.

**"Reload NetworkManager" is different:** it is gated on
`bootstrap_wsl_version | int == 0`, so it is skipped on **both** WSL-1 and WSL-2.
Under either, the network interfaces are owned by Windows and there is no
NetworkManager to reload. A VDI that runs Linux natively is an ordinary Linux
host here and does get the reload — which is why this gate keys off WSL
detection rather than off `environment_profile`.

**Impact:** Services configured by the playbook may not restart after configuration changes. SSH will continue running if already started before playbook execution, but changes to SSH config won't take effect until next manual restart.

**Workaround:** After running the playbook on WSL-1, manually restart services from Windows PowerShell:
```powershell
wsl -d Ubuntu -- sudo service ssh restart
wsl -d Ubuntu -- sudo service bluetooth restart
```

Or within WSL-1 shell:
```bash
sudo service ssh restart
sudo service bluetooth restart
```

**Tag:** `requires_systemd`

---

### Kubernetes Networking Tasks

**Location:** `roles/kubernetes/tasks/worker.yml` (multiple)

Tasks:
- "Reset iptables before joining to remove old CNI and kube-proxy chains"
- "Add iptables DNAT rules to redirect VIP to active control plane"
- "Add iptables MASQUERADE so VIP traffic returns via Tailscale"
- "Save iptables rules for boot restoration"
- "Create systemd unit to restore iptables rules on boot"

**Reason:** Kubernetes networking requires NAT rules and packet filtering via iptables. WSL-1 doesn't support these operations.

**Impact:** Container networking cannot be fully configured. Kubernetes will not function properly in WSL-1.

**Workaround:** Do not deploy Kubernetes workers to WSL-1 environments. Kubernetes requires full kernel features available only on bare-metal or hypervisor-backed VMs.

**Tag:** none — these tasks are **not** tagged or gated today, so they will fail
rather than skip if the role is run on WSL-1. That is acceptable only because the
`kubernetes` role is commented out in `setup.yml` and, per the workaround above,
should never target WSL-1. Tag them `requires_netfilter` if that changes.

---

## Adding New Incompatible Tasks

When you discover a task that fails in WSL-1/VDI environments:

1. **Verify the failure is unavoidable** — Run the task on WSL-1 and confirm it fails due to missing kernel features, not configuration issues.

2. **Document the incompatibility** — Add an entry to this file explaining:
   - Task name and location
   - Reason for incompatibility
   - Impact on VDI deployments
   - Suggested workarounds (if any)

3. **Add incompatibility tag** — Create a new tag if needed (or use existing):
   ```yaml
   - name: "Example task"
     some_module: ...
     tags:
       - "requires_netfilter"  # or appropriate tag
     when: >-
       not (bootstrap_wsl_version | int == 1 and
            '<tag>' in wsl1_incompatible_tags)
   ```

   Outside `roles/bootstrap`, `bootstrap_wsl_version` and
   `wsl1_incompatible_tags` are not in scope (role defaults do not cross role or
   play boundaries), so either add them to that role's own `defaults/main.yml`
   or rely on `--skip-tags` for it.

4. **Update roles/bootstrap/defaults/main.yml** — If adding a new
   incompatibility type:
   ```yaml
   wsl1_incompatible_tags:
     - "requires_netfilter"
     - "requires_new_feature"  # Your new tag
   ```

   Do **not** move this to `group_vars/all.yml`: that file is untracked, so a
   variable defined only there is undefined on every other clone.

5. **Document in this file** — Add section under "Incompatible Tasks by Category".

6. **Test thoroughly** — Run the playbook on WSL-1 and verify:
   - The incompatible task is skipped (not silently failed)
   - Other tasks continue normally
   - No downstream tasks depend on the skipped task's output

---

## Debugging

### View tasks that would be skipped

To see which tasks are incompatible without running them:

```bash
grep -r "requires_netfilter" roles/*/tasks/*.yml
```

### Run playbook with verbose output

```bash
ansible-playbook setup.yml -vvv
```

Look for `when: not (...)` conditions evaluating to `False` — these indicate skipped tasks.

To check what the detection decided on a host:

```bash
ansible <host> -m ansible.builtin.debug -a 'var=ansible_facts.kernel'
```

### Manually test a specific incompatible task

To bypass the skip condition and test if a task still fails (for troubleshooting):

```bash
ansible-playbook setup.yml -e "wsl1_incompatible_tags=[]"
```

This clears the incompatible tags list, allowing all tasks to run. Use only for debugging.

The reverse — forcing the WSL-1 skips on a host that is not WSL-1 — is
`-e "bootstrap_wsl_version=1"`.

---

## Future Enhancements

As more incompatibilities are discovered, expand the tag system:

```yaml
wsl1_incompatible_tags:
  - "requires_dbus"           # dbus system bus
  - "requires_gui"            # Graphical session
  - "requires_netfilter"      # Firewall, container networking
  - "requires_systemd"        # Service management
  - "requires_seccomp"        # Seccomp sandboxing (future)
  - "requires_apparmor"       # AppArmor security profiles (future)
  - "requires_device_access"  # Hardware device passthrough (future)
```

Each tag should:
- Be specific to a kernel feature or subsystem
- Be documented in this file
- Be applied consistently across all incompatible tasks
- Be referenced in `group_vars/all.yml` with a comment explaining its purpose

---

## Related Configuration

See also:
- `roles/bootstrap/defaults/main.yml` — WSL detection and the incompatibility tag list
- `roles/sources/defaults/main.yml` — `environment_profile` and the VDI repo/package skip lists
- `README.md` — Environment Profiles section for usage examples
