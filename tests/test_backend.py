from __future__ import annotations

import hashlib
import io
import json
import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest

from ccusage_viz import backend, backend_install, backend_store
from ccusage_viz.backend_store import BackendChoice, load_choice, resolve_executable, save_choice
from ccusage_viz.cli import main
from ccusage_viz.errors import QueryError
from ccusage_viz.i18n import load_translator


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(backend_store, "ccuv_state_root", lambda: tmp_path)
    monkeypatch.setattr(backend_install, "ccuv_state_root", lambda: tmp_path)
    monkeypatch.setattr(backend_store.shutil, "which", lambda name: None)
    monkeypatch.setattr(backend, "interactive", lambda: False)


def test_store_atomic_and_private(tmp_path):
    choice = BackendChoice("official", "ccusage")
    save_choice(choice)
    assert load_choice() == choice
    assert not list(tmp_path.glob(".backend-*"))
    if backend_store.os.name != "nt":
        assert (tmp_path / "backend.json").stat().st_mode & 0o077 == 0


@pytest.mark.parametrize(
    "data",
    [
        "{",
        '{"schema":"future"}',
        "[]",
        '{"schema":"ccuv.backend/v1","backend":"enhanced","executable":"relative"}',
    ],
)
def test_corrupt_is_protected(tmp_path, data):
    path = tmp_path / "backend.json"
    path.write_text(data)
    with pytest.raises(QueryError):
        save_choice(BackendChoice("official", "ccusage"))
    assert path.read_text() == data


def test_resolution_precedence(monkeypatch):
    save_choice(BackendChoice("enhanced", "/tools/my-ccusage"))
    monkeypatch.setattr(backend_store.shutil, "which", lambda name: name)
    assert resolve_executable() == "/tools/my-ccusage"
    assert resolve_executable(explicit=True) == "ccusage"
    assert resolve_executable("/custom/bin") == "/custom/bin"


def test_discovery_noninteractive_prefers_official(monkeypatch):
    monkeypatch.setattr(backend_store.shutil, "which", lambda name: f"/bin/{name}")
    assert resolve_executable() == "ccusage"


@pytest.mark.parametrize("argv", [["backend"], ["backend", "--lang", "zh"]])
def test_status_absent_read_only(tmp_path, capsys, argv):
    assert main(argv) == 0
    assert "ccuv backend setup" in capsys.readouterr().out
    assert not (tmp_path / "backend.json").exists()


def test_status_unavailable_no_install(monkeypatch, capsys):
    save_choice(BackendChoice("official", "ccusage"))
    monkeypatch.setattr(
        backend,
        "validate",
        lambda choice: (_ for _ in ()).throw(QueryError("error.backend", detail="missing")),
    )
    assert main(["backend", "--lang", "en"]) == 0
    assert "unavailable" in capsys.readouterr().out


@pytest.mark.parametrize(
    "argv",
    [
        ["backend", "setup"],
        ["backend", "setup", "--yes"],
        ["backend", "setup", "--backend", "official"],
    ],
)
def test_noninteractive_requires_authorization(argv, tmp_path):
    assert main(argv) == 2
    assert not (tmp_path / "backend.json").exists()


@pytest.mark.parametrize("language", ["en", "zh"])
def test_nested_help_side_effect_free(language, tmp_path, capsys):
    with pytest.raises(SystemExit) as caught:
        main(["backend", "setup", "--help", "--lang", language])
    assert caught.value.code == 0
    assert "--backend" in capsys.readouterr().out
    assert not (tmp_path / "backend.json").exists()


@pytest.mark.parametrize("selected", ["official", "enhanced"])
def test_agent_setup_installs_and_saves(monkeypatch, selected):
    choice = BackendChoice(selected, "ccusage" if selected == "official" else "/managed/my-ccusage")
    monkeypatch.setattr(backend, f"install_{selected}", lambda: choice)
    monkeypatch.setattr(backend, "validate", lambda choice: "20.0")
    assert main(["backend", "setup", "--backend", selected, "--yes"]) == 0
    assert load_choice() == choice


@pytest.mark.parametrize(
    "answer,expected",
    [
        ("y", "enhanced"),
        ("n", "official"),
        ("?", "official"),
        ("", "official"),
        ("需要", "enhanced"),
    ],
)
def test_interactive_sources(monkeypatch, answer, expected):
    monkeypatch.setattr("builtins.input", lambda prompt: answer)
    assert backend.select(load_translator("en"), None) == expected


def test_unsure_preserves_saved(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt: "?")
    assert (
        backend.select(load_translator("zh"), BackendChoice("enhanced", "/tools/my-ccusage"))
        == "enhanced"
    )


@pytest.mark.parametrize("language", ["en", "zh"])
@pytest.mark.parametrize("saved_backend", [None, "enhanced"])
def test_prompt_uses_tool_names_and_explains_default(monkeypatch, language, saved_backend):
    prompts = []

    def answer(prompt):
        prompts.append(prompt)
        return "?"

    monkeypatch.setattr("builtins.input", answer)
    saved = BackendChoice("enhanced", "/tools/my-ccusage") if saved_backend else None
    assert backend.select(load_translator(language), saved) == (saved_backend or "official")
    assert "enhanced" not in prompts[0]
    assert ("my-ccusage" if saved else "ccusage") in prompts[0]
    expected = (
        ("保留当前" if language == "zh" else "keep your current")
        if saved
        else ("使用官方" if language == "zh" else "use official")
    )
    assert expected in prompts[0]


def test_invalid_answer_reprompts(monkeypatch):
    answers = iter(["invalid", "y"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    assert backend.select(load_translator("en"), None) == "enhanced"


@pytest.mark.parametrize("cancel", [EOFError, KeyboardInterrupt])
def test_cancel_preserves(monkeypatch, cancel):
    choice = BackendChoice("official", "ccusage")
    save_choice(choice)
    monkeypatch.setattr(backend, "interactive", lambda: True)

    def cancelled(prompt):
        raise cancel

    monkeypatch.setattr("builtins.input", cancelled)
    with pytest.raises(QueryError, match="error.backend_cancelled"):
        backend.setup(load_translator("en"))
    assert load_choice() == choice


def test_decline_preserves(monkeypatch):
    save_choice(BackendChoice("official", "ccusage"))
    monkeypatch.setattr(backend, "interactive", lambda: True)
    answers = iter(["y", "n"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    with pytest.raises(QueryError, match="error.backend_cancelled"):
        backend.setup(load_translator("en"))
    assert load_choice().backend == "official"


def test_failure_preserves(monkeypatch):
    choice = BackendChoice("official", "ccusage")
    save_choice(choice)

    def failure():
        raise QueryError("error.backend", detail="download failed")

    monkeypatch.setattr(backend, "install_enhanced", failure)
    with pytest.raises(QueryError):
        backend.setup(load_translator("en"), "enhanced", yes=True)
    assert load_choice() == choice


def archive(name="my-ccusage-linux-x64/my-ccusage", *, link=False):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as bundle:
        member = tarfile.TarInfo(name)
        if link:
            member.type = tarfile.SYMTYPE
            member.linkname = "/etc/passwd"
            bundle.addfile(member)
        else:
            member.size = 6
            bundle.addfile(member, io.BytesIO(b"binary"))
    return output.getvalue()


def test_extract_archive():
    assert (
        backend_install.extract_executable(archive(), "linux.tar.gz", "my-ccusage-linux-x64")
        == b"binary"
    )


@pytest.mark.parametrize(
    "name,link",
    [
        ("../outside", False),
        ("/absolute", False),
        ("my-ccusage-linux-x64/my-ccusage", True),
        ("wrong", False),
    ],
)
def test_unsafe_archive_rejected(name, link):
    with pytest.raises(QueryError):
        backend_install.extract_executable(
            archive(name, link=link), "linux.tar.gz", "my-ccusage-linux-x64"
        )


def test_windows_zip():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as bundle:
        bundle.writestr("my-ccusage-windows-x64/my-ccusage.exe", b"binary")
    assert (
        backend_install.extract_executable(
            output.getvalue(), "windows.zip", "my-ccusage-windows-x64"
        )
        == b"binary"
    )


@pytest.mark.parametrize(
    "system,machine,expected",
    [
        ("Darwin", "arm64", "macos-arm64.tar.gz"),
        ("Linux", "x86_64", "linux-x64.tar.gz"),
        ("Windows", "AMD64", "windows-x64.zip"),
    ],
)
def test_platform_assets(monkeypatch, system, machine, expected):
    monkeypatch.setattr(backend_install.platform, "system", lambda: system)
    monkeypatch.setattr(backend_install.platform, "machine", lambda: machine)
    assert backend_install.release_asset()[1].endswith(expected)


def test_unsupported_platform(monkeypatch):
    monkeypatch.setattr(backend_install.platform, "system", lambda: "Windows")
    monkeypatch.setattr(backend_install.platform, "machine", lambda: "arm64")
    with pytest.raises(QueryError):
        backend_install.release_asset()


@pytest.mark.parametrize("corrupt", [False, True])
def test_release_install_fixed_tag_and_checksum(monkeypatch, tmp_path, corrupt):
    data = archive()
    stem, asset = "my-ccusage-linux-x64", "my-ccusage-linux-x64.tar.gz"
    monkeypatch.setattr(backend_install, "release_asset", lambda: (stem, asset))
    urls = []

    def download(url, limit):
        urls.append(url)
        if url.endswith("/latest"):
            return json.dumps({"tag_name": "v20.0.34-my.2"}).encode()
        if url.endswith("SHA256SUMS"):
            return (
                f"{('0' * 64) if corrupt else hashlib.sha256(data).hexdigest()}  {asset}\n".encode()
            )
        return data

    monkeypatch.setattr(backend_install, "download", download)
    monkeypatch.setattr(backend_install, "validate", lambda choice: "20.0")
    if corrupt:
        with pytest.raises(QueryError):
            backend_install.install_enhanced()
        assert not (tmp_path / "tools").exists()
    else:
        choice = backend_install.install_enhanced()
        assert Path(choice.executable).read_bytes() == b"binary"
        assert not list((tmp_path / "tools" / "my-ccusage").glob(".stage-*"))
    assert all("/v20.0.34-my.2/" in url for url in urls[1:])


def test_probe_timeout(monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 15)

    monkeypatch.setattr(backend_install.subprocess, "run", timeout)
    with pytest.raises(QueryError):
        backend_install.probe("ccusage")


def test_npm_missing():
    with pytest.raises(QueryError, match="error.npm_missing"):
        backend_install.install_official()


@pytest.mark.parametrize(
    "code,available,key",
    [
        (7, False, "error.ccusage_install_failed"),
        (0, False, "error.ccusage_install_path"),
        (0, True, None),
    ],
)
def test_npm_result(monkeypatch, code, available, key):
    monkeypatch.setattr(
        backend_install.shutil,
        "which",
        lambda name: "/bin/npm" if name == "npm" else ("/bin/ccusage" if available else None),
    )
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, code)

    monkeypatch.setattr(backend_install.subprocess, "run", run)
    if key:
        with pytest.raises(QueryError, match=key):
            backend_install.install_official()
    else:
        assert backend_install.install_official().backend == "official"
    assert calls[0][0] == ["/bin/npm", "install", "-g", "ccusage"]
    assert calls[0][1]["shell"] is False


def test_builtin_acquisition_and_explicit_dashboard_override(monkeypatch):
    from ccusage_viz.acquisition import historical_query_intent
    from ccusage_viz.bootstrap import build_provider_registry
    from ccusage_viz.cli.configuration import _to_options
    from ccusage_viz.command_parsing.parser import build_parser
    from ccusage_viz.configuration import standalone_from_chart_pane
    from ccusage_viz.query.models import QueryTrigger

    save_choice(BackendChoice("enhanced", "/managed/my-ccusage"))
    monkeypatch.setattr(backend_store.shutil, "which", lambda name: name)
    parser = build_parser(load_translator("en"))
    definition = build_provider_registry().get("ccusage")
    for explicit in (frozenset(), frozenset({"ccusage_bin"})):
        launch = _to_options(
            parser.parse_args(["dashboard", "--pane", "timeline"]), explicit=explicit
        )
        pane = standalone_from_chart_pane(launch, launch.panes[0])
        intent = historical_query_intent(
            pane, definition, owner_id="pane", generation=0, trigger=QueryTrigger.STARTUP
        )
        assert intent.execution_context.executable == (
            "ccusage" if explicit else "/managed/my-ccusage"
        )
        assert launch.process.ccusage_bin == "ccusage"


def test_existing_backend_reused(monkeypatch):
    monkeypatch.setattr(
        backend_store.shutil,
        "which",
        lambda name: "/bin/my-ccusage" if name in {"my-ccusage", "/bin/my-ccusage"} else None,
    )
    monkeypatch.setattr(backend, "validate", lambda choice: "20.0")
    monkeypatch.setattr(backend, "install_enhanced", lambda: pytest.fail("must reuse"))
    backend.setup(load_translator("en"), "enhanced", yes=True)
    assert load_choice() == BackendChoice("enhanced", "/bin/my-ccusage")


def test_managed_failed_validation_preserves_old_binary(monkeypatch, tmp_path):
    old = tmp_path / "tools" / "my-ccusage" / "old" / "my-ccusage"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"old")
    save_choice(BackendChoice("enhanced", str(old)))
    data = archive()
    asset = "my-ccusage-linux-x64.tar.gz"
    monkeypatch.setattr(backend_install, "release_asset", lambda: ("my-ccusage-linux-x64", asset))

    def download(url, limit):
        if url.endswith("/latest"):
            return b'{"tag_name":"v1"}'
        if url.endswith("SHA256SUMS"):
            return f"{hashlib.sha256(data).hexdigest()}  {asset}\n".encode()
        return data

    monkeypatch.setattr(backend_install, "download", download)

    def fail(choice):
        raise QueryError("error.backend", detail="invalid executable")

    monkeypatch.setattr(backend_install, "validate", fail)
    with pytest.raises(QueryError):
        backend_install.install_enhanced()
    assert old.read_bytes() == b"old"
    assert load_choice().executable == str(old)
    assert not list(old.parent.parent.glob(".stage-*"))


def test_download_size_and_network_errors(monkeypatch):
    class Response(io.BytesIO):
        def geturl(self):
            return "https://example.com/asset"

    monkeypatch.setattr(
        backend_install.urllib.request, "urlopen", lambda *args, **kwargs: Response(b"oversize")
    )
    with pytest.raises(QueryError):
        backend_install.download("https://example.com/asset", 2)

    def fail(*args, **kwargs):
        raise OSError("network unavailable")

    monkeypatch.setattr(backend_install.urllib.request, "urlopen", fail)
    with pytest.raises(QueryError):
        backend_install.download("https://example.com/asset", 100)
