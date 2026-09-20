"""Security regression tests.

Each test corresponds to a finding from the pre-release security review. They
assert the fix holds, so a future refactor cannot quietly reintroduce the hole.
"""
import importlib
import os
import sys
from pathlib import Path

import pytest

import app


# --------------------------------------------------------------------------
# Upload filename -> arbitrary file write
# --------------------------------------------------------------------------
@pytest.mark.parametrize("hostile", [
    "../../../../etc/passwd",
    "/etc/passwd",
    "/tmp/owned.nc",
    "..\\..\\windows\\system32\\drivers\\etc\\hosts",
    "....//....//escape.nc",
    "../",
    "..",
    "",
    None,
])
def test_upload_names_cannot_escape_their_directory(hostile):
    """`os.path.join(tmp, name)` discards tmp for an absolute name and honours '..'."""
    safe = app.safe_upload_name(hostile)
    assert safe, "a name must always be produced"
    assert os.path.basename(safe) == safe, f"{safe!r} still contains a path separator"
    assert "/" not in safe and "\\" not in safe
    assert not safe.startswith(".."), f"{safe!r} can still traverse upwards"
    assert not os.path.isabs(safe)
    joined = os.path.join("/var/tmp/verif", safe)
    assert os.path.realpath(joined).startswith("/var/tmp/verif" + os.sep) or \
           os.path.realpath(joined).startswith(os.path.realpath("/var/tmp/verif") + os.sep)


def test_upload_name_keeps_a_normal_filename_usable():
    assert app.safe_upload_name("day01fcst_2025-06-19.nc") == "day01fcst_2025-06-19.nc"


def test_upload_name_is_length_bounded():
    assert len(app.safe_upload_name("a" * 5000 + ".nc")) <= 128


def test_upload_name_strips_shell_and_control_characters():
    out = app.safe_upload_name("a;rm -rf ~`$(id)`.nc")
    assert all(c.isalnum() or c in "._- " for c in out)


# --------------------------------------------------------------------------
# VERIF_ROOT confinement -> arbitrary file read
# --------------------------------------------------------------------------
def test_paths_are_unrestricted_when_verif_root_is_unset():
    """Default behaviour must be unchanged for existing single-user installs."""
    assert app.VERIF_ROOT is None or isinstance(app.VERIF_ROOT, str)
    if app.VERIF_ROOT is None:
        assert app.path_ok("/etc/hosts")


def _reload_with_root(monkeypatch, root):
    monkeypatch.setenv("VERIF_ROOT", str(root))
    mod = importlib.reload(app)
    return mod


def test_verif_root_blocks_paths_outside_the_tree(monkeypatch, tmp_path):
    root = tmp_path / "data"; root.mkdir()
    (root / "obs.nc").write_bytes(b"x")
    mod = _reload_with_root(monkeypatch, root)
    try:
        assert mod.path_ok(str(root / "obs.nc"))
        assert mod.path_ok(str(root))
        for outside in ("/etc/passwd", "/etc", str(tmp_path / "elsewhere.nc"), "/"):
            assert not mod.path_ok(outside), f"{outside} should be refused"
        with pytest.raises(mod.PathNotAllowed):
            mod.safe_path("/etc/passwd")
    finally:
        monkeypatch.delenv("VERIF_ROOT", raising=False)
        importlib.reload(app)


def test_verif_root_blocks_traversal_out_of_the_tree(monkeypatch, tmp_path):
    root = tmp_path / "data"; root.mkdir()
    mod = _reload_with_root(monkeypatch, root)
    try:
        assert not mod.path_ok(str(root / ".." / ".." / "etc" / "passwd"))
        assert not mod.path_ok(str(root) + "/../../etc/passwd")
    finally:
        monkeypatch.delenv("VERIF_ROOT", raising=False)
        importlib.reload(app)


def test_verif_root_resolves_symlinks_before_deciding(monkeypatch, tmp_path):
    """A symlink inside the root that points outside it must still be refused."""
    root = tmp_path / "data"; root.mkdir()
    secret = tmp_path / "secret.nc"; secret.write_bytes(b"x")
    link = root / "innocent.nc"
    try:
        link.symlink_to(secret)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this platform")
    mod = _reload_with_root(monkeypatch, root)
    try:
        assert not mod.path_ok(str(link)), "a symlink escaping the root must be refused"
    finally:
        monkeypatch.delenv("VERIF_ROOT", raising=False)
        importlib.reload(app)


def test_verif_root_still_allows_the_bundled_demo(monkeypatch, tmp_path):
    """A hardened deployment must not lose the demo dataset."""
    root = tmp_path / "data"; root.mkdir()
    mod = _reload_with_root(monkeypatch, root)
    try:
        assert mod.path_ok(mod._DEMO_OBS)
    finally:
        monkeypatch.delenv("VERIF_ROOT", raising=False)
        importlib.reload(app)


def test_readers_enforce_confinement(monkeypatch, tmp_path):
    """The guard sits at the open chokepoints, not only at the UI inputs."""
    root = tmp_path / "data"; root.mkdir()
    mod = _reload_with_root(monkeypatch, root)
    try:
        with pytest.raises(mod.PathNotAllowed):
            mod._open("/etc/hosts")
        with pytest.raises(mod.PathNotAllowed):
            mod.open_any("/etc/hosts")
        with pytest.raises(mod.PathNotAllowed):
            mod.discover_models("/etc")
    finally:
        monkeypatch.delenv("VERIF_ROOT", raising=False)
        importlib.reload(app)


# --------------------------------------------------------------------------
# Unbounded directory scan -> denial of service
# --------------------------------------------------------------------------
def test_directory_scan_is_bounded(monkeypatch, tmp_path):
    """Pointing the sidebar at a huge directory must not walk all of it."""
    for i in range(50):
        (tmp_path / f"d{i:03d}").mkdir()
    monkeypatch.setattr(app, "MAX_SCAN_SUBDIRS", 5)

    seen = []
    real_isdir = os.path.isdir
    monkeypatch.setattr(os.path, "isdir", lambda p: (seen.append(p), real_isdir(p))[1])
    app.discover_models(str(tmp_path))
    assert len(seen) <= 5, f"scanned {len(seen)} entries despite a cap of 5"


def test_scan_cap_has_a_sane_default():
    assert 0 < app.MAX_SCAN_SUBDIRS <= 10000


# --------------------------------------------------------------------------
# Shipped configuration
# --------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]


def test_bundled_config_binds_loopback_only():
    cfg = (ROOT / ".streamlit" / "config.toml").read_text()
    assert 'address = "127.0.0.1"' in cfg, "the default bind address must be loopback"
    assert 'address = "0.0.0.0"' not in cfg


def test_bundled_config_keeps_xsrf_protection_on():
    cfg = (ROOT / ".streamlit" / "config.toml").read_text()
    assert "enableXsrfProtection = true" in cfg


def test_bundled_config_bounds_uploads():
    cfg = (ROOT / ".streamlit" / "config.toml").read_text()
    line = [l for l in cfg.splitlines() if l.strip().startswith("maxUploadSize")][0]
    assert int(line.split("=")[1].split("#")[0].strip()) <= 1000


def test_no_dangerous_dynamic_execution_in_the_codebase():
    src = (ROOT / "app.py").read_text()
    for bad in ("eval(", "exec(", "pickle.load", "os.system(", "shell=True", "__import__("):
        assert bad not in src, f"{bad} appeared in app.py"


def test_security_policy_is_published():
    assert (ROOT / "SECURITY.md").exists()
