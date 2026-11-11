"""Black-box checks of the standalone worktree command on each CI platform."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "skills/new-project-worktree/scripts/New-ProjectWorktree.ps1"
PWSH = shutil.which("pwsh")
GIT = shutil.which("git")


class ProjectWorktreeTests(unittest.TestCase):
    def setUp(self):
        if not PWSH or not GIT:
            self.fail("Worktree integration tests require Git and PowerShell 7.2 or later.")
        temp = tempfile.TemporaryDirectory(prefix="project-worktree-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        self.env["GIT_CONFIG_NOSYSTEM"] = "1"
        self.env["GIT_CONFIG_GLOBAL"] = str(self.root / "empty.gitconfig")
        self.repo = self.make_repo("示範 A")

    def git(self, directory, *args):
        return subprocess.run(
            [GIT, "-C", str(directory), *args],
            capture_output=True, encoding="utf-8", check=True, env=self.env, timeout=30,
        ).stdout

    def make_repo(self, name, base="develop"):
        repo = self.root / name / "repo"
        repo.mkdir(parents=True)
        self.git(repo, "init", "-b", base)
        self.git(repo, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                 "commit", "--allow-empty", "-m", "Fixture")
        return repo

    def invoke(self, cwd, name="sample-task", *options, error=None, env=None):
        args = [PWSH, "-NoProfile", "-NonInteractive", "-File", str(SCRIPT),
                "-Type", "feat", "-Name", name, *options]
        result = subprocess.run(args, cwd=cwd, capture_output=True, encoding="utf-8",
                                env=env or self.env, timeout=30)
        if error:
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn(error, result.stderr)
        else:
            self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def snapshot(self, repo):
        return self.git(repo, "show-ref"), self.git(repo, "worktree", "list", "--porcelain", "-z")

    def test_preview_from_checkout_nested_and_linked_is_read_only(self):
        linked = self.root / "another location" / "linked"
        linked.parent.mkdir()
        self.git(self.repo, "worktree", "add", "--detach", str(linked), "develop")
        nested = self.repo / "inner"
        nested.mkdir()
        before = self.snapshot(self.repo)
        expected = self.repo.parent / "worktrees" / "feat-sample-task"
        for start in (self.repo, nested, linked):
            output = self.invoke(start)
            self.assertIn("Preview", output)
            self.assertIn(str(expected), output)
            self.assertIn(self.git(self.repo, "rev-parse", "develop").strip(), output)
        self.assertEqual(before, self.snapshot(self.repo))
        self.assertFalse(expected.parent.exists())

    def test_apply_targets_its_own_project_preserves_dirty_checkout_and_uses_base(self):
        first = self.snapshot(self.repo)
        second = self.make_repo("示範 B", "main")
        dirty = second / "notes.txt"
        dirty.write_text("keep", encoding="utf-8")
        self.invoke(second, "sample-task", "-Base", "main", "-Apply")
        expected = second.parent / "worktrees" / "feat-sample-task"
        self.assertEqual(self.git(expected, "branch", "--show-current").strip(), "codex/feat/sample-task")
        self.assertEqual(self.git(expected, "rev-parse", "HEAD"), self.git(second, "rev-parse", "main"))
        self.assertEqual(dirty.read_text(encoding="utf-8"), "keep")
        self.assertFalse((expected / dirty.name).exists())
        self.assertEqual(first, self.snapshot(self.repo))

    def test_conflicts_and_unsafe_inputs_do_not_change_repository(self):
        worktrees = self.repo.parent / "worktrees"
        worktrees.mkdir()
        (worktrees / "FEAT-OCCUPIED").mkdir()
        self.git(self.repo, "branch", "codex/feat/duplicate")
        before = self.snapshot(self.repo)
        self.invoke(self.repo, "duplicate", "-Apply", error="分支名稱已占用")
        self.invoke(self.repo, "occupied", "-Apply", error="目的地已存在")
        self.invoke(self.repo, "valid", "-Base", "missing", "-Apply", error="Git")
        self.invoke(self.repo, "../escape", "-Apply", error="Name")
        self.invoke(self.repo, "UPPER", "-Apply", error="Name")
        self.invoke(self.repo, "valid", "-Apply", error="GIT_DIR",
                    env={**self.env, "GIT_DIR": str(self.repo / ".git")})
        self.assertEqual(before, self.snapshot(self.repo))
        self.assertEqual([item.name for item in worktrees.iterdir()], ["FEAT-OCCUPIED"])

    def test_rejects_redirected_worktree_directory(self):
        worktrees = self.repo.parent / "worktrees"
        outside = self.root / "outside"
        outside.mkdir()
        if os.name == "nt":
            subprocess.run(
                [PWSH, "-NoProfile", "-NonInteractive", "-Command",
                 "New-Item -ItemType Junction -Path $env:WT_TEST_LINK -Target $env:WT_TEST_OUTSIDE | Out-Null"],
                check=True, timeout=30,
                env={**self.env, "WT_TEST_LINK": str(worktrees), "WT_TEST_OUTSIDE": str(outside)},
            )
        else:
            worktrees.symlink_to(outside, target_is_directory=True)
        before = self.snapshot(self.repo)
        self.invoke(self.repo, "sample-task", "-Apply", error="junction")
        self.assertEqual(before, self.snapshot(self.repo))
        self.assertEqual(list(outside.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
