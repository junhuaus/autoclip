import subprocess
from pathlib import Path

import pytest

import liveclip.services.demo_media as demo_media
from liveclip.services.demo_media import (
    DemoMediaError,
    build_demo_source_argv,
    clean_demo_contents,
    create_demo_source,
)


def test_demo_source_uses_argument_array_and_shell_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed: dict[str, object] = {}

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        observed["argv"] = argv
        observed.update(kwargs)
        Path(argv[-1]).write_bytes(b"generated-demo" * 1_000)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(demo_media.subprocess, "run", fake_run)
    output = tmp_path / "source.mp4"
    create_demo_source(output_path=output, duration_ms=96_000, ffmpeg_path="/fake/ffmpeg")

    assert output.is_file()
    assert observed["shell"] is False
    assert isinstance(observed["argv"], list)
    assert "between(t,30.000,32.000)" in " ".join(observed["argv"])  # type: ignore[arg-type]


def test_demo_source_argv_contains_real_audio_video_and_silence() -> None:
    argv = build_demo_source_argv(
        output_path=Path("/tmp/generated.mp4"),
        duration_ms=96_000,
    )
    assert "testsrc2=size=640x360:rate=24:duration=96.000" in argv
    assert "sine=frequency=660:sample_rate=48000:duration=96.000" in argv
    assert any("between(t,62.000,64.000)" in argument for argument in argv)
    assert "libx264" in argv and "aac" in argv


def test_clean_demo_only_removes_validated_demo_children(tmp_path: Path) -> None:
    project_root = tmp_path / "repo"
    demo_root = project_root / "data" / "demo"
    demo_root.mkdir(parents=True)
    (project_root / "data" / "projects").mkdir()
    (demo_root / ".gitkeep").write_text("", encoding="utf-8")
    projects_root = demo_root / "projects"
    projects_root.mkdir()
    generated = projects_root / "demo_20260803T101112_1234abcd"
    generated.mkdir()
    (generated / ".phase.json").write_text('{"phase":"delivered"}', encoding="utf-8")
    (generated / "artifact.txt").write_text("generated", encoding="utf-8")
    unowned_file = demo_root / "keep-me.txt"
    unowned_file.write_text("user data", encoding="utf-8")
    unowned_project = projects_root / "project-a"
    unowned_project.mkdir()

    removed = clean_demo_contents(project_root=project_root, allowed_media_roots=())

    assert removed == 1
    assert not generated.exists()
    assert unowned_file.read_text(encoding="utf-8") == "user data"
    assert unowned_project.is_dir()
    assert (demo_root / ".gitkeep").is_file()


def test_clean_demo_preserves_unmarked_demo_shaped_project(tmp_path: Path) -> None:
    project_root = tmp_path / "repo"
    projects_root = project_root / "data" / "demo" / "projects"
    projects_root.mkdir(parents=True)
    (project_root / "data" / "projects").mkdir()
    unmarked = projects_root / "demo_20260803T101112_1234abcd"
    unmarked.mkdir()
    (unmarked / "important.txt").write_text("preserve", encoding="utf-8")

    removed = clean_demo_contents(project_root=project_root, allowed_media_roots=())

    assert removed == 0
    assert (unmarked / "important.txt").read_text(encoding="utf-8") == "preserve"


def test_clean_demo_rejects_allowed_root_overlap(tmp_path: Path) -> None:
    project_root = tmp_path / "repo"
    demo_root = project_root / "data" / "demo"
    demo_root.mkdir(parents=True)
    (project_root / "data" / "projects").mkdir()

    with pytest.raises(DemoMediaError, match="allowed media root"):
        clean_demo_contents(project_root=project_root, allowed_media_roots=(demo_root,))
