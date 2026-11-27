"""Black-box checks of the idea-assessment helper CLI."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/idea-assessment/scripts/idea_assessment.py"
EXAMPLE = ROOT / "skills/idea-assessment/examples/assessment.json"


class IdeaAssessmentCliTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="idea-assessment-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.home = self.root / "home"
        self.home.mkdir()
        self.env = {
            key: value
            for key, value in os.environ.items()
            if key not in {"IDEA_ASSESSMENT_CONFIG", "XDG_DATA_HOME", "XDG_CONFIG_HOME"}
        }
        self.env.update({"HOME": str(self.home), "USERPROFILE": str(self.home)})

    def run_cli(self, *args, cwd=None, check=True):
        result = subprocess.run(
            [sys.executable, "-I", str(SCRIPT), *args],
            capture_output=True, encoding="utf-8", env=self.env, cwd=cwd or self.root, timeout=30,
        )
        if check and result.returncode != 0:
            self.fail(f"exit {result.returncode}: {result.stderr}")
        return result

    def json_out(self, *args, cwd=None):
        return json.loads(self.run_cli(*args, cwd=cwd).stdout)

    def write_config(self, data, name="config.json"):
        path = self.root / "cfg" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
        self.env["IDEA_ASSESSMENT_CONFIG"] = str(path)
        return path

    def test_default_output_root_follows_platform_convention(self):
        result = self.json_out("path")
        if sys.platform == "win32":
            expected = self.home / ".local/share/command1264-skills/idea-assessment"
        elif sys.platform == "darwin":
            expected = self.home / "Library/Application Support/command1264-skills/idea-assessment"
        else:
            expected = self.home / ".local/share/command1264-skills/idea-assessment"
        self.assertEqual(Path(result["output_root"]), expected)
        self.assertEqual(result["source"], "default")

    @unittest.skipIf(sys.platform in {"win32", "darwin"}, "XDG applies to Linux only")
    def test_linux_honors_xdg_data_home(self):
        self.env["XDG_DATA_HOME"] = str(self.root / "xdg")
        result = self.json_out("path")
        self.assertEqual(Path(result["output_root"]), self.root / "xdg/command1264-skills/idea-assessment")

    def test_config_absolute_output_root(self):
        target = self.root / "reports"
        self.write_config({"schema_version": 1, "output_root": str(target)})
        result = self.json_out("path")
        self.assertEqual(Path(result["output_root"]), target)
        self.assertEqual(result["source"], "config")

    def test_config_relative_output_root_resolves_against_config_folder(self):
        config = self.write_config({"schema_version": 1, "output_root": "../ideas"})
        result = self.json_out("path")
        self.assertEqual(Path(result["output_root"]), (config.parent / "../ideas").resolve())

    def test_output_dir_argument_overrides_config_and_resolves_against_cwd(self):
        self.write_config({"schema_version": 1, "output_root": str(self.root / "ignored")})
        work = self.root / "work"
        work.mkdir()
        result = self.json_out("path", "--output-dir", "out", cwd=work)
        self.assertEqual(Path(result["output_root"]), work / "out")
        self.assertEqual(result["source"], "argument")

    def test_invalid_config_fails_with_actionable_error(self):
        self.write_config({"schema_version": 1, "output_root": 5})
        result = self.run_cli("path", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("output_root", result.stderr)

    def test_init_creates_dated_folder_with_safe_slug(self):
        result = self.json_out("init", "--slug", "Minecraft 伺服器/管理器!", "--date", "2026-11-28",
                               "--output-dir", str(self.root / "out"))
        folder = Path(result["folder"])
        self.assertTrue(folder.is_dir())
        self.assertEqual(folder.parent, self.root / "out")
        self.assertEqual(folder.name, "2026-11-28-minecraft-伺服器-管理器")

    def test_init_refuses_existing_folder(self):
        args = ("init", "--slug", "demo", "--date", "2026-11-28", "--output-dir", str(self.root / "out"))
        self.json_out(*args)
        result = self.run_cli(*args, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("已存在", result.stderr)

    def write_assessment(self, mutate=None, name="assessment.json"):
        data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        if mutate:
            mutate(data)
        source = self.root / name
        source.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return source, data

    def render(self, source, check=True):
        return self.run_cli("render", str(source), "--output-dir", str(self.root / "r"), check=check)

    def test_render_writes_chart_with_proportional_bars(self):
        result = self.json_out("render", str(EXAMPLE), "--output-dir", str(self.root / "r"))
        tree = ET.parse(result["svg"])
        ns = {"s": "http://www.w3.org/2000/svg"}
        bars = tree.getroot().findall(".//s:rect[@class='bar']", ns)
        example = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        self.assertEqual(len(bars), len(example["dimensions"]))
        full = float(tree.getroot().find(".//s:rect[@class='track']", ns).get("width"))
        for bar, dimension in zip(bars, example["dimensions"]):
            self.assertAlmostEqual(float(bar.get("width")), full * dimension["score"] / 5, places=1)

    def test_render_writes_self_contained_html_report(self):
        result = self.json_out("render", str(EXAMPLE), "--output-dir", str(self.root / "r"))
        html = Path(result["html"]).read_text(encoding="utf-8")
        example = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        self.assertTrue(html.startswith("<!doctype html>"))
        self.assertIn("先驗證", html)
        self.assertIn(example["verdict_reason"].split(" [1]")[0], html)
        for dimension in example["dimensions"]:
            self.assertIn(dimension["label"], html)
        for competitor in example["competitors"]:
            self.assertIn(competitor["name"], html)
        for source in example["sources"]:
            self.assertIn(f'id="src-{source["id"]}"', html)
            self.assertIn(f'href="{source["url"]}"', html)
        self.assertIn('href="#src-1"', html)
        self.assertNotIn("<script", html)
        self.assertNotRegex(html, r'(?:src|href)="//|<link[^>]+href="http|@import')
        self.assertIn("prefers-color-scheme: dark", html)

    def test_render_writes_markdown_fallback_with_text_bars(self):
        result = self.json_out("render", str(EXAMPLE), "--output-dir", str(self.root / "r"))
        text = Path(result["markdown"]).read_text(encoding="utf-8")
        example = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        self.assertIn("█", text)
        self.assertIn("不推薦", text)
        for heading in ("競品與替代做法", "AI 替代風險", "最便宜的驗證實驗", "放棄條件", "來源"):
            self.assertIn(heading, text)
        for source in example["sources"]:
            self.assertIn(source["url"], text)

    def test_render_escapes_markup_everywhere(self):
        def mutate(d):
            d["dimensions"][0]["label"] = "<script>x</script> & y"
            d["competitors"][0]["name"] = "<img src=x onerror=alert(1)>"
            d["verdict_reason"] = "<b>bold</b>"
        source, _ = self.write_assessment(mutate)
        result = self.json_out("render", str(source), "--output-dir", str(self.root / "r"))
        html = Path(result["html"]).read_text(encoding="utf-8")
        svg = Path(result["svg"]).read_text(encoding="utf-8")
        for text in (html, svg):
            for injected in ("<script>x", "<img src=x", "<b>bold"):
                self.assertNotIn(injected, text)
        ET.fromstring(svg)

    def test_render_rejects_invalid_assessments_without_writing(self):
        cases = (
            (lambda d: d["dimensions"][0].update(score=6), "score"),
            (lambda d: d.update(extra=1), "extra"),
            (lambda d: d.update(verdict="maybe"), "verdict"),
            (lambda d: d["dimensions"][0].update(confidence="sure"), "confidence"),
            (lambda d: d["sources"][0].update(url="javascript:alert(1)"), "url"),
            (lambda d: d["competitors"][0].update(url="file:///etc/passwd"), "url"),
            (lambda d: d.update(verdict_reason="見 [99]"), "[99]"),
            (lambda d: d["sources"].append(dict(d["sources"][0])), "id"),
            (lambda d: d.update(date="2026-13-40"), "date"),
            (lambda d: d["ai_risk"].pop("platform"), "platform"),
        )
        for mutate, needle in cases:
            source, _ = self.write_assessment(mutate)
            result = self.render(source, check=False)
            self.assertNotEqual(result.returncode, 0, needle)
            self.assertIn(needle, result.stderr, needle)
            self.assertFalse((self.root / "r").exists(), needle)


if __name__ == "__main__":
    unittest.main()
