import importlib.util
import subprocess
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("deploy_pages", Path(__file__).parents[1] / "scripts" / "deploy_pages.py")
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)


def site(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    for name in ("index.html", "assets/app.js", *deploy.INPUTS):
        (dist / name).parent.mkdir(parents=True, exist_ok=True)
        (dist / name).write_text(name)
    return dist


def git(*args, cwd) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def test_a_build_without_its_pipeline_outputs_is_refused(tmp_path):
    dist = site(tmp_path)
    (dist / "regions.pmtiles").unlink()
    with pytest.raises(SystemExit):
        deploy.check(dist)
    assert len(deploy.check(site(tmp_path / "ok"))) == 2 + len(deploy.INPUTS)


def test_each_deploy_replaces_gh_pages_with_one_parentless_commit_by_the_public_author(tmp_path):
    bare = tmp_path / "repo.git"
    git("init", "-q", "--bare", str(bare), cwd=tmp_path)
    dist = site(tmp_path)
    deploy.publish(dist, str(bare), "Deploy 1")
    (dist / "index.html").write_text("new")
    deploy.publish(dist, str(bare), "Deploy 2")
    assert git("rev-list", "--count", "gh-pages", cwd=bare) == "1"
    assert git("log", "-1", "--format=%an <%ae> %s", "gh-pages", cwd=bare) == f"{deploy.AUTHOR[0]} <{deploy.AUTHOR[1]}> Deploy 2"
    files = set(git("ls-tree", "-r", "--name-only", "gh-pages", cwd=bare).splitlines())
    assert {".nojekyll", "index.html", "smooth/smooth.json"} <= files
    assert git("show", "gh-pages:index.html", cwd=bare) == "new"
