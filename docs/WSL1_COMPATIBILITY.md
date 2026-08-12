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

### 1. Environment Profile

When invoking the playbook, specify the target environment:

```bash
# Standard Linux workstation (all features)
ansible-playbook setup.yml

# WSL-1 or VDI environment (skip incompatible tasks)
ansible-playbook setup.yml -e "environment_profile=vdi"
```

### 2. Incompatibility Tags

Tasks that are incompatible with VDI/WSL-1 environments are tagged with incompatibility markers. The main incompatibility tag is:

- `requires_netfilter` — Tasks requiring iptables/netfilter kernel subsystem (firewall rules, network address translation, packet filtering, container networking)

These tags are declared in `group_vars/all.yml`:

```yaml
wsl1_incompatible_tags:
  - "requires_netfilter"
```

### 3. Conditional Skipping

Each task tagged with an incompatibility marker includes a `when` condition that skips it if:
- The environment profile is set to `vdi`, AND
- The task's tag is in the `wsl1_incompatible_tags` list

Example:

```yaml
- name: "Remove any tcp port 22 allow rules"
  community.general.ufw:
    delete: true
    port: 22
    proto: "tcp"
    rule: "allow"
  tags:
    - "requires_netfilter"
  when: not (environment_profile == 'vdi' and 'requires_netfilter' in wsl1_incompatible_tags)
```

This means:
- On standard Linux: task runs (firewall rules are configured)
- On WSL-1 with `environment_profile=vdi`: task is skipped (firewall unavailable)

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

**Tag:** `requires_netfilter`

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
     when: not (environment_profile == 'vdi' and '<tag>' in wsl1_incompatible_tags)
   ```

4. **Update group_vars/all.yml** — If adding a new incompatibility type:
   ```yaml
   wsl1_incompatible_tags:
     - "requires_netfilter"
     - "requires_new_feature"  # Your new tag
   ```

5. **Document in this file** — Add section under "Incompatible Tasks by Category".

6. **Test thoroughly** — Run the playbook on WSL-1 with `environment_profile=vdi` and verify:
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
ansible-playbook setup.yml -e "environment_profile=vdi" -vvv
```

Look for `when: not (...)` conditions evaluating to `False` — these indicate skipped tasks.

### Manually test a specific incompatible task

To bypass the skip condition and test if a task still fails (for troubleshooting):

```bash
ansible-playbook setup.yml -e "environment_profile=vdi" -e "wsl1_incompatible_tags=[]"
```

This clears the incompatible tags list, allowing all tasks to run. Use only for debugging.

---

## Future Enhancements

As more incompatibilities are discovered, expand the tag system:

```yaml
wsl1_incompatible_tags:
  - "requires_netfilter"      # Firewall, container networking
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
- `group_vars/all.yml` — Environment profiles and incompatibility tag list
- `README.md` — Environment Profiles section for usage examples
