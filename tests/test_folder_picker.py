"""Test per app/folder_picker.py (dialog nativo via PowerShell, no tkinter)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import folder_picker as fp  # noqa: E402

WINDOWS = sys.platform.startswith("win")


@pytest.mark.skipif(not WINDOWS, reason="solo Windows")
def test_is_available_true_on_windows():
    # Windows + powershell presente -> dialog nativo disponibile (no tkinter).
    assert fp.is_available() is True


def test_build_ps_script_includes_initialdir():
    s = fp._build_ps_script(r"C:\Users\Tizio\Documents")
    assert "FolderBrowserDialog" in s
    assert r"C:\Users\Tizio\Documents" in s
    assert "ShowDialog" in s


def test_build_ps_script_escapes_single_quotes():
    s = fp._build_ps_script("C:\\a'b")
    # quote singola raddoppiata (escape PowerShell), nessuna quota nuda non-escaped
    assert "a''b" in s


def test_build_ps_script_no_initialdir_ok():
    s = fp._build_ps_script(None)
    assert "FolderBrowserDialog" in s


def test_parse_result_empty_returns_none():
    assert fp._parse_result("") is None
    assert fp._parse_result(None) is None
    assert fp._parse_result("   \n") is None


def test_parse_result_path_stripped():
    assert fp._parse_result("  C:\\Users\\Out\r\n") == "C:\\Users\\Out"


def test_default_output_dir_creates():
    d = fp.default_output_dir()
    assert d.exists()
    assert d.name == "GLM-OCR"
