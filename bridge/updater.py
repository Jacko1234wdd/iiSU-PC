"""
Checks for updates to iiSU-PC itself, run first thing by start_iisu_pc.py
so a normal day-to-day start always at least knows whether it's running
stale code -- and, for a git checkout, gets current automatically.

Two install shapes, two different checks:

  - A git checkout (PROJECT_ROOT has a .git folder -- the normal case for
    a dev clone, on whichever branch, master or dev): `git fetch` the
    current branch, then a fast-forward-only `git pull` if it's behind.
    No special-casing between dev and master is needed -- whatever branch
    is actually checked out is the one this fetches and fast-forwards,
    so a dev checkout updates from dev and a master checkout updates from
    master automatically. --ff-only is what makes this safe to run
    unattended before every single start: it only ever applies a clean,
    already-merged update, and refuses outright (never merges, rebases,
    or clobbers) the moment there's any local commit or edit it would
    otherwise have to reconcile -- the worst case is always "did nothing,
    printed why."
  - A plain extracted/zipped install (no .git -- a normal end user's
    download): there's no git-guaranteed-safe way to replace those files
    in place (this very process could have one of them open, and a real
    config.json living alongside them is exactly the kind of file an
    in-place file swap could clobber, unlike git which already refuses to
    touch anything with uncommitted local changes). This only compares
    VERSION against the latest GitHub Release tag and prints a link --
    never downloads or touches anything.

Best-effort throughout: no internet, GitHub/the remote being unreachable,
or git not being on PATH all skip silently (well, loudly to the log, but
never fatally) -- this is a nice-to-have layered on top of starting
iiSU-PC, never a prerequisite for it. A successful pull also can't take
effect in the process that just applied it (Python already loaded the old
files into memory) -- it always says so, since the honest fix is "restart
iiSU-PC," not pretending to hot-swap running code.
"""

import json
import subprocess
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
GIT_DIR = PROJECT_ROOT / ".git"
VERSION_PATH = PROJECT_ROOT / "VERSION"
GITHUB_REPO = "MAGOOSKEE/iiSU-PC"
GIT_TIMEOUT = 10.0
HTTP_TIMEOUT = 5.0


def _run_git(args: list[str]) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(
            ["git", *args], cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=GIT_TIMEOUT
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def is_git_checkout() -> bool:
    return GIT_DIR.is_dir()


def current_branch() -> str | None:
    result = _run_git(["rev-parse", "--abbrev-ref", "HEAD"])
    if result is None or result.returncode != 0:
        return None
    branch = result.stdout.strip()
    return branch if branch and branch != "HEAD" else None


def check_and_apply_git_update() -> None:
    branch = current_branch()
    if branch is None:
        print("[updater] git checkout isn't on a branch (detached HEAD?) -- skipping the update check")
        return

    print(f"[updater] checking for updates ({branch})...")
    fetch = _run_git(["fetch", "origin", branch])
    if fetch is None or fetch.returncode != 0:
        reason = fetch.stderr.strip()[:200] if fetch else "git not found or fetch timed out"
        print(f"[updater] couldn't reach GitHub to check for updates -- continuing with what's here ({reason})")
        return

    local = _run_git(["rev-parse", "HEAD"])
    remote = _run_git(["rev-parse", f"origin/{branch}"])
    local_sha = local.stdout.strip() if local and local.returncode == 0 else None
    remote_sha = remote.stdout.strip() if remote and remote.returncode == 0 else None
    if not local_sha or not remote_sha:
        print("[updater] couldn't compare local/remote commits -- skipping")
        return
    if local_sha == remote_sha:
        print(f"[updater] already up to date ({branch}).")
        return

    count = _run_git(["rev-list", "--count", f"HEAD..origin/{branch}"])
    behind = count.stdout.strip() if count and count.returncode == 0 else "some"
    print(f"[updater] {behind} new commit(s) on {branch} -- pulling...")

    pull = _run_git(["pull", "--ff-only", "origin", branch])
    if pull is not None and pull.returncode == 0:
        print(f"[updater] updated to the latest {branch}. This run is still using the old code -- restart iiSU-PC to pick it up.")
    else:
        reason = pull.stderr.strip()[:300] if pull else "git not found or pull timed out"
        print(
            f"[updater] {behind} update(s) available on {branch}, but couldn't fast-forward automatically "
            f"(likely local changes here) -- update manually with `git pull` when convenient:\n[updater]   {reason}"
        )


def check_release_update() -> None:
    current = VERSION_PATH.read_text(encoding="utf-8").strip() if VERSION_PATH.is_file() else None
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
            headers={"User-Agent": "iiSU-PC", "Accept": "application/vnd.github+json"},
        )
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            latest = json.loads(resp.read())["tag_name"]
    except Exception as e:
        print(f"[updater] couldn't check for updates ({e}) -- continuing")
        return

    if current is None:
        print(f"[updater] latest release is {latest} (this install doesn't have a VERSION file to compare against)")
    elif current == latest:
        print(f"[updater] already on the latest release ({current}).")
    else:
        print(
            f"[updater] a newer release is available: {latest} (this install is {current}) -- "
            f"https://github.com/{GITHUB_REPO}/releases/latest"
        )


def check_for_updates() -> None:
    """Never raises -- called unconditionally at the top of every
    start_iisu_pc.py run, and a broken update check is never a good
    reason to fail an otherwise-normal start."""
    try:
        if is_git_checkout():
            check_and_apply_git_update()
        else:
            check_release_update()
    except Exception as e:
        print(f"[updater] update check failed ({e}) -- continuing")
