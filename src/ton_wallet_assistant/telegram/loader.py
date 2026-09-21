"""libtdjson binary discovery — pure Python, no build-time components.

Search order (first existing file wins):

1. explicit path (``TDLIB_PATH`` env or constructor argument)
2. macOS ``.app`` bundle dirs — ``Contents/Frameworks``, ``Contents/Resources``,
   ``Contents/MacOS`` (relative to the app executable) — and PyInstaller's
   ``sys._MEIPASS`` when frozen
3. package-adjacent dirs — this package's directory, the ``lib``/``libs``/
   ``native``/``bin`` subdirectories of the package root, and the repo/app
   root (``cwd`` + its ``lib``/``libs``)
4. runtime loader/system paths — ``ctypes.util.find_library('tdjson')``
   then the bare platform filename handed to the OS loader

The resolver never mutates anything; ``searched_paths()`` returns the full
candidate list for diagnostics when loading fails.
"""

from __future__ import annotations

import ctypes.util
import os
import sys
from pathlib import Path


def platform_library_name(platform: str | None = None) -> str:
    """The libtdjson filename for a platform string (``sys.platform``)."""
    platform = sys.platform if platform is None else platform
    if platform == "darwin":
        return "libtdjson.dylib"
    if platform.startswith("win"):
        return "tdjson.dll"
    return "libtdjson.so"


def _bundle_dirs(executable: Path | None = None) -> list[Path]:
    """macOS .app / frozen-app directories that commonly ship binaries."""
    exe = executable or Path(sys.executable)
    dirs: list[Path] = []
    # <App>.app/Contents/{MacOS,Frameworks,Resources}
    for parent in exe.parents:
        if parent.name == "MacOS" and parent.parent.name == "Contents":
            contents = parent.parent
            dirs += [contents / "Frameworks", contents / "Resources", contents / "MacOS"]
            break
    # PyInstaller-style frozen bundles
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        dirs.append(Path(meipass))
    if getattr(sys, "frozen", False):
        dirs.append(exe.parent)
    return dirs


def candidate_dirs() -> list[Path]:
    """All directories searched, in order, for the platform filename."""
    package_dir = Path(__file__).resolve().parent  # .../telegram/
    package_root = package_dir.parent  # ton_wallet_assistant/
    dirs: list[Path] = []
    dirs += _bundle_dirs()
    dirs += [package_dir, package_root]
    for base in (package_root, Path.cwd()):
        for sub in ("lib", "libs", "native", "bin"):
            dirs.append(base / sub)
    # de-duplicate, preserving order
    seen: set[Path] = set()
    unique: list[Path] = []
    for d in dirs:
        if d not in seen:
            seen.add(d)
            unique.append(d)
    return unique


def searched_paths(
    explicit: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> list[str]:
    """Every location that will be tried, in order — for error diagnostics."""
    env = os.environ if env is None else env
    name = platform_library_name()
    paths: list[str] = []
    if explicit:
        paths.append(str(explicit))
    if env.get("TDLIB_PATH") and str(env["TDLIB_PATH"]) != str(explicit):
        paths.append(env["TDLIB_PATH"])
    for d in candidate_dirs():
        paths.append(str(d / name))
    found = ctypes.util.find_library("tdjson")
    if found:
        paths.append(found)
    # bare filenames → OS loader search path (LD_LIBRARY_PATH, PATH, etc.)
    for bare in (name, "libtdjson.so", "tdjson.dll", "libtdjson.dylib", "libtdjson.so.0"):
        if bare not in paths:
            paths.append(bare)
    return paths


def resolve_tdjson_library(
    explicit: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> Path | None:
    """Return the filesystem path to libtdjson, or None if only the OS loader
    can find it (bare-name fallback). Explicit path wins over everything."""
    env = os.environ if env is None else env
    name = platform_library_name()

    candidates: list[str | Path] = []
    if explicit:
        candidates.append(explicit)
    if env.get("TDLIB_PATH"):
        candidates.append(env["TDLIB_PATH"])
    for d in candidate_dirs():
        candidates.append(d / name)

    for c in candidates:
        p = Path(c)
        if p.is_file():
            return p
    return None
