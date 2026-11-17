import importlib.util
from pathlib import Path
from types import SimpleNamespace


spec = importlib.util.spec_from_file_location("check_glibc", Path(__file__).parents[1] / "packaging/check_glibc.py")
check_glibc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_glibc)


def test_glibc_check_reads_version_needs_not_exported_symbols(tmp_path, monkeypatch):
    elf = tmp_path / "library.so"; elf.write_bytes(b"\x7fELFtest")
    (tmp_path / "README").write_text("not an ELF")
    monkeypatch.setattr(check_glibc.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=0, stderr="", stdout="Version definition section\n Name: GLIBC_9.99\n"
        "Version needs section '.gnu.version_r'\n Name: GLIBC_2.34\n Name: GLIBC_2.43\n"))
    assert check_glibc.check_bundle(tmp_path, (2, 35)) == [(elf, (2, 43))]
    assert check_glibc.check_bundle(tmp_path, (2, 43)) == []
