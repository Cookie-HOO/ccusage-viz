"""Authorized backend installers. Remote scripts are never executed."""

from __future__ import annotations

import hashlib
import io
import json
import os
import platform
import shutil
import subprocess
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

from ccusage_viz.backend_store import BackendChoice, ccuv_state_root
from ccusage_viz.errors import QueryError

REPOSITORY = "Cookie-HOO/my-ccusage"
ARCHIVE_LIMIT = 128 * 1024 * 1024
BINARY_LIMIT = 256 * 1024 * 1024


def probe(executable: str, arguments: tuple[str, ...] = ("--version",)) -> str:
    # Use temporary files to bound captured output without pipe deadlocks.
    try:
        with tempfile.TemporaryFile() as output:
            result = subprocess.run(
                [executable, *arguments],
                stdout=output,
                stderr=output,
                timeout=15,
                check=False,
                shell=False,
            )
            output.seek(0)
            text = output.read(8192).decode("utf-8", errors="replace").strip()
        if result.returncode != 0:
            raise QueryError("error.backend", detail=f"{executable}: {text or result.returncode}")
        return text
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise QueryError("error.backend", detail=f"{executable}: {exc}") from exc


def validate(choice: BackendChoice) -> str:
    version = probe(choice.executable)
    if choice.backend == "enhanced":
        probe(choice.executable, ("dsh", "--help"))
        probe(choice.executable, ("workbuddy", "--help"))
    return version


def download(url: str, limit: int) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "ccusage-viz"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            if not response.geturl().startswith("https://"):
                raise ValueError("insecure download redirect")
            data = response.read(limit + 1)
        if len(data) > limit:
            raise ValueError("download exceeds size limit")
        return data
    except (OSError, ValueError, urllib.error.URLError) as exc:
        raise QueryError("error.backend", detail=f"{url}: {exc}") from exc


def release_asset() -> tuple[str, str]:
    system = platform.system()
    machine = platform.machine().lower()
    os_name = {"Darwin": "macos", "Linux": "linux", "Windows": "windows"}.get(system)
    arch = {"x86_64": "x64", "amd64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(machine)
    if os_name is None or arch is None or (os_name == "windows" and arch != "x64"):
        raise QueryError(
            "error.backend",
            detail=f"Unsupported platform {system}/{machine}; see https://github.com/{REPOSITORY}/releases",
        )
    stem = f"my-ccusage-{os_name}-{arch}"
    return stem, stem + (".zip" if os_name == "windows" else ".tar.gz")


def extract_executable(archive: bytes, asset: str, stem: str) -> bytes:
    """Read only the expected regular executable; never extract archive paths."""
    filename = "my-ccusage.exe" if asset.endswith(".zip") else "my-ccusage"
    expected = f"{stem}/{filename}"

    def safe(name: str) -> None:
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name:
            raise ValueError("unsafe archive path")

    try:
        if asset.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
                for entry in bundle.infolist():
                    safe(entry.filename)
                    mode = entry.external_attr >> 16
                    if mode & 0o170000 == 0o120000:
                        raise ValueError("archive links are not allowed")
                matches = [entry for entry in bundle.infolist() if entry.filename == expected]
                if len(matches) != 1 or matches[0].is_dir() or matches[0].file_size > BINARY_LIMIT:
                    raise ValueError("unexpected executable layout or size")
                with bundle.open(matches[0]) as stream:
                    binary = stream.read(BINARY_LIMIT + 1)
        else:
            with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as bundle:
                entries = bundle.getmembers()
                for entry in entries:
                    safe(entry.name)
                    if not (entry.isfile() or entry.isdir()):
                        raise ValueError("archive links/special files are not allowed")
                matches = [entry for entry in entries if entry.name == expected]
                if len(matches) != 1 or not matches[0].isfile() or matches[0].size > BINARY_LIMIT:
                    raise ValueError("unexpected executable layout or size")
                stream = bundle.extractfile(matches[0])
                if stream is None:
                    raise ValueError("missing executable")
                with stream:
                    binary = stream.read(BINARY_LIMIT + 1)
        if not binary or len(binary) > BINARY_LIMIT:
            raise ValueError("invalid executable size")
        return binary
    except (OSError, ValueError, tarfile.TarError, zipfile.BadZipFile, EOFError) as exc:
        raise QueryError("error.backend", detail=f"Invalid release archive: {exc}") from exc


def install_enhanced() -> BackendChoice:
    stem, asset = release_asset()
    try:
        metadata = json.loads(
            download(f"https://api.github.com/repos/{REPOSITORY}/releases/latest", 1024 * 1024)
        )
        tag = metadata["tag_name"]
        if not isinstance(tag, str) or not tag:
            raise ValueError("missing release tag")
        base = (
            f"https://github.com/{REPOSITORY}/releases/download/{urllib.parse.quote(tag, safe='')}"
        )
        archive = download(f"{base}/{asset}", ARCHIVE_LIMIT)
        sums = download(f"{base}/SHA256SUMS", 1024 * 1024).decode("utf-8")
        hashes = [
            line.split()[0]
            for line in sums.splitlines()
            if len(line.split()) == 2 and line.split()[1].lstrip("*") == asset
        ]
        if len(hashes) != 1 or hashlib.sha256(archive).hexdigest() != hashes[0].lower():
            raise ValueError("release SHA-256 checksum mismatch")
        binary = extract_executable(archive, asset, stem)
        # Versioned destinations preserve the previously selected executable on failure.
        root = ccuv_state_root() / "tools" / "my-ccusage"
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.TemporaryDirectory(prefix=".stage-", dir=root) as staging:
            staged = Path(staging) / ("my-ccusage.exe" if asset.endswith(".zip") else "my-ccusage")
            staged.write_bytes(binary)
            staged.chmod(0o700)
            validate(BackendChoice("enhanced", str(staged)))
            destination = root / hashlib.sha256(binary).hexdigest()
            destination.mkdir(exist_ok=True, mode=0o700)
            target = destination / staged.name
            # Replace atomically even when a prior copy at this digest was damaged.
            os.replace(staged, target)
            choice = BackendChoice("enhanced", str(target))
            validate(choice)
            return choice
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise QueryError("error.backend", detail=str(exc)) from exc


def install_official() -> BackendChoice:
    npm = shutil.which("npm")
    if npm is None:
        raise QueryError("error.npm_missing")
    try:
        completed = subprocess.run(
            [npm, "install", "-g", "ccusage"], shell=False, check=False, timeout=300
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise QueryError("error.ccusage_install_start", detail=str(exc)) from exc
    if completed.returncode:
        raise QueryError("error.ccusage_install_failed", code=completed.returncode)
    if shutil.which("ccusage") is None:
        raise QueryError("error.ccusage_install_path")
    return BackendChoice("official", "ccusage")
