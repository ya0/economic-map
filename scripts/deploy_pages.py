#!/usr/bin/env python3
"""Publish the built web app on GitHub Pages: build web/dist, then push it to the `gh-pages` branch (README.md, Deploy).

    python scripts/deploy_pages.py                 build, show what would be pushed, ask, push to `origin`
    python scripts/deploy_pages.py <repo url>      the same, to this repository (or set ECONVIZ_PAGES_REPO)
    python scripts/deploy_pages.py --yes           no question (for a script)
    python scripts/deploy_pages.py --no-build      push the build directory as it is

Each deploy is one commit without a parent, force-pushed: the branch holds the current site and no history, so
replaced tiles and surfaces (85 MB per build) do not pile up. The commit's author is the project's public name and
address below, never the address in the local git configuration.
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
AUTHOR = ("Yannik Ammann", "contact@yammann.ch")
BRANCH = "gh-pages"
INPUTS = ("regions.pmtiles", "indicators.json", "sources.json", "smooth/smooth.json")  # pipeline outputs in web/public
MAX_FILE, MAX_SITE = 100e6, 1e9  # GitHub: files above 100 MB are refused; a Pages site may hold 1 GB


def fail(msg: str):
    sys.exit(f"deploy_pages: {msg}")


def run(*cmd: str, cwd: Path) -> str:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode:
        fail(f"{' '.join(cmd[:2])} failed:\n{(proc.stderr or proc.stdout)[-2000:]}")
    return proc.stdout.strip()


def build(out: Path):
    if missing := [n for n in INPUTS if not (WEB / "public" / n).is_file()]:
        fail(f"web/public lacks {', '.join(missing)}: run econviz.build, econviz.tiles and econviz.smooth first (README.md, Build)")
    npm = shutil.which("npm") or fail("npm not found")
    run(npm, "run", "build", "--", "--outDir", str(out), "--emptyOutDir", cwd=WEB)


def check(dist: Path) -> list[Path]:
    """The files to publish; refuses an unfinished build or one GitHub would reject."""
    if not (dist / "index.html").is_file() or not all((dist / n).is_file() for n in INPUTS):
        fail(f"{dist} is not a finished build (index.html or a pipeline output is missing)")
    files = [p for p in dist.rglob("*") if p.is_file()]
    if big := [f"{p.relative_to(dist)} ({p.stat().st_size / 1e6:.0f} MB)" for p in files if p.stat().st_size > MAX_FILE]:
        fail(f"files above GitHub's 100 MB limit: {', '.join(big)}")
    if sum(p.stat().st_size for p in files) > MAX_SITE:
        fail("the site exceeds the 1 GB GitHub Pages limit")
    return files


def publish(dist: Path, repo: str, message: str):
    """Push a copy of `dist` to `repo` as the single commit of the `gh-pages` branch."""
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "site"
        shutil.copytree(dist, work)
        (work / ".nojekyll").touch()  # serve every file as it is
        run("git", "init", "-q", "-b", BRANCH, cwd=work)
        run("git", "add", "-A", cwd=work)
        run("git", "-c", f"user.name={AUTHOR[0]}", "-c", f"user.email={AUTHOR[1]}", "-c", "commit.gpgsign=false",
            "commit", "-q", "-m", message, cwd=work)
        run("git", "push", "--force", repo, f"HEAD:{BRANCH}", cwd=work)


def main(argv=None) -> bool:
    """True when the site was pushed."""
    p = argparse.ArgumentParser(description="Build the web app and push it to the gh-pages branch.")
    p.add_argument("repo", nargs="?", help="repository URL (default: $ECONVIZ_PAGES_REPO, else the `origin` remote)")
    p.add_argument("--yes", action="store_true", help="push without asking")
    p.add_argument("--no-build", action="store_true", help="push the build directory as it is")
    p.add_argument("--out", type=Path, default=WEB / "dist", help="build directory (default: web/dist)")
    args = p.parse_args(argv)

    repo = args.repo or os.environ.get("ECONVIZ_PAGES_REPO")
    if not repo:
        proc = subprocess.run(["git", "remote", "get-url", "origin"], cwd=ROOT, capture_output=True, text=True)
        repo = proc.stdout.strip() if proc.returncode == 0 else None
    if not repo:
        print("no repository: pass its URL, set ECONVIZ_PAGES_REPO or add an `origin` remote. Nothing done.")
        return False
    out = args.out.resolve()
    if not args.no_build:
        build(out)
    files = check(out)
    print(f"{len(files)} files, {sum(f.stat().st_size for f in files) / 1e6:.1f} MB -> {repo} branch {BRANCH}, replacing what is there")
    if not args.yes and input("Push? [y/N] ").strip().lower() != "y":
        print("Nothing pushed.")
        return False
    publish(out, repo, f"Deploy {date.today().isoformat()}")
    print("pushed. GitHub Pages shows it within a few minutes.")
    return True


if __name__ == "__main__":
    main()
