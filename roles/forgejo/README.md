# Migrating the forge off its host, and back

A runbook for the window when the processor in `homelab` is away for warranty
replacement (Intel case 07019943). Nothing here is automatic: every role
involved is off on each host until a `host_vars` file turns it on.

Three services move together, because they all live on `homelab` and all have
to be somewhere while it is apart. The forge is this role; the other two are
`roles/calibre` (the `eBook` library at `books.bobbalisa.org`) and
`roles/foundry` (the game table at `game.bobbalisa.org`).

## What moves, and what does not

|                       |                                                                        |
| --------------------- | ---------------------------------------------------------------------- |
| Moves                 | the forge: git hosting, the web interface, the Debian package registry |
| Moves                 | the `eBook` library and the game table, through their own roles        |
| Moves, with limits    | Actions runners. See "The runner, and what actually bounds it"         |
| Follows automatically | the 25 local clones, because each `origin` is a hostname               |

## Before you start

Settle the version question, because it is the one that breaks silently.
`homelab` runs `Forgejo` **17.0.0**; `racknerd` carries the distribution
package at **15.0.12**. `Forgejo` migrates its schema forward only, so a 17
dump on a 15 binary does not downgrade — it refuses, or half-applies. The role
asserts this when `forgejo_restore_source_version` is set, and installs a
pinned upstream binary in `/usr/local/bin` rather than using the package.

The packaged install is left in place and shadowed by the unit this role
writes. Run `apt-mark hold forgejo` on `racknerd` so an upgrade cannot move a
binary that nothing is running. Do **not** hold `forgejo-runner`: the runner
tasks use the packaged one, so upgrades there are wanted.

## Where the name records actually live

**Not on `racknerd`.** This was wrong in an earlier version of this runbook
and is worth stating plainly, because acting on it would waste an afternoon:

- `bobbalisa.org` is hosted at **Hurricane Electric** (`ns1` through
  `ns5.he.net`), and records are edited in the web interface at `dns.he.net`.
- `knot` on `racknerd` is a **hidden primary** that is not in the zone's `NS`
  set and is not delegated at the registrar. What it actually serves is a set
  of small **delegated ACME challenge zones**, one per name — nothing else.

So repointing a service is a change at `dns.he.net`, by hand.

Two TTLs matter, and they are long: `forgejo` and `game` carry **86400**, and
`books` carries **172800**. A resolver that has cached the old answer keeps it
for that long. Drop these to 300 while you are in there — the move _back_
after the `RMA` is otherwise just as slow as the move out.

### Get the certificate before you move the name

The obvious order — repoint the name, then issue over `http-01` — is the slow
one, because `Let's Encrypt` may hold a cached `CNAME` for up to a day.
Instead, delegate the challenge name to `knot` and issue over `dns-01`, which
works while the service name still points at `homelab`:

1. At `dns.he.net`, add `NS` for `_acme-challenge.<name>.bobbalisa.org`
   pointing at `ns1.bobbalisa.org`. It is a _new_ record, so only negative
   caching applies — the `SOA` minimum, 900 seconds — and it is live in about
   fifteen minutes rather than a day.
2. On `racknerd`, add a scoped `ACL` for the existing `certbot_acme` key and a
   zone for that name. The three added on 2026-11-25 are in
   `/etc/knot/knot.conf`; copy one. Validate with `knotc conf-check` **before**
   `knotc reload`.
3. Issue it, with a `--dry-run` first:

   ```bash
   sudo certbot certonly --non-interactive \
     --authenticator dns-rfc2136 \
     --dns-rfc2136-credentials /etc/letsencrypt/secrets/rfc2136-bobbalisa.ini \
     --dns-rfc2136-propagation-seconds 30 \
     --key-type ecdsa \
     --cert-name <name>.bobbalisa.org -d <name>.bobbalisa.org
   ```

The key is scoped by `ACL` to `TXT` at exactly one name, so leaking it cannot
repoint anything. Renewal is unattended thereafter.

Note for `game` specifically: its certificate on `homelab` was **not** managed
by `certbot` at all. It was issued by `acme.sh` through the DNS API at Hurricane Electric, lives
in `/etc/nginx/certs/game.bobbalisa.org/`, expires 2027-01-06, and nothing on
that host would have renewed it. Moving it to the `certbot` path above fixes a
latent problem rather than merely relocating one.

## Moving the forge

1. **Take the dump, on `homelab`.** The only step that needs that host alive,
   so do it before the processor comes out.

   ```bash
   sudo systemctl stop forgejo
   sudo -u forgejo /usr/local/bin/forgejo dump \
     --config /etc/forgejo/app.ini --file /var/tmp/forgejo-dump.zip
   sudo systemctl start forgejo
   ```

   Stopping it first is not optional: a dump taken while the forge is running
   captures the database mid-write. Nothing may be pushed between the dump and
   the cutover, because anything pushed is not in the dump and does not travel.

2. **Send it straight to the target, not through the controller.** It is 4.2
   GiB. `ansible.builtin.copy` would stream it through the controller, so set
   `forgejo_restore_dump_remote: true` and put it there with `rsync` instead.
   `homelab` has no key on `racknerd`, so it goes via the controller in two
   hops — use `--partial --inplace` and **checksum both ends**; a 17-minute
   WAN transfer is long enough to go wrong quietly.

3. **Set the `host_vars`** — see `host_vars/racknerd.yml`, which carries the
   whole set with the reasoning attached. `forgejo_memory_max` is not optional
   there, and the reason is not the forge: that host has 4.3 GiB of memory and
   also runs `knot` and `opensmtpd`, this estate's authoritative name service
   and its mail. Unbounded, a spike lets the kernel choose a victim.

4. **Run it**, with the runner held back until the name resolves here:

   ```bash
   ansible-playbook setup.yml -l racknerd --tags forgejo \
     -e forgejo_runner_enabled=false
   ```

5. **Repoint the name** at `dns.he.net`: `forgejo.bobbalisa.org` from `CNAME
homelab.bobbalisa.org` to `CNAME racknerd.bobbalisa.org`.

6. **Repoint it on the LAN too**, which is a separate control and easy to
   forget. The router at `10.0.0.1` answers these names itself:

   ```bash
   ssh root@10.0.0.1 "uci show dhcp | grep -i address"
   ```

   Its `dnsmasq` `address` list pins `forgejo`, `books`, `game` and `homelab`
   to `10.0.0.2`. This takes effect immediately and is what makes the long
   public TTL survivable.

   **An `address=` entry is not enough on its own for a name that is a `CNAME`
   upstream,** which cost an hour on 2026-11-25. `address=/name/<ipv4>` is
   applied **per record type**: `dnsmasq` answers the `A` query locally and
   _forwards the `AAAA` query upstream_, where the old `CNAME` still points at
   `homelab`. `systemd-resolved` asks for both, gets a `CNAME` chain in the
   `AAAA` answer, follows it, and resolves the name to `10.0.0.2` — so the
   client reaches the host that was just stopped and sees `502`, while
   `dig A` against the same router returns the right address and everything
   looks correct. An `/etc/hosts` entry on the router does not fix it either;
   `AAAA` is still forwarded.

   What fixes it is declaring the name local so nothing is ever forwarded for
   it, which makes `AAAA` return `NODATA`:

   ```bash
   uci add_list dhcp.@dnsmasq[0].server="/forgejo.bobbalisa.org/"   # no upstream
   uci commit dhcp && /etc/init.d/dnsmasq restart
   ```

   Verify **both** types, not just `A`:

   ```bash
   dig +short @10.0.0.1 forgejo.bobbalisa.org A      # the new address
   dig @10.0.0.1 forgejo.bobbalisa.org AAAA +short   # must be empty
   ```

   The names also appear bare in the router's `/etc/hosts` (`forgejo`), which
   a client using the short name will pick up, so update those too. And flush
   the client: `resolvectl flush-caches`.

   Once the public `CNAME` has moved, these overrides are no longer doing
   anything and can come out — the upstream answer is then correct for both
   record types by itself.

7. **Then register the runner** and stop the old forge:

   ```bash
   ansible-playbook setup.yml -l racknerd --tags forgejo
   ssh homelab "sudo systemctl disable --now forgejo"
   ```

8. **Verify a clone works end to end** before trusting it:

   ```bash
   git -C /tmp clone \
     ssh://forgejo@forgejo.bobbalisa.org:65432/pillarsdotnet/timesheet.git
   ```

### Every client with a clone sees a host key warning

The name now reaches a different machine, so `ssh` reports
`REMOTE HOST IDENTIFICATION HAS CHANGED` on every host that has cloned over
`ssh`. That is correct behaviour, not a problem to click through blindly.
Confirm the new key is the host you think it is before trusting it — the key
`racknerd` presents under its own address is already in `known_hosts`, so the
two fingerprints can simply be compared:

```bash
ssh-keygen -F "[96.44.137.73]:65432" -l                  # already trusted
ssh-keyscan -p 65432 -t ed25519 forgejo.bobbalisa.org 2>/dev/null | ssh-keygen -lf -
ssh-keygen -R "[forgejo.bobbalisa.org]:65432"            # drop the stale one
```

## Three things that made the restore fail silently

All three were found on 2026-11-25 by reading the dump before trusting it.
Each produces a forge that starts, serves, authenticates — and is broken.

- **The repositories are not where the layout suggests.** `Forgejo`'s default
  `REPO_ROOT_PATH` is `APP_DATA_PATH/forgejo-repositories`, and `APP_DATA_PATH`
  is `WORK_PATH/data`, so they live at
  `/var/lib/forgejo/data/forgejo-repositories`. The dump calls that directory
  `repos/` regardless. This role restored it to `forgejo_home` until that was
  fixed, which yields a forge with **no repositories at all**. Now it restores
  to `forgejo_repo_root` and asserts a non-zero count of `*.git` afterwards.
- **`authorized_keys` is not in the dump.** `git`-over-`ssh` works by `Forgejo`
  writing `command=` lines into the run account's `authorized_keys`, and that
  file lives at `forgejo_home/.ssh` — outside the data directory the dump
  packs. The restore now runs `forgejo admin regenerate keys` from the
  restored rows. Without it every clone and push is refused, which looks like
  a networking fault and is not one.
- **A wildcard `listen 443` takes the whole host down.** `tailscaled` on
  `racknerd` holds the `tailnet` address's port 443, and an `nginx` listener that
  cannot bind does not merely drop its own virtual host — the reload aborts and
  `library.bobbalisa.org` and `bobvincent.com` go with it. Hence
  `forgejo_nginx_listen_addresses`, set to the two explicit addresses. The
  existing virtual host for `library` carries the same warning in a comment.

Also carried over deliberately: the blocked user-agent map. On `homelab`,
`meta-externalagent` was **15.9% of all traffic** (29439 of 185609 requests)
and had never once fetched `robots.txt`. It matters more on `racknerd` — four
cores against twenty-four — so `forgejo_nginx_blocked_agents` keeps it.

## The runner, and what actually bounds it

An earlier version of this runbook said to leave the runners behind, and that
raising or lowering their count did not matter because the limit is per-compile
rather than concurrent. The second half of that is right. The advice that
followed it was not:

> put `MemoryMax=` on the runner unit, so an overrun is reclaimed from the
> runner rather than from the name service

**That does not work with the docker backend.** A job's compiler does not run
in the runner unit's cgroup: the runner asks `dockerd` to create a container,
and that container is a child of `docker.service`. `MemoryMax` on
`forgejo-runner.service` therefore caps a Go daemon that idles at a few tens of
MiB and caps nothing about the build.

The control that does work is `--memory` on the job container, which the
kernel enforces on the cgroup `dockerd` creates. A compile that exceeds it is
killed inside its own container and the job fails with something the log
explains — instead of the kernel picking a victim across the whole machine,
where the victim may be `knot`.

So as of 2026-11-25 `racknerd` runs a runner, deliberately and with limits:

- `forgejo_runner_capacity: 1` — four cores at 2.3 GHz against the 24 in `homelab`.
- `forgejo_runner_container_memory: 2g` — the floor, not a guess: single
  `rustc`/`g++` translation units in these builds were measured at 1–2 GiB,
  so less than this fails builds that should pass.
- `forgejo_runner_memory_max: 512M` — set because it is free, not because it
  protects anything. See above.
- **4 GiB of swap added by hand**, bringing that host to 6.5 GiB total
  (`/swapfile`, in `/etc/fstab` beside the existing `vda3` partition). Not
  managed by this repository. It is the cushion that makes a 2 GiB build
  container, the forge, the library and the game table coexist in 4.3 GiB of
  RAM.

Registration is the one step that cannot be declarative, because it trades a
one-time token for durable credentials. The role generates the token from the
forge on the same host and registers only when `.runner` is absent —
re-registering would appear in the forge as a second runner and orphan the
first. It must therefore run **after** the name resolves to this host, or the
runner registers against whatever is still answering.

## Moving the library and the table

Both are `rsync` plus a role. Neither has a dump format, and both hold live
databases, so the sequence is: pre-seed hot, then re-sync with the service
stopped.

```bash
# pre-seed while they are still running (minutes of copying, no downtime)
rsync -a --rsync-path="sudo rsync" homelab:/srv/calibre/ <stage>/calibre/
rsync -a --rsync-path="sudo rsync" homelab:/home/foundry/ <stage>/foundry/
# ... and push to racknerd the same way

# at cutover: stop, re-sync the delta, hand ownership over
ssh homelab "sudo systemctl disable --now calibre-server foundryvtt"
# re-run the two rsyncs - only the delta moves
ssh racknerd "sudo chown -R calibre:calibre /srv/calibre
              sudo chown -R foundry:foundry /home/foundry"
ansible-playbook setup.yml -l racknerd --tags calibre,foundry
```

The recursive `chown` is a migration step rather than something the roles do,
because `rsync` preserves numeric ownership and the accounts get different
`UID`s on a different host. Doing it recursively on every role run would mean
walking thousands of files to change nothing.

Three things specific to these two:

- **`Foundry`'s licence permits one running instance.** Stopping `homelab`'s
  is part of the move, not a tidy-up afterwards. The data directory carries the
  licence as well as the worlds, which is why it is copied rather than rebuilt.
- **`Foundry` needs the `WebSocket` upgrade headers**, and `nginx` needs a
  `map` to supply `$..._connection_upgrade`. Without them the table loads in
  the browser and then never joins. `roles/foundry` ships both; the variable is
  named for the role so two roles cannot collide on one `map`.
- **`calibre` does not fail when it cannot bind, it binds the public address
  instead.** This is the one to remember. Its log says
  `Trying to bind to the default interface` and it carries on, so a port
  conflict silently converts a loopback-only configuration into a publicly
  listening one. On `racknerd`, `sitewatch.service` already held
  `127.0.0.1:8080`, and `calibre` came up on `96.44.137.73:8080` serving the
  whole library; only the firewall's default-deny kept it unreachable.
  `roles/calibre` now reads back the bound address and fails if it is not the
  configured one, and `calibre_port` is 8081 there. Check what holds the port
  before assuming the default is free.
- **`calibre` binds loopback here, not `0.0.0.0`.** On `homelab` the wide bind
  let reader apps reach `http://10.0.0.2:8080` directly, which was safe behind
  a router that forwards only 80 and 443. `racknerd` has a public address and
  no LAN, so a reader app configured with the bare address and port must be
  pointed at `https://books.bobbalisa.org` instead.

## What else that host was doing

Three services are the obvious part of the move. An audit of `homelab` on
2026-11-25 found four background jobs that would also have gone away with it,
and two that correctly stay. Worth keeping, because none of them is visible
from the services themselves.

### Moved, each now a role

- **`roles/ddns`** — the site's Hurricane Electric dynamic DNS record. The
  house has a Comcast-dynamic address and the router forwards 80, 443 and
  65432 to one LAN address, so `homelab.bobbalisa.org` is how anything outside
  finds the house at all. It is also what the library's disaster copy resolves.
  Nothing would have refreshed it, and the record goes stale at the next
  rotation. Now on `acermagic`; the record keeps its name because it names the
  **site**, not the machine.
- **`roles/sccache`** — the shared Rust object cache, an `nginx` WebDAV store.
  The endpoint was written into `timesheet`'s workflow as
  `http://10.0.0.2:8088`, and a LAN address is not reachable from a runner on
  a VPS. Note what this was _not_: that workflow's own comment says an
  unreachable cache "degrades to a miss, not a failure", so losing it would
  have made those builds slower rather than broken. The workflow now names
  `sccache.bobbalisa.org`, which the runner gives each job container through
  `--add-host`, so no address appears in the workflow and the cache can move
  again freely.
- **`roles/library_peer`** — receives the Home Library hourly disaster copy.
  See below; this one is subtler than it looks.
- **the plain `ccache` directory** — 169 MB, bind-mounted into job containers
  as `/ccache-remote`, and `NFS`-exported to `bobse16` at `/mnt/ccache`. The
  `NFS` mount is `soft,nofail,x-systemd.automount`, so it degrades rather than
  hanging when the server goes; the copy on `racknerd` was seeded so the first
  build there is not cold.

### The library copy follows the address, not a setting

This is the one worth understanding before touching it. The active library node
pushes an hourly copy to **its failover peer**, and there is no separate
backup target to point elsewhere. The temptation is to change `PEER` in
`/etc/default/home-library-failover` on `racknerd` — don't. `PEER` is also the
failover identity, so that would nominate a host which cannot actually serve
the library, trading a working failover arrangement for a 1 MB database.

What happens instead is better and needs no change on the sender at all:

- the sender addresses its peer **by name**, which resolves to the house;
- the router forwards **65432 to 10.0.0.2**;
- so once `acermagic` holds that address, the copy lands there.

`roles/library_peer` is only the receiving half: an account for the files to
belong to, the directory, and one `authorized_keys` entry. Two details matter:

- **Authorise only the sync key**, not the failover negotiation key. A host
  that cannot serve the library should not answer questions about who owns it.
- **The probe tolerates a forced command.** The sender runs
  `ssh ... peer true` first and treats **only exit 255** - `ssh`'s own
  transport failure - as "offline". A forced `rrsync` command rejecting `true`
  with some other code is deliberately ignored, which is why one write-only
  `rrsync` entry is sufficient and no shell access is needed.

The key is confined: `restrict,command="/usr/bin/rrsync -wo <dir>"`, so it may
write one directory and do nothing else.

### Three things the address takeover does not do by itself

Done on 2026-11-25 with `homelab` powered off. Taking the address worked first
time; three things that depend on it did not, and none of them reported an
error that pointed at the cause.

- **`Samba` binds its addresses at startup.** With `bind interfaces only = yes`
  and `interfaces = lo wlp1s0`, `smbd` resolves those names to addresses when
  it starts — so an address added to an interface afterwards is simply not
  bound, and a client aimed at it gets `NT_STATUS_CONNECTION_REFUSED` while
  `smbd` is plainly running and healthy. `systemctl restart smbd nmbd` after
  the takeover.
- **The sending side's `known_hosts` has the wrong key now**, because the name
  reaches a different machine. The library sync passes
  `StrictHostKeyChecking=accept-new`, which accepts an _unknown_ host and
  refuses a _changed_ one, so `ssh` exits 255 and the script reports
  `peer unreachable or refusing the sync key` — which reads like a network
  problem and is not one. Clear the stale entry from **root's** `known_hosts`
  on the sender, after checking the offered key is the host you expect:

  ```bash
  ssh-keygen -F "[homelab.bobbalisa.org]:65432" -f /root/.ssh/known_hosts -l
  ssh-keyscan -p 65432 -t ed25519 homelab.bobbalisa.org | ssh-keygen -lf -
  ssh-keygen -R "[homelab.bobbalisa.org]:65432" -f /root/.ssh/known_hosts
  ```

- **The library sync thinks the peer is already current.** It records a
  fingerprint of the _source_ database in
  `/var/lib/home-library/.sync/last-synced` and exits early when it matches, so
  after the peer changes identity it copies nothing until the database next
  changes — and the new peer sits empty meanwhile. Delete that file once:

  ```bash
  rm -f /var/lib/home-library/.sync/last-synced
  systemctl start home-library-db-sync
  ```

Verified afterwards: `ssh` to the address reaches the new host, the shares
answer at `\\10.0.0.2` with the same names and credentials so no `Windows`
client needs touching, and the copy arrived as 970752 bytes plus 218 cover
files, 952 books, `integrity_check` ok.

One trap to avoid while checking: do not run `sqlite3` against the standby
database to test it before the first copy arrives. `sqlite3` **creates** the
file, so it leaves a zero-byte `library.db` that looks like a broken sync.
Open it read-only instead: `sqlite3 'file:...library.db?mode=ro'`.

### A moved name is pinned in more places than DNS

Moving these services broke four things, each of which was a name cached or
hard-coded somewhere that `DNS` never reaches. None reported a cause that
pointed at the migration. Check all four:

| where                                                 | symptom                                                    |
| ----------------------------------------------------- | ---------------------------------------------------------- |
| `known_hosts` on every machine that clones            | `REMOTE HOST IDENTIFICATION HAS CHANGED`                   |
| root's `known_hosts` on the library sync's **sender** | `peer unreachable or refusing the sync key`                |
| `/etc/hosts` on a LAN client                          | `apt update` fails; the forge is unreachable               |
| a workflow file                                       | a hard-coded `10.0.0.2` endpoint, unreachable from a `VPS` |

The `/etc/hosts` one is the easiest to miss and the most confusing, because it
surfaces as a **package manager** failure. `acermagic` carried a hand-made
line that was correct for years:

```text
10.0.0.2 homelab.lan homelab k8scp cp game.bobbalisa.org game forgejo.bobbalisa.org forgejo
```

Once that host took 10.0.0.2 the line pointed it at **itself** for the forge,
and because the `Debian` package registry is served by the forge, every
`apt update` failed with `Could not connect to forgejo.bobbalisa.org:443
(10.0.0.2) - connect (111: Connection refused)`. The role that wanted to
install `nut` failed on an apt cache update, which is about as far from "a
service moved" as a message can get.

Keep `homelab`, `k8scp` and `cp` in such a line - the first follows the
address deliberately, and the router answers neither of the others - and strip
only the names that moved. Then `resolvectl flush-caches`, because the stale
answer outlives the edit.

Worth sweeping for, rather than waiting to be bitten:

```bash
for h in bobse16 acermagic racknerd; do
  ssh "$h" 'grep -nE "bobbalisa" /etc/hosts'
done
```

### Correctly staying with the hardware

- **`NUT`** — the `UPS` is physically plugged into that host.
- **`diagnostics`, `fancontrol`, `rasdaemon`, `kdump`** — the telemetry that
  exists to catch this very fault.
- **`ollama` and 4.9 GB of models** — GPU-backed. `racknerd` has four cores,
  no GPU and 4.3 GiB of RAM, so moving it would produce something unusable. It
  is simply unavailable for the duration; that is the right answer, not an
  oversight.

Also checked and needing nothing: `gitlab-runner` and `gitlab_deploy` are
inactive and disabled, `libvirtd` is not running and no guests are defined,
and `/etc/exports` is empty apart from the `ccache` entry above.

## Coming back

Dump on `racknerd`, restore on `homelab`, repoint the records, then set
`forgejo_enabled`, `calibre_enabled` and `foundry_enabled` to false for
`racknerd` and re-run. The roles do not uninstall: they stop managing. Remove
`/var/lib/forgejo`, `/srv/calibre` and `/home/foundry` there by hand once each
service is confirmed healthy at home, and not before.

Lower those TTLs on the way out and the return trip is minutes rather than a
day.

## The printer, which is a separate problem

`homelab` serves the `USB`-attached EPSON at `ipp://localhost:65431` through
`ipp-usb`, and several print configurations hard-code **10.0.0.2** — an address
`homelab` holds on a lease.

`acermagic` was configured for both on 2026-11-25 (`printing_ipp_usb_interface:
"all"` and `printing_ipp_usb_ipv6: "disable"` in its `host_vars`), so it is
ready. Note what is physical: the printer is attached by `USB`, so the cable
has to move. `ipp-usb.service` is `static` and started by `udev` from
`71-ipp-usb.rules` when the device appears, so it correctly shows `inactive`
until then.

The address is handled by `bootstrap_extra_addresses` — see
`roles/bootstrap/tasks/ip_alias.yml`, which refuses to add an address something
else already answers on.

```yaml
# host_vars/acermagic.yml, during the window only
bootstrap_extra_addresses:
  - "10.0.0.2/24"
```

Apply it on its own, which is what the `ip_alias` tag is for:

```bash
ansible-playbook setup.yml -l acermagic --tags ip_alias
```

Not `--tags bootstrap`: the `bootstrap` role is included without a tag of that
name, so such a run reports a handful of tasks and changes nothing, which reads
as success. The tag was added on 2026-11-25 for exactly this reason - the only
other way in is a full `bootstrap` run, whose `pre_tasks` prompt for an ssh
port and a public key, which is no way to move an address while a host is down.

Three things worth knowing before setting it:

- **Only do it with `homelab` actually off.** The role checks, but the check is
  a courtesy, not a guarantee.
- **Port 65432 is forwarded there too**, which is the useful part: it is how
  the library's hourly disaster copy reaches the host holding the address, and
  how the house is reachable by `ssh` from outside. `acermagic` listens on that
  port already.
- The router forwards 80 and 443 to 10.0.0.2, so `acermagic` inherits inbound
  web traffic for that address while it holds it. Harmless if it serves nothing
  there, but confirm rather than assume — and note that after this migration
  those names resolve elsewhere anyway.

Name resolution is otherwise not a concern: split-horizon moved to the router
at 10.0.0.1 on 2026-11-22 and `dnsmasq` on `homelab` is masked. One caveat if a
new host joins — the router does not answer `k8scp` or `cp`; those come from
`/etc/hosts`, which the existing hosts already carry.
