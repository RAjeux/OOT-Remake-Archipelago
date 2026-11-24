"""Discover releases and stage authenticated application updates.

The release repository is fixed. Automatic replacement requires an explicitly
provisioned Ed25519 public key and a signed SHA256SUMS.txt; existing unsigned
releases remain available through their ordinary download page. No game data,
room profile, save or downloaded builder is part of an application update.

The signed-checksum scheme follows Mozencaz/OotrR's MIT-licensed updater. The
single-file release format, bounded downloads and transactional replacement are
adapted for this application's Windows distribution.
"""
from dataclasses import dataclass
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import ssl
import tempfile
import urllib.error
import urllib.parse
import urllib.request


REPOSITORY = "RAjeux/OOT-Remake-Archipelago"
API = "https://api.github.com/repos/" + REPOSITORY + "/releases"
DOWNLOADS = "https://github.com/" + REPOSITORY + "/releases/download/"
PAGES = "https://github.com/" + REPOSITORY + "/releases/tag/"
CHECKSUMS = "SHA256SUMS.txt"
SIGNATURE = CHECKSUMS + ".sig"
MAX_METADATA = 4 << 20
MAX_APPLICATION = 256 << 20
USER_AGENT = "OOT-Remake-Archipelago-updater"
# The matching private key stays outside the source tree, protected by DPAPI.
# Never trust a replacement key fetched from the release being authenticated.
from .update_key import PUBLIC_KEY_HEX
TRUSTED_PUBLIC_KEY = bytes.fromhex(PUBLIC_KEY_HEX)


class UpdateError(RuntimeError):
    """A release could not be checked or authenticated."""


@dataclass(frozen=True)
class Release:
    version: str
    page: str
    notes: str
    asset_name: str
    asset_url: str
    checksum_url: str | None = None
    signature_url: str | None = None

    @property
    def signed(self):
        """Whether signed metadata is offered, not whether it is trusted."""
        return bool(self.checksum_url and self.signature_url)


@dataclass(frozen=True)
class PreparedUpdate:
    release: Release
    path: Path
    sha256: str


def version_key(value):
    """Compare semantic versions, including numeric prerelease identifiers."""
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?", str(value))
    if not match:
        raise UpdateError("Invalid release version.")
    major, minor, patch, prerelease = match.groups()
    identifiers = tuple((0, int(part)) if part.isdecimal() else (1, part)
                        for part in (prerelease or "").split(".") if part)
    return int(major), int(minor), int(patch), prerelease is None, identifiers


def _asset_url(tag, name):
    if not isinstance(name, str) or Path(name).name != name or "/" in name or "\\" in name:
        raise UpdateError("Invalid release asset name.")
    return DOWNLOADS + urllib.parse.quote(tag, safe="") + "/" + urllib.parse.quote(name, safe="")


class _Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, url):
        parsed = urllib.parse.urlsplit(url)
        if (parsed.scheme != "https" or parsed.username or parsed.password
                or parsed.hostname not in {"github.com", "release-assets.githubusercontent.com",
                                           "objects.githubusercontent.com"}):
            raise UpdateError("The download redirected outside GitHub's release servers.")
        return super().redirect_request(request, response, code, message, headers, url)


def _download(url, limit):
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != "https" or parsed.username or parsed.password
            or parsed.hostname not in {"api.github.com", "github.com"}):
        raise UpdateError("Invalid release download address.")
    opener = urllib.request.build_opener(_Redirects(),
                                        urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                  "Accept": "application/vnd.github+json"})
    try:
        with opener.open(request, timeout=30) as response:
            length = response.headers.get("Content-Length")
            if length is not None and (not length.isdecimal() or int(length) > limit):
                raise UpdateError("The release download is too large.")
            result = response.read(limit + 1)
    except (OSError, urllib.error.URLError) as error:
        raise UpdateError("The release server could not be reached.") from error
    if len(result) > limit:
        raise UpdateError("The release download is too large.")
    return result


def check_for_update(current_version, include_prereleases=False, *, platform=None, fetch=None):
    """Return a newer compatible Release, or None; never install anything."""
    import sys
    platform = platform or sys.platform
    current = version_key(current_version)
    fetch = fetch or _download
    raw = fetch(API + "?per_page=30", MAX_METADATA)
    try:
        entries = json.loads(raw)
    except (UnicodeError, ValueError) as error:
        raise UpdateError("The release server returned invalid metadata.") from error
    if not isinstance(entries, list):
        raise UpdateError("The release server returned invalid metadata.")
    candidates = []
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("draft") or (entry.get("prerelease") and not include_prereleases):
            continue
        tag = entry.get("tag_name", "")
        try:
            key = version_key(tag)
        except UpdateError:
            continue
        if key <= current or (not key[3] and not include_prereleases):
            continue
        version = tag.removeprefix("v")
        expected = (f"OOT-Remake-Archipelago-{version}.exe" if platform.startswith("win")
                    else f"OOT-Remake-Archipelago-{version}-linux-x64.tar.gz" if platform.startswith("linux")
                    else None)
        assets = entry.get("assets", [])
        if not expected or not isinstance(assets, list):
            continue
        names = {a.get("name"): a for a in assets if isinstance(a, dict)}
        if expected not in names:
            continue
        for name in (expected, CHECKSUMS, SIGNATURE):
            if name in names and names[name].get("browser_download_url") != _asset_url(tag, name):
                raise UpdateError("The release contains an unexpected download address.")
        candidates.append((key, Release(version, PAGES + urllib.parse.quote(tag, safe=""),
                                        str(entry.get("body") or ""), expected, _asset_url(tag, expected),
                                        _asset_url(tag, CHECKSUMS) if CHECKSUMS in names else None,
                                        _asset_url(tag, SIGNATURE) if SIGNATURE in names else None)))
    return max(candidates, key=lambda pair: pair[0])[1] if candidates else None


def _signature(raw):
    if len(raw) == 64:
        return raw
    try:
        result = bytes.fromhex(raw.decode("ascii").strip())
    except (UnicodeError, ValueError) as error:
        raise UpdateError("The release signature has an invalid format.") from error
    if len(result) != 64:
        raise UpdateError("The release signature has an invalid format.")
    return result


def _checksum(raw, asset_name):
    try:
        text = raw.decode("utf-8")
    except UnicodeError as error:
        raise UpdateError("The checksum list is invalid.") from error
    hashes = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r"([0-9A-Fa-f]{64}) [ *](.+)", line)
        if not match:
            raise UpdateError("The checksum list is invalid.")
        digest, name = match.groups()
        if name in hashes or Path(name).name != name or "/" in name or "\\" in name:
            raise UpdateError("The checksum list contains an invalid or duplicate file.")
        hashes[name] = digest.lower()
    if asset_name not in hashes:
        raise UpdateError("The application is missing from the signed checksum list.")
    return hashes[asset_name]


def prepare_update(release, destination, *, public_key=None, fetch=None, verifier=None):
    """Authenticate metadata, verify bytes, then atomically stage an update."""
    public_key = TRUSTED_PUBLIC_KEY if public_key is None else public_key
    if not isinstance(public_key, bytes) or len(public_key) != 32:
        raise UpdateError("Automatic updates are not enabled: no trusted publisher key is configured. Use the release page.")
    if not release.signed:
        raise UpdateError("This release has no signed checksums. Use the release page.")
    tag = "v" + release.version
    version_key(release.version)
    for name, url in ((release.asset_name, release.asset_url), (CHECKSUMS, release.checksum_url),
                      (SIGNATURE, release.signature_url)):
        if url != _asset_url(tag, name):
            raise UpdateError("The update does not belong to this application's release repository.")
    fetch = fetch or _download
    checksums = fetch(release.checksum_url, MAX_METADATA)
    signature = _signature(fetch(release.signature_url, 1024))
    if verifier is None:
        from ootrr_full.ed25519 import verify
        verifier = verify
    if not verifier(public_key, checksums, signature):
        raise UpdateError("The release signature could not be verified.")
    expected = _checksum(checksums, release.asset_name)
    content = fetch(release.asset_url, MAX_APPLICATION)
    actual = hashlib.sha256(content).hexdigest()
    if not hmac.compare_digest(actual, expected):
        raise UpdateError("The downloaded application does not match the signed checksum.")
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / release.asset_name
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination, prefix=".verified-update-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return PreparedUpdate(release, target, actual)


def install_prepared(update, executable):
    """Replace only the application, preserving the previous executable on error.

    The caller must use a separately staged file. The returned backup remains
    available until the new application has successfully started; it is never
    deleted here. No executable is started by this function.
    """
    executable = Path(executable)
    source = Path(update.path)
    if executable.suffix.lower() != ".exe" or source.suffix.lower() != ".exe":
        raise UpdateError("In-place updates currently support the Windows application only.")
    if source.resolve() == executable.resolve() or not executable.is_file():
        raise UpdateError("Choose a separately staged update and an existing application.")
    if hashlib.sha256(source.read_bytes()).hexdigest() != update.sha256:
        raise UpdateError("The staged update changed after verification.")
    backup = executable.with_name(executable.name + ".previous")
    number = 1
    while backup.exists():
        number += 1
        backup = executable.with_name(executable.name + f".previous-{number}")
    replacement = executable.with_name(executable.name + ".updating")
    if replacement.exists():
        raise UpdateError("An incomplete application update needs recovery before continuing.")
    # Copy beside the destination first, so every rename is on one filesystem.
    import shutil
    try:
        with source.open("rb") as original, replacement.open("xb") as staged:
            shutil.copyfileobj(original, staged)
            staged.flush()
            os.fsync(staged.fileno())
        if hashlib.sha256(replacement.read_bytes()).hexdigest() != update.sha256:
            raise UpdateError("The copied application does not match the verified update.")
        os.replace(executable, backup)
        try:
            os.replace(replacement, executable)
        except BaseException:
            os.replace(backup, executable)
            raise
    finally:
        replacement.unlink(missing_ok=True)
    return backup
