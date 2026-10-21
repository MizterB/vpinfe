#!/usr/bin/env python3
"""Putting SDL3 into a build, and checking that it got there. Run by CI, not by the app.

    fetch_sdl3_bundle.py fetch --version 3.4.16 --triplet linux-x64
    fetch_sdl3_bundle.py check --version 3.4.16 dist

`fetch` leaves one library, named per platform in LIBRARY, in third_party/sdl3. Windows and
macOS take SDL's own release; SDL publishes no Linux library, so Linux builds the release
source on the runner. `check` finds that library inside a finished build, loads it and
compares the version SDL reports: a missing native library is invisible to the test suite and
only fails on a cabinet.
"""

import argparse
import ctypes
import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

LIBRARY = {
    "win-x64": "SDL3.dll",
    "macos-arm64": "libSDL3.dylib",
    "linux-x64": "libSDL3.so.0",
    "linux-arm64": "libSDL3.so.0",
}
MARKER = ".version"

# The release asset each kind of build takes, named for the version.
ASSETS = {
    "win-x64": "SDL3-{version}-win32-x64.zip",
    "macos-arm64": "SDL3-{version}.dmg",
    "source": "SDL3-{version}.tar.gz",
}
# The one version every triplet ships. A bump is a new entry here and the same number in
# SDL3_VERSION in .github/workflows/build.yml; the digests are the release assets', so an
# asset that changes underneath a tag fails the build.
RELEASES = {
    "3.4.16": {
        "win-x64": "4217944b4e51457af4a59c82d883f8443b3e65964b2acd8943484c492756c4b6",
        "macos-arm64": "675660a9e457239af615f9e41f788612168d1639b9d2eda2957e8dace26687fd",
        "source": "7322236cd12090c3eb40b9728be4d49c76f66ad17d04369584d4ecad5cf77c68",
    },
}


def _download(version: str, asset: str, expected_sha: str, dest: Path) -> None:
    url = f"https://github.com/libsdl-org/SDL/releases/download/release-{version}/{asset}"
    print(f"[SDL3 FETCH] Downloading {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "vpinfe-sdl3-fetcher"})
    digest = hashlib.sha256()
    with urllib.request.urlopen(req) as response, dest.open("wb") as out:
        for chunk in iter(lambda: response.read(1024 * 1024), b""):
            digest.update(chunk)
            out.write(chunk)
    if digest.hexdigest() != expected_sha:
        raise SystemExit(
            f"[SDL3 FETCH] SHA256 mismatch for {asset}.\n"
            f"  expected: {expected_sha}\n  actual:   {digest.hexdigest()}"
        )
    print("[SDL3 FETCH] SHA256 verified.")


def take_from_zip(archive: Path, outdir: Path) -> None:
    """SDL's Windows zip holds the DLL and its license at the top; nothing else ships."""
    with zipfile.ZipFile(archive) as zf:
        for name in (LIBRARY["win-x64"], "LICENSE.txt"):
            (outdir / name).write_bytes(zf.read(name))


def take_from_dmg(archive: Path, outdir: Path, scratch: Path) -> None:
    """The arm64 library from the dmg's framework, signed again ad hoc: thinning invalidates
    the signature, and an arm64 process refuses an unsigned library."""
    mount = scratch / "mount"
    mount.mkdir()
    subprocess.run(["hdiutil", "attach", "-nobrowse", "-readonly", "-mountpoint", str(mount),
                    str(archive)], check=True)
    try:
        framework = mount / "SDL3.xcframework" / "macos-arm64_x86_64" / "SDL3.framework"
        target = outdir / LIBRARY["macos-arm64"]
        subprocess.run(["lipo", str(framework / "Versions" / "A" / "SDL3"), "-thin", "arm64",
                        "-output", str(target)], check=True)
        subprocess.run(["codesign", "--force", "--sign", "-", str(target)], check=True)
        shutil.copy2(mount / "LICENSE.txt", outdir / "LICENSE.txt")
    finally:
        if subprocess.run(["hdiutil", "detach", str(mount)], check=False).returncode:
            subprocess.run(["hdiutil", "detach", "-force", str(mount)], check=True)


def build_from_source(archive: Path, outdir: Path, scratch: Path) -> None:
    """Builds the release tarball and leaves the library under the name a loader asks for."""
    with tarfile.open(archive) as tf:
        tf.extractall(scratch, filter="data")
    (source,) = [path for path in scratch.iterdir() if path.is_dir()]
    subprocess.run(["cmake", "-S", str(source), "-B", str(scratch / "build"),
                    "-DCMAKE_BUILD_TYPE=Release", "-DSDL_SHARED=ON", "-DSDL_STATIC=OFF",
                    "-DSDL_TESTS=OFF", "-DSDL_EXAMPLES=OFF", "-DSDL_TEST_LIBRARY=OFF",
                    "-DSDL_UNIX_CONSOLE_BUILD=ON"],
                   check=True)
    subprocess.run(["cmake", "--build", str(scratch / "build"), "--parallel",
                    str(os.cpu_count() or 2)], check=True)
    # The soname and the dev symlink sit beside the real file; only the real one is copied,
    # under the soname, because that is the name a loader asks for.
    (built,) = [path for path in (scratch / "build").glob("libSDL3.so.*.*.*")
                if not path.is_symlink()]
    shutil.copy2(built, outdir / LIBRARY["linux-x64"])
    shutil.copy2(source / "LICENSE.txt", outdir / "LICENSE.txt")


def fetch(version: str, triplet: str, outdir: Path) -> None:
    if version not in RELEASES:
        raise SystemExit(f"[SDL3 FETCH] No digests for {version}; add them to RELEASES.")
    if triplet not in LIBRARY:
        raise SystemExit(f"[SDL3 FETCH] Unsupported triplet: {triplet}")
    stamp = f"{version} {triplet}"
    marker = outdir / MARKER
    # A cached Linux build lands here whole, so a hit costs nothing.
    if marker.is_file() and marker.read_text().strip() == stamp \
            and (outdir / LIBRARY[triplet]).is_file():
        print(f"[SDL3 FETCH] {stamp} already in {outdir}.")
        return

    kind = "source" if triplet.startswith("linux-") else triplet
    asset, sha = ASSETS[kind].format(version=version), RELEASES[version][kind]
    if outdir.exists():
        shutil.rmtree(outdir)
    outdir.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix="vpinfe-sdl3-") as td:
        scratch = Path(td)
        archive = scratch / asset
        _download(version, asset, sha, archive)
        work = scratch / "work"
        work.mkdir()
        if kind == "win-x64":
            take_from_zip(archive, outdir)
        elif kind == "macos-arm64":
            take_from_dmg(archive, outdir, work)
        else:
            build_from_source(archive, outdir, work)
    marker.write_text(stamp + "\n")
    print(f"[SDL3 FETCH] Installed {stamp} to {outdir}")


def _reported_version(library: Path) -> tuple[int, int, int]:
    """SDL_GetVersion packs major*1000000 + minor*1000 + micro into one int."""
    sdl = ctypes.CDLL(str(library))
    sdl.SDL_GetVersion.restype = ctypes.c_int
    packed = sdl.SDL_GetVersion()
    return packed // 1000000, packed // 1000 % 1000, packed % 1000


def check(version: str, dist: Path) -> None:
    names = sorted(set(LIBRARY.values()))
    found = sorted(path for name in names for path in dist.rglob(name)
                   if path.parent.name == "sdl3" and path.parent.parent.name == "third_party")
    if not found:
        raise SystemExit(f"[SDL3 CHECK] No SDL3 library under {dist}/**/third_party/sdl3.")
    wanted = tuple(int(part) for part in version.split("."))
    for library in found:
        reported = _reported_version(library)
        print(f"[SDL3 CHECK] {library} reports SDL {'.'.join(map(str, reported))}")
        if reported != wanted:
            raise SystemExit(f"[SDL3 CHECK] Expected SDL {version}.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    fetching = commands.add_parser("fetch", help="Put SDL3 into third_party/sdl3.")
    fetching.add_argument("--version", required=True)
    fetching.add_argument("--triplet", required=True, choices=sorted(LIBRARY))
    fetching.add_argument("--outdir", default="third_party/sdl3", type=Path)
    checking = commands.add_parser("check", help="Load SDL3 out of a finished build.")
    checking.add_argument("--version", required=True)
    checking.add_argument("dist", type=Path)
    args = parser.parse_args()
    if args.command == "fetch":
        fetch(args.version, args.triplet, args.outdir)
    else:
        check(args.version, args.dist)
    return 0


if __name__ == "__main__":
    sys.exit(main())
