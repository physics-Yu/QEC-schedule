"""Campaign source freezing is opt-in, content-based, and scope-preserving."""

import hashlib
from pathlib import Path

import pytest

from nadit_physical_compiler.experiments import version


@pytest.fixture
def checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    files = {
        "modules/physical_compiler/src/package/runtime.py": "physical = 1\n",
        "modules/physical_compiler/pyproject.toml": "[project]\n",
        "modules/physical_compiler/uv.lock": "version = 1\n",
        "modules/codes/component.py": "component = 1\n",
        "modules/codes/configs/device.json": '{"load_us":10}\n',
        "modules/logical_compiler/src/runtime.py": "logical = 1\n",
        "modules/logical_compiler/configs/recipe.json": "{}\n",
        "experiments/msd/campaign.py": "campaign = 1\n",
        "experiments/msd/noise.json": "{}\n",
    }
    for name, content in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    monkeypatch.setattr(version, "MODULE", tmp_path / "modules/physical_compiler")
    monkeypatch.setattr(
        version.subprocess,
        "check_output",
        lambda command, **kwargs: (
            "frozen-commit\n" if command[1] == "rev-parse" else ""
        ),
    )
    return tmp_path


def test_default_version_retains_original_physical_scope_and_hash(
    checkout: Path,
) -> None:
    module = checkout / "modules/physical_compiler"
    digest = hashlib.sha256()
    for path in [
        *sorted((module / "src").rglob("*.py")),
        module / "pyproject.toml",
        module / "uv.lock",
    ]:
        digest.update(path.relative_to(module).as_posix().encode())
        digest.update(b"\0" + path.read_bytes() + b"\0")
    snapshot = version.code_version(allow_dirty=False)
    assert snapshot == {
        "commit": "frozen-commit",
        "dirty": False,
        "source_hash": digest.hexdigest(),
    }
    (checkout / "modules/codes/component.py").write_text("changed", encoding="utf-8")
    version.check_version(snapshot)


@pytest.mark.parametrize(
    "name",
    (
        "modules/codes/component.py",
        "modules/codes/configs/device.json",
        "modules/logical_compiler/src/runtime.py",
        "modules/logical_compiler/configs/recipe.json",
        "experiments/msd/campaign.py",
        "experiments/msd/noise.json",
        "modules/physical_compiler/uv.lock",
        "modules/physical_compiler/pyproject.toml",
    ),
)
def test_msd_detects_changed_source_references_and_environment(
    checkout: Path, name: str
) -> None:
    snapshot = version.code_version(allow_dirty=False, scope="msd")
    version.check_version(snapshot)
    (checkout / name).write_text("changed bytes", encoding="utf-8")
    with pytest.raises(ValueError, match="Code changed"):
        version.check_version(snapshot)


@pytest.mark.parametrize(
    "directory",
    (
        "modules/codes",
        "modules/logical_compiler/src",
        "experiments/msd",
    ),
)
def test_msd_detects_added_and_deleted_relevant_files(
    checkout: Path, directory: str
) -> None:
    before = version.code_version(allow_dirty=False, scope="msd")
    added = checkout / directory / "added.json"
    added.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="Code changed"):
        version.check_version(before)
    after = version.code_version(allow_dirty=False, scope="msd")
    added.unlink()
    with pytest.raises(ValueError, match="Code changed"):
        version.check_version(after)


def test_msd_excludes_runtime_outputs_and_tests(checkout: Path) -> None:
    snapshot = version.code_version(allow_dirty=False, scope="msd")
    for folder in ("tests", "artifacts", "results", "__pycache__"):
        path = checkout / "experiments/msd" / folder / "generated.json"
        path.parent.mkdir()
        path.write_text("{}", encoding="utf-8")
    version.check_version(snapshot)


def test_explicit_reference_scope_is_persisted_and_rechecked(checkout: Path) -> None:
    reference = checkout / "inputs/device.json"
    reference.parent.mkdir()
    reference.write_text("{}", encoding="utf-8")
    snapshot = version.code_version(
        allow_dirty=False, source_paths=("inputs/device.json",)
    )
    assert snapshot["source_paths"] == ["inputs/device.json"]
    version.check_version(snapshot)
    reference.unlink()
    with pytest.raises(ValueError, match="Code changed"):
        version.check_version(snapshot)


def test_explicit_tree_detects_added_reference(checkout: Path) -> None:
    folder = checkout / "inputs"
    folder.mkdir()
    snapshot = version.code_version(
        allow_dirty=False, scope="msd", source_paths=("inputs",)
    )
    (folder / "device.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="Code changed"):
        version.check_version(snapshot)


@pytest.mark.parametrize(
    "path", ("../outside", "/absolute", "C:\\outside", "inputs/../../outside")
)
def test_explicit_sources_must_stay_inside_checkout(checkout: Path, path: str) -> None:
    with pytest.raises(ValueError, match="source_paths"):
        version.code_version(allow_dirty=False, scope="msd", source_paths=(path,))


def test_deleted_environment_lock_invalidates_campaign(checkout: Path) -> None:
    snapshot = version.code_version(allow_dirty=False, scope="msd")
    (checkout / "modules/physical_compiler/uv.lock").unlink()
    with pytest.raises(ValueError, match="Code changed"):
        version.check_version(snapshot)


def test_added_and_deleted_root_environment_manifest_invalidates_campaign(
    checkout: Path,
) -> None:
    before = version.code_version(allow_dirty=False, scope="msd")
    manifest = checkout / "requirements.txt"
    manifest.write_text("package==1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Code changed"):
        version.check_version(before)
    after = version.code_version(allow_dirty=False, scope="msd")
    manifest.unlink()
    with pytest.raises(ValueError, match="Code changed"):
        version.check_version(after)
