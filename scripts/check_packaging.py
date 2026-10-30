"""Build code/editable wheels offline and verify imports outside the checkout directory."""

import json
import os
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import zipfile
from pathlib import Path

from backend.runtime_profiles import isolated_test_environment

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ("agent", "backend", "config", "eval", "rag", "scripts", "security", "services", "tools")
REQUIRED = {
    "agent/llm/factory.py",
    "backend/__init__.py",
    "backend/api/routes/chat.py",
    "backend/bootstrap/lifespan.py",
    "backend/services/wallet/submissions.py",
    "backend/services/blockchain/transaction_builder.py",
    "rag/retrieval/search.py",
    "eval/e2e/runner.py",
    "scripts/evaluate_e2e.py",
    "config/tools.yaml",
    "config/policy.yaml",
    "backend/db/migrations/versions/0001_wallet_history.py",
}


def copy_build_source(target: Path) -> None:
    target.mkdir()
    for name in ("pyproject.toml", "README.md"):
        shutil.copy2(ROOT / name, target / name)
    for package in PACKAGES:
        for folder, directories, files in os.walk(ROOT / package):
            directories[:] = [
                name
                for name in directories
                if not name.startswith(".") and name not in {"tests", "__pycache__", "node_modules"}
            ]
            for name in files:
                path = Path(folder) / name
                if path.suffix != ".py" and not (
                    package == "config" and path.suffix in {".yaml", ".json"}
                ):
                    continue
                destination = target / path.relative_to(ROOT)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, destination)


def build(kind: str, source: Path, output: Path, environment: dict[str, str], log: Path) -> Path:
    output.mkdir()
    code = (
        f"from setuptools.build_meta import build_{kind}; build_{kind}(__import__('sys').argv[1])"
    )
    with log.open("w", encoding="utf-8") as stream:
        subprocess.run(
            [sys.executable, "-c", code, str(output)],
            cwd=source,
            env=environment,
            stdout=stream,
            stderr=subprocess.STDOUT,
            check=True,
        )
    wheels = list(output.glob("*.whl"))
    if len(wheels) != 1:
        raise RuntimeError(f"Expected one {kind} wheel; inspect {log}")
    return wheels[0]


def check_archive(path: Path) -> int:
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
    if not REQUIRED.issubset(names):
        raise RuntimeError(f"Missing packaged modules/data: {sorted(REQUIRED - names)}")
    for name in names:
        parts = Path(name).parts
        if any(
            part in {"tests", "site-packages", "__pycache__"} or part.startswith(".venv")
            for part in parts
        ) or Path(name).name.startswith(".env"):
            raise RuntimeError(f"Unexpected package member: {name}")
    return sum(name.endswith(".py") for name in names)


def check_editable(path: Path, directory: Path, environment: dict[str, str], log: Path) -> None:
    target = directory / "editable-imports"
    target.mkdir()
    with zipfile.ZipFile(path) as archive:
        for member in archive.namelist():
            if not (target / member).resolve().is_relative_to(target.resolve()):
                raise RuntimeError("Wheel member escapes the import directory")
        archive.extractall(target)
    outside = directory / "outside"
    outside.mkdir()
    code = """
import importlib, pathlib, site, sys
# Load dependencies without executing pre-existing editable .pth files.
sys.path.insert(0, sys.argv[1])
sys.path.append(sys.argv[3])
site.addsitedir(sys.argv[1])
root = pathlib.Path(sys.argv[2]).resolve()
modules = ['agent.llm.factory', 'backend.api.server', 'backend.services.wallet.submissions',
           'backend.services.blockchain.transaction_builder', 'backend.db.repositories.proposals',
           'rag.retrieval.search', 'eval.e2e.runner', 'scripts.evaluate_e2e',
           'config.settings', 'security.policy', 'services.retriever', 'tools.registry']
for name in modules:
    module = importlib.import_module(name)
    assert pathlib.Path(module.__file__).resolve().is_relative_to(root), name
print('Editable imports passed outside cwd:', len(modules))
"""
    with log.open("w", encoding="utf-8") as stream:
        subprocess.run(
            [
                sys.executable,
                "-I",
                "-S",
                "-c",
                code,
                str(target),
                str(ROOT),
                sysconfig.get_path("purelib"),
            ],
            cwd=outside,
            env=environment,
            stdout=stream,
            stderr=subprocess.STDOUT,
            check=True,
        )


def main() -> int:
    directory = ROOT / ".phase3/packaging"
    directory.mkdir(parents=True, exist_ok=True)
    environment = isolated_test_environment()
    environment.update(
        PHASE3_PROFILE="unit", TEMP=str(ROOT / ".phase3/tmp"), TMP=str(ROOT / ".phase3/tmp")
    )
    Path(environment["TEMP"]).mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="build-", dir=directory) as temporary:
        workspace = Path(temporary).resolve()
        if not workspace.is_relative_to(directory.resolve()):
            raise RuntimeError("Build workspace is outside the packaging directory")
        source = workspace / "source"
        copy_build_source(source)
        wheel = build("wheel", source, workspace / "wheel", environment, directory / "wheel.log")
        count = check_archive(wheel)
        editable = build(
            "editable", ROOT, workspace / "editable", environment, directory / "editable.log"
        )
        check_editable(editable, workspace, environment, directory / "imports.log")
    report = dict(
        passed=True,
        packaged_python_modules=count,
        required_members=len(REQUIRED),
        editable_imports=12,
        imports_outside_cwd=True,
        installed_into_environment=False,
        application_installation="source checkout with editable package mapping and root requirements",
    )
    (directory / "summary.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
