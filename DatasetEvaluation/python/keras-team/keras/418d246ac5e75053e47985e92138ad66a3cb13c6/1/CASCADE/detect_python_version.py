#!/usr/bin/env python3
"""Select a Python Docker tag from metadata in a checked-out repository."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


KNOWN_VERSIONS = (
    "3.2",
    "3.3",
    "3.4",
    "3.5",
    "3.6",
    "3.7",
    "3.8",
    "3.9",
    "3.10",
    "3.11",
    "3.12",
    "3.13",
)


def version_key(version: str) -> tuple[int, int]:
    major, minor = version.split(".", 1)
    return int(major), int(minor)


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def metadata_files(repository: Path) -> list[Path]:
    files = [
        repository / ".python-version",
        repository / ".travis.yml",
        repository / ".travis.yaml",
        repository / "tox.ini",
        repository / "setup.py",
        repository / "setup.cfg",
        repository / "pyproject.toml",
        repository / "keras" / "tools" / "pip_package" / "setup.py",
    ]

    workflows = repository / ".github" / "workflows"
    if workflows.is_dir():
        files.extend(sorted(workflows.glob("*.yml")))
        files.extend(sorted(workflows.glob("*.yaml")))

    return [path for path in files if path.is_file()]


def explicit_versions(repository: Path) -> tuple[set[str], list[str]]:
    versions: set[str] = set()
    sources: list[str] = []

    python_version_file = repository / ".python-version"
    if python_version_file.is_file():
        match = re.search(r"(?m)^\s*(3\.\d+)", read_text(python_version_file))
        if match and match.group(1) in KNOWN_VERSIONS:
            return {match.group(1)}, [".python-version"]

    for path in metadata_files(repository):
        relative = str(path.relative_to(repository))
        text = read_text(path)
        found: set[str] = set()

        if path.name in {"setup.py", "setup.cfg", "pyproject.toml"}:
            found.update(
                re.findall(r"Programming Language\s*::\s*Python\s*::\s*(3\.\d+)", text)
            )

        if path.name == "tox.ini":
            for major, minor in re.findall(r"(?<![A-Za-z0-9])py(3)(\d{1,2})(?!\d)", text):
                found.add(f"{major}.{int(minor)}")

        if path.suffix in {".yml", ".yaml"}:
            for line in text.splitlines():
                if re.search(r"python(?:-version)?\s*:", line, flags=re.IGNORECASE):
                    found.update(re.findall(r"(?<!\d)(3\.\d+)(?!\d)", line))
                elif re.search(r"\bpython\b", line, flags=re.IGNORECASE):
                    found.update(re.findall(r"(?<!\d)(3\.\d+)(?!\d)", line))

        supported = found.intersection(KNOWN_VERSIONS)
        if supported:
            versions.update(supported)
            sources.append(relative)

    return versions, sources


def requires_python(repository: Path) -> str | None:
    patterns = (
        re.compile(r"python_requires\s*=\s*['\"]([^'\"]+)"),
        re.compile(r"requires-python\s*=\s*['\"]([^'\"]+)"),
    )
    for path in metadata_files(repository):
        text = read_text(path)
        for pattern in patterns:
            match = pattern.search(text)
            if match:
                return match.group(1)
    return None


def commit_year(repository: Path) -> int:
    try:
        value = subprocess.check_output(
            ["git", "-C", str(repository), "show", "-s", "--format=%ad", "--date=format:%Y", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        return int(value)
    except (OSError, subprocess.CalledProcessError, ValueError):
        return 2020


def version_for_year(year: int) -> str:
    if year <= 2012:
        return "3.2"
    if year <= 2014:
        return "3.4"
    if year <= 2016:
        return "3.5"
    if year <= 2018:
        return "3.6"
    if year <= 2020:
        return "3.8"
    if year <= 2022:
        return "3.10"
    if year <= 2024:
        return "3.12"
    return "3.13"


def satisfies_simple_spec(version: str, spec: str) -> bool:
    current = version_key(version)
    for operator, required in re.findall(r"(<=|>=|<|>|==|~=)\s*(3\.\d+)", spec):
        target = version_key(required)
        if operator == ">=" and not current >= target:
            return False
        if operator == ">" and not current > target:
            return False
        if operator == "<=" and not current <= target:
            return False
        if operator == "<" and not current < target:
            return False
        if operator == "==" and not current == target:
            return False
        if operator == "~=" and not current >= target:
            return False
    return True


def detect(repository: Path) -> tuple[str, str]:
    versions, sources = explicit_versions(repository)
    if versions:
        return max(versions, key=version_key), ",".join(sources)

    year = commit_year(repository)
    preferred = version_for_year(year)
    spec = requires_python(repository)
    if spec:
        compatible = [version for version in KNOWN_VERSIONS if satisfies_simple_spec(version, spec)]
        if compatible:
            not_newer = [
                version for version in compatible if version_key(version) <= version_key(preferred)
            ]
            selected = max(not_newer or compatible, key=version_key)
            return selected, f"requires-python {spec}; commit year {year}"

    return preferred, f"commit year {year} fallback"


def tensorflow_version(repository: Path) -> str | None:
    for relative in ("setup.py", "pyproject.toml", "requirements.txt"):
        text = read_text(repository / relative)
        matches = re.findall(
            r"(?:tensorflow(?:-cpu)?)\s*(?:==|~=)\s*"
            r"([0-9]+(?:\.[0-9]+){1,2})",
            text,
            flags=re.IGNORECASE,
        )
        if matches:
            return matches[0]

    # Older Keras commits keep their package version in this nested setup.py.
    # The matching TensorFlow release provides the required runtime.
    keras_setup = (
        repository
        / "keras"
        / "tools"
        / "pip_package"
        / "setup.py"
    )
    text = read_text(keras_setup)

    match = re.search(
        r"(?m)^_VERSION\s*=\s*[\"']"
        r"([0-9]+(?:\.[0-9]+){1,2})"
        r"[\"']",
        text,
    )
    if match:
        return match.group(1)

    return None


def main() -> int:
    if len(sys.argv) != 2:
        print(
            f"Usage: {Path(sys.argv[0]).name} REPOSITORY",
            file=sys.stderr,
        )
        return 2

    repository = Path(sys.argv[1]).resolve()
    if not (repository / ".git").exists():
        print(f"Not a Git repository: {repository}", file=sys.stderr)
        return 2

    version, source = detect(repository)
    runtime = f"Python {version}"
    dependencies = ""

    tensorflow = tensorflow_version(repository)
    if tensorflow:
        runtime += f"; TensorFlow {tensorflow}"
        dependencies = f"tensorflow=={tensorflow}"

    print(
        f"{version}\t"
        f"{source}\t"
        f"{runtime}\t"
        f"{dependencies}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
