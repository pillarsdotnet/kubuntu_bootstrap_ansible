# Migrating the forge off its host, and back

A runbook for the window when the processor in `homelab` is away for warranty
replacement. Nothing here is automatic: the role is off on every host until a
`host_vars` file turns it on.

## What moves, and what does not

|                       |                                                                        |
| --------------------- | ---------------------------------------------------------------------- |
| Moves                 | the forge: git hosting, the web interface, the Debian package registry |
| Does not move         | Actions runners. See "Why the builds stay behind"                      |
| Follows automatically | the 25 local clones, because each `origin` is a hostname               |

## Before you start

Settle the version question, because it is the one that breaks silently.
`homelab` runs `Forgejo` **17.0.0**; `racknerd` carries the distribution
package at **15.0.12**. `Forgejo` migrates its schema forward only, so a 17
dump on a 15 binary does not downgrade — it refuses, or half-applies. The role
asserts this when `forgejo_restore_source_version` is set, and installs a
pinned upstream binary in `/usr/local/bin` rather than using the package.

The packaged install is left in place and shadowed by the unit this role
writes. Run `apt-mark hold forgejo forgejo-runner` on `racknerd` so an upgrade
cannot move a binary that nothing is running.

## Moving it

1. **Take the dump, on `homelab`.** This is the only step that must happen
   while that host is alive, so do it before the processor comes out.

   ```bash
   sudo systemctl stop forgejo
   sudo -u forgejo /usr/local/bin/forgejo dump \
     --config /etc/forgejo/app.ini --file /var/tmp/forgejo-dump.zip
   sudo systemctl start forgejo
   ```

   Stopping it first is not optional. A dump taken while the forge is running
   captures the database mid-write, and the result is neither the old state
   nor the new one.

2. **Fetch it to the controller**, then set the `host_vars` for `racknerd`:

   ```yaml
   forgejo_enabled: true
   forgejo_app_name: "Forgejo on racknerd"
   forgejo_domain: "forgejo.bobbalisa.org"
   forgejo_root_url: "https://forgejo.bobbalisa.org/"
   forgejo_restore_dump: "/path/to/forgejo-dump.zip"
   forgejo_restore_source_version: "17.0.0"
   forgejo_memory_max: "2G"
   forgejo_tls_cert: "/etc/letsencrypt/live/forgejo.bobbalisa.org/fullchain.pem"
   forgejo_tls_key: "/etc/letsencrypt/live/forgejo.bobbalisa.org/privkey.pem"
   ```

   On `racknerd`, `forgejo_memory_max` is not optional, and the reason is not
   the forge. That host has 4.3 GiB of memory and also runs `knot` and
   `opensmtpd` — the authoritative name service for this estate, and its mail.
   Unbounded, a spike in the forge lets the kernel pick a victim, and it may
   pick the name service. Bounded, the forge is reclaimed from first.

3. **Get the certificate first.** The template for the virtual host references
   the paths above, and `nginx` will not start without them. There is already
   `nginx` on `racknerd` with a certificate for `library.bobbalisa.org`, so
   this is a known path.

4. **Run it**, then repoint the name records. `knot` is authoritative for the
   zone on `racknerd` itself, so this is a local edit rather than a registrar
   ticket.

5. **Verify a clone works end to end** before trusting it:

   ```bash
   git -C /tmp clone \
     ssh://forgejo@forgejo.bobbalisa.org:65432/pillarsdotnet/timesheet.git
   ```

## Why the builds stay behind

The runners are not part of this. `racknerd` has 4 cores at 2.3 GHz against
the 24 in `homelab`, so roughly a tenth of the throughput — survivable. The
binding constraint is memory: a single `rustc` or `g++` translation unit in
these builds can take 1–2 GiB, and 3.6 GiB is available in total. Reducing the
runner count does not help, because the limit is per-compile, not concurrent.

So during the window, publish nothing. The forge serves clones and the
existing registry; packages get rebuilt when it comes home. If builds there
turn out to be unavoidable, add swap first — 86 GiB is free — and put
`MemoryMax=` on the runner unit, so an overrun is reclaimed from the runner
rather than from the name service.

## Coming back

Dump on `racknerd`, restore on `homelab`, repoint the records, then set
`forgejo_enabled: false` for `racknerd` and re-run. The role does not
uninstall: it stops managing. Remove `/var/lib/forgejo` by hand once the forge
is confirmed healthy at home, and not before.

## The printer, which is a separate problem

The host `homelab` serves the USB-attached EPSON at `ipp://localhost:65431`
through `ipp-usb`, and several print configurations hard-code **10.0.0.2**.
That address is held by `homelab` on a lease.

The host `acermagic` can take both, but note what is physical: the printer is
attached by USB, so the cable has to move. `CUPS` already runs there from
`roles/printing` with `Allow all`, and `ipp-usb` is now named by that role
rather than arriving as a recommendation of something else.

The address is handled by `bootstrap_extra_addresses` — see
`roles/bootstrap/tasks/ip_alias.yml`, which refuses to add an address that
something else is already answering on, because two hosts sharing one address
is worse than neither holding it.

```yaml
# host_vars/acermagic.yml, during the window only
bootstrap_extra_addresses:
  - "10.0.0.2/24"
```

Two things worth knowing before setting it:

- **Only do it with `homelab` actually off.** The role checks, but the check
  is a courtesy, not a guarantee.
- The router forwards 80 and 443 to 10.0.0.2 — not 65432, per the note in the
  `app.ini` on `homelab`. So `acermagic` inherits inbound web traffic for that
  address while it holds it. Harmless if it serves nothing there, but worth
  confirming rather than assuming.

One more: `dnsmasq` on `homelab` answers on 10.0.0.2 with `host-record`
entries for `forgejo`, `books`, `game`, `k8scp` and `cp`. The host `acermagic`
resolves through the router at 10.0.0.1 and most of the estate probably does
too, but anything pointed at 10.0.0.2 for name service loses those entries
when `homelab` goes. Check before you need them.
