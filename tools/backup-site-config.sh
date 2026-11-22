#!/bin/bash
# Copyright (c) 2026 Robert August Vincent II <pillarsdotnet@gmail.com>
#
# Back up the parts of this checkout that git deliberately does not carry.
#
# The roles in this repository are reproducible; the files that aim them at a
# particular estate are not in version control at all, by design - they hold
# the inventory, the per-host variables and the vault. So the playbooks would
# survive the loss of this machine and the configuration that drives them
# would not. "Not in the public mirror" and "not backed up" are different
# properties, and without this script they were the same one.
#
# The archive is encrypted with the same Ansible Vault password the repository
# already uses, because a copy of an estate's topology on a public host is
# worse than no copy. Note what that implies: the backup is recoverable only
# while that password survives somewhere other than this machine. The password
# file itself is NOT included - including it would make the encryption
# decorative.
set -euo pipefail

usage() {
  cat >&2 <<USAGE
usage: $0 <ssh-destination> [remote-directory]

  ssh-destination   anything ssh accepts, e.g. a Host alias
  remote-directory  default: backups/site-config (relative to the remote home)

Run from the root of the checkout.
USAGE
  exit 2
}

dest="${1:-}"
[ -n "$dest" ] || usage
remote_dir="${2:-backups/site-config}"

# Everything git ignores that is configuration rather than cache. Listed
# explicitly rather than derived from .gitignore, so adding a cache directory
# to that file never silently adds it to the backup - and so a new
# configuration path has to be considered here deliberately.
paths=(inventory.yml host_vars group_vars/all)
[ -e local_sources.yml ] && paths+=(local_sources.yml)

for p in "${paths[@]}"; do
  [ -e "$p" ] || { echo "missing: $p - run from the checkout root" >&2; exit 1; }
done

command -v ansible-vault > /dev/null 2>&1 ||
  { echo "ansible-vault not on PATH; activate the venv" >&2; exit 1; }

umask 077
work="$(mktemp -d)"
# Shred rather than delete: the intermediate archive is the plaintext of
# everything this is trying to protect.
cleanup() { find "$work" -type f -exec shred -u {} + 2>/dev/null || true; rm -rf "$work"; }
trap cleanup EXIT

name="site-config-$(date +%Y%m%d-%H%M).tar.gz.vault"
tar czf "$work/plain.tar.gz" "${paths[@]}"
cp "$work/plain.tar.gz" "$work/$name"
ansible-vault encrypt "$work/$name" > /dev/null

# Prove the archive round-trips before shipping it. An encrypted backup that
# cannot be decrypted is indistinguishable from a good one until the day it
# matters.
cp "$work/$name" "$work/verify.tar.gz"
ansible-vault decrypt "$work/verify.tar.gz" > /dev/null
want="$(tar tzf "$work/plain.tar.gz" | wc -l)"
got="$(tar tzf "$work/verify.tar.gz" | wc -l)"
[ "$want" = "$got" ] ||
  { echo "round-trip mismatch: $want entries in, $got out" >&2; exit 1; }
echo "verified: $got entries survive encrypt and decrypt"

# shellcheck disable=SC2029  # $remote_dir must expand here and travel.
ssh "$dest" "mkdir -p ~/'$remote_dir' && chmod 700 ~/'$remote_dir'"
scp -q "$work/$name" "$dest:$remote_dir/"
# shellcheck disable=SC2029  # as above: expanded locally on purpose.
ssh "$dest" "chmod 600 ~/'$remote_dir/$name'"

# Compare checksums rather than trusting that scp reported success.
local_sum="$(sha256sum "$work/$name" | awk '{print $1}')"
# shellcheck disable=SC2029  # as above: expanded locally on purpose.
remote_sum="$(ssh "$dest" "sha256sum ~/'$remote_dir/$name'" | awk '{print $1}')"
if [ "$local_sum" != "$remote_sum" ]; then
  echo "checksum mismatch after copy; the remote file is not the one built" >&2
  exit 1
fi
echo "stored: $dest:$remote_dir/$name"
echo "sha256: $local_sum"
