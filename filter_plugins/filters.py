"""Add some useful filters for ansible."""

from __future__ import annotations

import base64
import json
from shutil import which
from subprocess import PIPE, run
from typing import TYPE_CHECKING
from urllib.request import urlopen

if TYPE_CHECKING:
    from collections.abc import Callable


class FilterModule:
    """Ansible filter module class."""

    @staticmethod
    def fetch_and_convert(url: str) -> str:
        """Fetch a signing key from a url and return a .sources fragment.

        Publicly available signing keys may be armored or unarmored. We fetch
        the key, convert it to armored if needed, ensure that it starts and ends
        with the desired identifer string, then indent it by one space for use
        in a .sources file.

        Args:
            url: A fully-qualified url from which a key may be downloaded.

        Returns:
            A properly-formatted "Signed-By:" snippet that may be inserted
            directly into a /etc/apt/sources.list.d/*.sources file.


        """
        # Fetch the contents of the `url` as a string.
        with urlopen(url) as response:
            key = response.read()
        # Pass it through `gpg --dearmor` in case it is already armored,
        # then through `gpg --armor` to re-armor it.
        gpg = which("gpg")
        # Use sed to convert the output for use with a .sources file.
        sed = which("sed")
        return "Signed-By:\n" + run(
            f"{gpg} --dearmor | {gpg} --enarmor | {sed} -e '"
            "/^Comment:/d;/^Version/d;"
            "s/ARMORED FILE/PUBLIC KEY BLOCK/;s/^$/./;s/^/ /'",
            check=True, input=key, shell=True, stdout=PIPE,
            text=False,
        ).stdout.decode("utf-8")

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
        # Construct the releases url from the `project` string.
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
                }, separators=(",", ":")
            ).encode("utf-8")
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
        """Return a hash of filter names and implementing functions."""
        return {
            "latest_github_release": self.latest_github_release,
            "rustdesk_config": self.rustdesk_config,
            "rustdesk_debs_client": self.rustdesk_debs_client,
            "rustdesk_debs_server": self.rustdesk_debs_server,
            "signed_by": self.fetch_and_convert,
        }
