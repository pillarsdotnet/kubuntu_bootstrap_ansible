# Copyright (c) 2026 Robert August Vincent II <pillarsdotnet@gmail.com>
"""Add some useful filters for ansible."""

from __future__ import annotations

import base64
import ipaddress
import json
from shutil import which

# The gpg re-armoring pipeline below is a deliberate subprocess use.
from subprocess import PIPE, run
from typing import TYPE_CHECKING
from urllib.request import urlopen

if TYPE_CHECKING:
    from collections.abc import Callable


class FilterModule:
    """Ansible filter module class."""

    @staticmethod
    def fetch_and_convert(urls: str | list[str]) -> str:
        """Fetch one or more signing keys and return a .sources fragment.

        Publicly available signing keys may be armored or unarmored. We fetch
        each key, convert it to armored if needed, ensure that it starts and
        ends with the desired identifier string, then indent it by one space
        for use in a .sources file.

        Several keys fold into a *single* armored block, because each one is
        dearmored on its own and the binary results are concatenated before
        the whole is re-armored. So a repo that spans a vendor's key rotation
        can name the outgoing and the incoming key together, and apt checks
        the index against whichever one signed it, ignoring the other.
        Measured against apt 3.3.3: one block carrying both Microsoft release
        signers verifies the prod repo, which has rotated, and the vscode
        repo, which has not, with no warning from either. Note that a key
        named here is one apt will *accept* for that repo, so list only keys
        of the vendor who owns it.

        Args:
            urls: A fully-qualified url from which a key may be downloaded,
                or a list of several such urls.

        Returns:
            A properly-formatted "Signed-By:" snippet that may be inserted
            directly into a /etc/apt/sources.list.d/*.sources file.


        """
        gpg = which("gpg")
        # Use sed to convert the output for use with a .sources file.
        sed = which("sed")
        # Dearmor each key separately and concatenate the binary results,
        # rather than concatenating what was fetched and dearmoring once. A
        # key may be served either armored or unarmored, and `gpg --dearmor`
        # copies an unarmored one through byte for byte - so any separator
        # inserted between two fetched keys would land inside a certificate
        # instead of between them. Dearmoring first means none is needed.
        #
        # The URLs come from the playbook's own vars, always https:// key
        # locations, not user input.
        url_list = [urls] if isinstance(urls, str) else urls
        key = b""
        for url in url_list:
            with urlopen(url) as response:  # noqa: S310
                # shell=True is deliberate here and below: every command is
                # fixed, built from which() results, with no untrusted text
                # interpolated.
                key += run(  # noqa: S602
                    f"{gpg} --dearmor",
                    check=True, input=response.read(), shell=True, stdout=PIPE,
                    text=False,
                ).stdout
        # Re-armor the collected keys as one block and reshape it for apt.
        return "Signed-By:\n" + run(  # noqa: S602
            f"{gpg} --enarmor | {sed} -e '"
            "/^Comment:/d;/^Version/d;"
            "s/ARMORED FILE/PUBLIC KEY BLOCK/;s/^$/./;s/^/ /'",
            check=True, input=key, shell=True, stdout=PIPE,
            text=False,
        ).stdout.decode("utf-8")

    @staticmethod
    def global_addresses(addresses: list[str]) -> list[str]:
        """Return the addresses that are routable on the public internet.

        Private ranges, loopback, link-local and the carrier-grade NAT range
        are all dropped, so a host behind NAT yields an empty list.

        Args:
            addresses: IP address strings, such as a host's
                `all_ipv4_addresses` fact.

        Returns:
            The members of `addresses` that are globally routable.

        """
        return [a for a in addresses if ipaddress.ip_address(a).is_global]

    @staticmethod
    def latest_github_release(project: str) -> str:
        """Use the github api to fetch the latest release for a given project.

        Fetch latest release info for a github project and parse the returned
        JSON for the release tag string.

        Args:
            project: A "username/projectname" string.

        Returns:
            The tag string (such as "1.2.3") corresponding to the latest
            release.

        """
        # Construct the releases url from the `project` string. The scheme is
        # fixed https and the project slug comes from the playbook's own vars.
        url = f"https://api.github.com/repos/{project}/releases/latest"
        with urlopen(url) as response:
            data = json.loads(response.read().decode("utf-8"))
        return data["tag_name"]

    @staticmethod
    def rustdesk_config(ipv4: str, pubkey: str) -> str:
        """Return a setup string that can be used to configure rustdesk clients.

        The setup string consists of a JSON object string, converted to Base64,
        and reversed.

        Args:
            ipv4: The external IPv4 address of the rustdesk server.
            pubkey: The public key used to sign rustdesk messages.

        Returns:
            An obfuscated setup string.

        """
        return base64.b64encode(
            json.dumps(
                {
                    "host": ipv4,
                    "relay": ipv4,
                    "key": pubkey,
                    "api": f"https://{ipv4}",
                }, separators=(",", ":"),
            ).encode("utf-8"),
        ).decode("ascii").replace("=", "")[::-1]

    @staticmethod
    def rustdesk_debs_client(release: str) -> list[str]:
        """Return the rustdesk client package url(s) for a given release.

        This list will contain a single url for the rustdesk client package.

        Args:
            release: The desired rustdesk release.

        Returns:
            A list containing a single url.

        """
        baseurl = "https://github.com/rustdesk/rustdesk"
        download = f"releases/download/{release}"
        return [f"{baseurl}/{download}/rustdesk-{release}-x86_64.deb"]

    @staticmethod
    def rustdesk_debs_server(release: str) -> list[str]:
        """Return the rustdesk server package url(s) for a given release.

        This list will contain the urls for the hbbr (id server) and
        hbbr (relay server) packages.

        Args:
            release: The desired rustdesk release.

        Returns:
            A list two urls.

        """
        baseurl = "https://github.com/rustdesk/rustdesk-server-pro"
        download = f"releases/download/{release}"
        prefix = f"{baseurl}/{download}/rustdesk-server-linux-amd64.tar.gz"
        suffix = f"_{release}_amd64.deb"
        return [f"{prefix}r{suffix}", f"{prefix}s{suffix}"]

    def filters(self) -> dict[str, Callable]:
        """Return a hash of filter names and implementing functions.

        Returns:
            A mapping from each filter's Jinja name to the static method
            that implements it.

        """
        return {
            "global_addresses": self.global_addresses,
            "latest_github_release": self.latest_github_release,
            "rustdesk_config": self.rustdesk_config,
            "rustdesk_debs_client": self.rustdesk_debs_client,
            "rustdesk_debs_server": self.rustdesk_debs_server,
            "signed_by": self.fetch_and_convert,
        }
