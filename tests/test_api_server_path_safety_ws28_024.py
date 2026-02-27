from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

import apiserver.api_server as api_server


def test_write_skill_file_writes_inside_local_skills_dir(monkeypatch, tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    monkeypatch.setattr(api_server, "LOCAL_SKILLS_DIR", skills_root)

    skill_file = api_server._write_skill_file("safe_skill", "# demo")

    assert skill_file == skills_root / "safe_skill" / "SKILL.md"
    assert skill_file.read_text(encoding="utf-8") == "# demo"


@pytest.mark.parametrize(
    "skill_name",
    [
        "../../escape",
        "..\\..\\escape",
        "bad/name",
        "bad\\name",
        "bad.name",
        "",
    ],
)
def test_write_skill_file_rejects_unsafe_skill_name(skill_name: str) -> None:
    with pytest.raises(HTTPException) as exc:
        api_server._write_skill_file(skill_name, "content")
    assert exc.value.status_code == 400


@pytest.mark.parametrize(
    "filename",
    [
        "",
        "   ",
        ".",
        "..",
        "\x00bad.txt",
    ],
)
def test_normalize_uploaded_filename_rejects_invalid_names(filename: str) -> None:
    with pytest.raises(HTTPException) as exc:
        api_server._normalize_uploaded_filename(filename)
    assert exc.value.status_code == 400


def test_normalize_uploaded_filename_keeps_basename_only() -> None:
    assert api_server._normalize_uploaded_filename("report.txt") == "report.txt"
    assert api_server._normalize_uploaded_filename("../report.txt") == "report.txt"
    assert api_server._normalize_uploaded_filename(r"C:\fakepath\report.txt") == "report.txt"
