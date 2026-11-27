#!/usr/bin/env python3
"""idea-assessment helper: resolve the private report folder and render score charts.

Standard library only. stdout carries one JSON object per command; errors go to stderr
as JSON and exit with a non-zero code.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import sys
from typing import Any
from xml.sax.saxutils import escape

SCHEMA_VERSION = 1
APP_DIR = Path("command1264-skills") / "idea-assessment"
CONFIG_ENV = "IDEA_ASSESSMENT_CONFIG"
VERDICTS = {"pursue": "值得做", "validate-first": "先驗證", "pass": "不建議"}
CONFIDENCE = {"high": "高", "medium": "中", "low": "低"}
KEY = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
COLORS = ("#c0392b", "#c0392b", "#e67e22", "#d4ac0d", "#58a55c", "#1e8449")


class CliError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def home() -> Path:
    return Path.home()


def default_data_root() -> Path:
    if sys.platform == "win32":
        return home() / ".local" / "share" / APP_DIR
    if sys.platform == "darwin":
        return home() / "Library" / "Application Support" / APP_DIR
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg and Path(xdg).is_absolute() else home() / ".local" / "share"
    return base / APP_DIR


def default_config_path() -> Path:
    if sys.platform == "win32":
        return home() / ".config" / APP_DIR / "config.json"
    if sys.platform == "darwin":
        return home() / "Library" / "Application Support" / APP_DIR / "config.json"
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg and Path(xdg).is_absolute() else home() / ".config"
    return base / APP_DIR / "config.json"


def read_json(path: Path, what: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise CliError("FILE_NOT_FOUND", f"找不到{what}：{path}") from None
    except (OSError, UnicodeError) as exc:
        raise CliError("FILE_UNREADABLE", f"無法讀取{what} {path}：{exc}") from None
    except json.JSONDecodeError as exc:
        raise CliError("INVALID_JSON", f"{what}不是有效 JSON（{path} 第 {exc.lineno} 行）") from None


def resolve_output_root(output_dir: str | None) -> dict[str, Any]:
    """Pick the report root: --output-dir, then config output_root, then the platform default."""
    override = os.environ.get(CONFIG_ENV)
    config_path = Path(override).expanduser() if override else default_config_path()
    config_exists = config_path.is_file()
    if override and not config_exists:
        raise CliError("CONFIG_NOT_FOUND", f"{CONFIG_ENV} 指向的設定檔不存在：{config_path}")
    result = {"schema_version": SCHEMA_VERSION, "config_path": str(config_path), "config_exists": config_exists}
    if output_dir:
        root, source = Path(output_dir).expanduser(), "argument"
        root = root if root.is_absolute() else Path.cwd() / root
    elif config_exists:
        config = read_json(config_path, "設定檔")
        if not isinstance(config, dict) or config.get("schema_version") != SCHEMA_VERSION:
            raise CliError("INVALID_CONFIG", f"設定檔需為物件且 schema_version 為 {SCHEMA_VERSION}：{config_path}")
        unknown = sorted(set(config) - {"schema_version", "output_root"})
        if unknown:
            raise CliError("INVALID_CONFIG", f"設定檔有未知欄位 {unknown}：{config_path}")
        value = config.get("output_root")
        if value is None:
            root, source = default_data_root(), "default"
        elif not isinstance(value, str) or not value.strip():
            raise CliError("INVALID_CONFIG", f"output_root 必須是非空字串：{config_path}")
        else:
            root, source = Path(value).expanduser(), "config"
            root = root if root.is_absolute() else (config_path.parent / root).resolve()
    else:
        root, source = default_data_root(), "default"
    result.update(output_root=str(root), source=source)
    return result


def slugify(text: str) -> str:
    slug = re.sub(r"[\W_]+", "-", text.strip().lower()).strip("-")[:60].strip("-")
    if not slug:
        raise CliError("INVALID_SLUG", "slug 去除符號後是空的，請改用含文字或數字的名稱")
    return slug


def cmd_path(args: argparse.Namespace) -> dict[str, Any]:
    return resolve_output_root(args.output_dir)


def cmd_init(args: argparse.Namespace) -> dict[str, Any]:
    resolved = resolve_output_root(args.output_dir)
    try:
        date = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    except ValueError:
        raise CliError("INVALID_DATE", f"--date 必須是 YYYY-MM-DD：{args.date}") from None
    folder = Path(resolved["output_root"]) / f"{date.isoformat()}-{slugify(args.slug)}"
    if folder.exists():
        raise CliError("FOLDER_EXISTS", f"資料夾已存在，請換 slug 或日期：{folder}")
    folder.mkdir(parents=True)
    return {**resolved, "folder": str(folder)}


KINDS = {"open": "開源", "closed": "閉源", "platform": "平台內建", "workaround": "替代做法"}
STATUSES = {"active": "活躍", "stale": "停滯", "shut-down": "已收掉", "unknown": "未確認"}
CITATION = re.compile(r"\[(\d+)\]")
TOP_KEYS = {
    "schema_version", "idea", "date", "verdict", "verdict_reason", "scale_max", "axis_low_label",
    "axis_high_label", "dimensions", "context", "competitors", "demand", "trends", "ai_risk",
    "considerations", "experiment", "kill_criteria", "research_gaps", "sources",
}


class Checker:
    """Collects every problem in one pass so the agent can fix the JSON in one edit."""

    def __init__(self) -> None:
        self.errors: list[str] = []
        self.texts: list[tuple[str, str]] = []

    def fail(self, where: str, message: str) -> None:
        self.errors.append(f"{where}: {message}")

    def obj(self, value: Any, where: str, required: set[str], optional: frozenset[str] = frozenset()) -> bool:
        if not isinstance(value, dict):
            self.fail(where, "必須是物件")
            return False
        for key in sorted(set(value) - required - optional):
            self.fail(f"{where}.{key}", "未知欄位")
        for key in sorted(required - set(value)):
            self.fail(f"{where}.{key}", "缺少必要欄位")
        return True

    def text(self, value: Any, where: str, max_len: int = 1000) -> None:
        if not isinstance(value, str) or not value.strip():
            self.fail(where, "必須是非空字串")
        elif len(value) > max_len:
            self.fail(where, f"超過 {max_len} 字")
        else:
            self.texts.append((where, value))

    def array(self, value: Any, where: str, minimum: int = 1) -> list[Any]:
        if not isinstance(value, list) or len(value) < minimum:
            self.fail(where, f"必須是至少 {minimum} 項的陣列")
            return []
        return value

    def texts_array(self, value: Any, where: str, minimum: int = 1) -> None:
        for index, item in enumerate(self.array(value, where, minimum)):
            self.text(item, f"{where}[{index}]")

    def url(self, value: Any, where: str) -> None:
        if not isinstance(value, str) or not re.match(r"^https?://[^\s\"'<>]+$", value):
            self.fail(where, "url 必須是 http:// 或 https:// 開頭的網址")

    def date(self, value: Any, where: str) -> None:
        try:
            dt.date.fromisoformat(value)
        except (TypeError, ValueError):
            self.fail(where, "date 必須是有效的 YYYY-MM-DD")


def validate_assessment(data: Any) -> list[str]:
    c = Checker()
    optional = frozenset({"axis_low_label", "axis_high_label"})
    if not c.obj(data, "$", TOP_KEYS - optional, optional):
        return c.errors
    if data.get("schema_version") != SCHEMA_VERSION:
        c.fail("$.schema_version", f"必須是 {SCHEMA_VERSION}")
    c.text(data.get("idea"), "$.idea", 120)
    c.date(data.get("date"), "$.date")
    if data.get("verdict") not in VERDICTS:
        c.fail("$.verdict", f"verdict 必須是 {sorted(VERDICTS)} 之一")
    c.text(data.get("verdict_reason"), "$.verdict_reason", 300)
    if data.get("scale_max") != 5:
        c.fail("$.scale_max", "必須是 5")
    for key in sorted(optional & set(data)):
        c.text(data[key], f"$.{key}", 20)
    seen: set[str] = set()
    for index, item in enumerate(c.array(data.get("dimensions"), "$.dimensions")):
        where = f"$.dimensions[{index}]"
        if not c.obj(item, where, {"key", "label", "score", "confidence", "summary"}):
            continue
        key = item.get("key")
        if not isinstance(key, str) or not KEY.match(key):
            c.fail(f"{where}.key", "必須是 kebab-case 字串")
        elif key in seen:
            c.fail(f"{where}.key", f"重複的 {key}")
        seen.add(key if isinstance(key, str) else "")
        c.text(item.get("label"), f"{where}.label", 40)
        c.text(item.get("summary"), f"{where}.summary", 200)
        score = item.get("score")
        if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 5:
            c.fail(f"{where}.score", "score 必須是 0 到 5 的整數")
        if item.get("confidence") not in CONFIDENCE:
            c.fail(f"{where}.confidence", f"confidence 必須是 {sorted(CONFIDENCE)} 之一")
    for index, item in enumerate(c.array(data.get("context"), "$.context")):
        where = f"$.context[{index}]"
        if c.obj(item, where, {"label", "value", "assumed"}):
            c.text(item.get("label"), f"{where}.label", 40)
            c.text(item.get("value"), f"{where}.value", 500)
            if not isinstance(item.get("assumed"), bool):
                c.fail(f"{where}.assumed", "必須是 true 或 false")
    for index, item in enumerate(c.array(data.get("competitors"), "$.competitors")):
        where = f"$.competitors[{index}]"
        if not c.obj(item, where, {"name", "kind", "status", "price", "difference", "complaints"}, frozenset({"url"})):
            continue
        c.text(item.get("name"), f"{where}.name", 120)
        if "url" in item:
            c.url(item["url"], f"{where}.url")
        if item.get("kind") not in KINDS:
            c.fail(f"{where}.kind", f"kind 必須是 {sorted(KINDS)} 之一")
        if item.get("status") not in STATUSES:
            c.fail(f"{where}.status", f"status 必須是 {sorted(STATUSES)} 之一")
        for key in ("price", "difference", "complaints"):
            c.text(item.get(key), f"{where}.{key}", 300)
    c.texts_array(data.get("demand"), "$.demand")
    c.texts_array(data.get("trends"), "$.trends")
    risk = data.get("ai_risk")
    if c.obj(risk, "$.ai_risk", {"general_agent", "platform", "value"}):
        for key in ("general_agent", "platform", "value"):
            if key in risk:
                c.text(risk[key], f"$.ai_risk.{key}", 600)
    for index, item in enumerate(c.array(data.get("considerations"), "$.considerations")):
        where = f"$.considerations[{index}]"
        if c.obj(item, where, {"topic", "note"}):
            c.text(item.get("topic"), f"{where}.topic", 40)
            c.text(item.get("note"), f"{where}.note", 500)
    experiment = data.get("experiment")
    if c.obj(experiment, "$.experiment", {"hypothesis", "method", "duration", "cost", "success", "failure"}):
        for key in ("hypothesis", "duration", "cost", "success", "failure"):
            if key in experiment:
                c.text(experiment[key], f"$.experiment.{key}", 400)
        c.texts_array(experiment.get("method"), "$.experiment.method")
    c.texts_array(data.get("kill_criteria"), "$.kill_criteria")
    for index, item in enumerate(c.array(data.get("research_gaps"), "$.research_gaps", 0)):
        where = f"$.research_gaps[{index}]"
        if c.obj(item, where, {"category", "reason"}):
            c.text(item.get("category"), f"{where}.category", 40)
            c.text(item.get("reason"), f"{where}.reason", 300)
    ids: set[int] = set()
    for index, item in enumerate(c.array(data.get("sources"), "$.sources")):
        where = f"$.sources[{index}]"
        if not c.obj(item, where, {"id", "title", "url", "accessed"}):
            continue
        source_id = item.get("id")
        if isinstance(source_id, bool) or not isinstance(source_id, int) or source_id < 1:
            c.fail(f"{where}.id", "id 必須是正整數")
        elif source_id in ids:
            c.fail(f"{where}.id", f"重複的 id {source_id}")
        else:
            ids.add(source_id)
        c.text(item.get("title"), f"{where}.title", 200)
        c.url(item.get("url"), f"{where}.url")
        c.date(item.get("accessed"), f"{where}.accessed")
    for where, value in c.texts:
        for ref in CITATION.findall(value):
            if int(ref) not in ids:
                c.fail(where, f"引用 [{ref}] 不在 sources 裡")
    return c.errors


def render_svg(data: dict[str, Any]) -> str:
    label_w, track_w, row_h, top, pad = 210, 420, 40, 64, 16
    width = pad + label_w + track_w + 90 + pad
    rows = data["dimensions"]
    height = top + row_h * len(rows) + 44
    low = data.get("axis_low_label", "不推薦")
    high = data.get("axis_high_label", "推薦")
    x0 = pad + label_w
    title = f"{data['idea']}：{VERDICTS[data['verdict']]}"
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" class="chart" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="system-ui, sans-serif" role="img">',
        f"<title>{escape(title)}</title>",
        f'<rect class="bg" width="{width}" height="{height}" fill="#ffffff"/>',
        f'<text class="label" x="{pad}" y="30" font-size="18" font-weight="600" fill="#1f2328">{escape(title)}</text>',
    ]
    for index, item in enumerate(rows):
        y = top + index * row_h
        bar_w = track_w * item["score"] / data["scale_max"]
        parts += [
            f'<text class="label" x="{x0 - 12}" y="{y + 19}" font-size="14" text-anchor="end" fill="#1f2328">{escape(item["label"])}</text>',
            f'<rect class="track" x="{x0}" y="{y + 4}" width="{track_w}" height="22" rx="4" fill="#eaeef2"/>',
            f'<rect class="bar" x="{x0}" y="{y + 4}" width="{bar_w:.1f}" height="22" rx="4" fill="{COLORS[item["score"]]}"/>',
            f'<text class="meta" x="{x0 + track_w + 10}" y="{y + 20}" font-size="13" fill="#57606a">'
            f'{item["score"]}/{data["scale_max"]}・信心{CONFIDENCE[item["confidence"]]}</text>',
        ]
    axis_y = top + row_h * len(rows) + 18
    parts += [
        f'<text class="meta" x="{x0}" y="{axis_y}" font-size="12" fill="#57606a">← {escape(low)}</text>',
        f'<text class="meta" x="{x0 + track_w}" y="{axis_y}" font-size="12" text-anchor="end" fill="#57606a">{escape(high)} →</text>',
        "</svg>",
    ]
    return "\n".join(parts) + "\n"


def strongest_and_weakest(data: dict[str, Any]) -> tuple[list[str], list[str]]:
    ordered = sorted(data["dimensions"], key=lambda item: item["score"])
    return [item["label"] for item in ordered[::-1][:2]], [item["label"] for item in ordered[:2]]


def html_text(value: str) -> str:
    return CITATION.sub(r'<a class="cite" href="#src-\1">[\1]</a>', escape(value))


HTML_STYLE = """
:root{--bg:#f6f8fa;--card:#ffffff;--fg:#1f2328;--muted:#57606a;--line:#d0d7de;--track:#eaeef2;
--pursue:#1e8449;--validate-first:#b7791f;--pass:#c0392b;--link:#0969da}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#0d1117;--card:#161b22;--fg:#e6edf3;
--muted:#9198a1;--line:#30363d;--track:#262c36;--pursue:#3fb950;--validate-first:#d29922;--pass:#f85149;--link:#4493f8}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.6 system-ui,-apple-system,"Segoe UI","Noto Sans TC",sans-serif}
main{max-width:960px;margin:0 auto;padding:24px 16px 48px}
header h1{font-size:1.6rem;line-height:1.3;margin:0 0 4px}
header p{margin:0;color:var(--muted)}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:20px;margin-top:16px}
.verdict{border-left:6px solid var(--v)}
.verdict .label{font-size:1.4rem;font-weight:700;color:var(--v)}
.verdict p{margin:8px 0 0}
.extremes{display:flex;flex-wrap:wrap;gap:8px 24px;margin-top:12px;color:var(--muted)}
.extremes b{color:var(--fg);font-weight:600}
.bars{display:grid;gap:10px}
.row{display:grid;grid-template-columns:minmax(6em,max-content) 1fr 7.5em;gap:12px;align-items:center}
.row .track{height:18px;border-radius:4px;background:var(--track);overflow:hidden}
.row .bar{display:block;height:100%;border-radius:4px}
.row .val{color:var(--muted);font-size:.9rem;white-space:nowrap}
.axis{display:flex;justify-content:space-between;color:var(--muted);font-size:.85rem;margin-top:4px}
@media (max-width:560px){.row{grid-template-columns:1fr auto;gap:4px 12px}.row .dim{grid-column:1/-1}.axis{margin-left:0}}
@media (min-width:561px){.axis{margin-left:calc(6em + 12px);margin-right:calc(7.5em + 12px)}}
h2{font-size:1.15rem;margin:0}
details>summary{cursor:pointer;list-style:none;display:flex;justify-content:space-between;align-items:center}
details>summary::-webkit-details-marker{display:none}
details>summary::after{content:"＋";color:var(--muted)}
details[open]>summary::after{content:"－"}
details[open]>summary{margin-bottom:12px}
.table-wrap{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:.95rem}
th,td{border-bottom:1px solid var(--line);padding:8px;text-align:left;vertical-align:top}
th{color:var(--muted);font-weight:600;white-space:nowrap}
a{color:var(--link)}
.cite{font-size:.8em;text-decoration:none}
.assumed{color:var(--muted);font-size:.85em}
ol,ul{margin:0;padding-left:1.4em}
dl{display:grid;grid-template-columns:max-content 1fr;gap:6px 16px;margin:0}
dt{color:var(--muted)}dd{margin:0}
.muted{color:var(--muted)}
"""


def html_section(title: str, body: str, open_: bool) -> str:
    flag = " open" if open_ else ""
    return f'<details class="card"{flag}><summary><h2>{escape(title)}</h2></summary>{body}</details>'


def html_bars(data: dict[str, Any]) -> str:
    rows = "".join(
        f'<div class="row"><span class="dim">{escape(d["label"])}</span>'
        f'<span class="track"><span class="bar" style="width:{100 * d["score"] / data["scale_max"]:.0f}%;'
        f'background:{COLORS[d["score"]]}"></span></span>'
        f'<span class="val">{d["score"]}/{data["scale_max"]}・信心{CONFIDENCE[d["confidence"]]}</span></div>'
        for d in data["dimensions"]
    )
    low = escape(data.get("axis_low_label", "不推薦"))
    high = escape(data.get("axis_high_label", "推薦"))
    return (f'<div class="bars" role="img" aria-label="評分長條圖">{rows}</div>'
            f'<div class="axis"><span>← {low}</span><span>{high} →</span></div>')


def render_html(data: dict[str, Any]) -> str:
    verdict = data["verdict"]
    strong, weak = strongest_and_weakest(data)
    dims = "".join(
        f"<tr><td>{escape(d['label'])}</td><td>{d['score']}/{data['scale_max']}</td>"
        f"<td>{CONFIDENCE[d['confidence']]}</td><td>{html_text(d['summary'])}</td></tr>"
        for d in data["dimensions"]
    )
    context = "".join(
        f"<dt>{escape(c['label'])}</dt><dd>{html_text(c['value'])}"
        + (' <span class="assumed">（假設）</span>' if c["assumed"] else "") + "</dd>"
        for c in data["context"]
    )
    competitors = "".join(
        "<tr><td>"
        + (f'<a href="{escape(c["url"], {chr(34): "&quot;"})}" rel="noreferrer">{escape(c["name"])}</a>' if "url" in c else escape(c["name"]))
        + f"</td><td>{KINDS[c['kind']]}</td><td>{STATUSES[c['status']]}</td><td>{html_text(c['price'])}</td>"
        f"<td>{html_text(c['difference'])}</td><td>{html_text(c['complaints'])}</td></tr>"
        for c in data["competitors"]
    )
    bullets = lambda items: "<ul>" + "".join(f"<li>{html_text(i)}</li>" for i in items) + "</ul>"
    risk = data["ai_risk"]
    exp = data["experiment"]
    gaps = data["research_gaps"]
    sources = "".join(
        f'<li id="src-{s["id"]}" value="{s["id"]}">{escape(s["title"])}：'
        f'<a href="{escape(s["url"], {chr(34): "&quot;"})}" rel="noreferrer">{escape(s["url"])}</a>'
        f'<span class="muted">（查閱 {s["accessed"]}）</span></li>'
        for s in sorted(data["sources"], key=lambda s: s["id"])
    )
    sections = [
        html_section("評分依據", f'<div class="table-wrap"><table><thead><tr><th>面向</th><th>分數</th><th>信心</th>'
                     f"<th>依據</th></tr></thead><tbody>{dims}</tbody></table></div>", False),
        html_section("想法與假設", f"<dl>{context}</dl>", True),
        html_section("競品與替代做法", '<div class="table-wrap"><table><thead><tr><th>名稱</th><th>類型</th><th>狀態</th>'
                     f"<th>價格</th><th>差異</th><th>使用者抱怨</th></tr></thead><tbody>{competitors}</tbody></table></div>", True),
        html_section("AI 替代風險", f"<dl><dt>通用 Agent</dt><dd>{html_text(risk['general_agent'])}</dd>"
                     f"<dt>平台內建</dt><dd>{html_text(risk['platform'])}</dd>"
                     f"<dt>價值所在</dt><dd>{html_text(risk['value'])}</dd></dl>", True),
        html_section("最便宜的驗證實驗", f"<dl><dt>要驗證</dt><dd>{html_text(exp['hypothesis'])}</dd>"
                     f"<dt>做法</dt><dd><ol>{''.join(f'<li>{html_text(m)}</li>' for m in exp['method'])}</ol></dd>"
                     f"<dt>時間</dt><dd>{html_text(exp['duration'])}</dd><dt>成本</dt><dd>{html_text(exp['cost'])}</dd>"
                     f"<dt>成功</dt><dd>{html_text(exp['success'])}</dd><dt>失敗</dt><dd>{html_text(exp['failure'])}</dd></dl>", True),
        html_section("放棄條件", bullets(data["kill_criteria"]), True),
        html_section("需求與趨勢", f"<h3>需求</h3>{bullets(data['demand'])}<h3>趨勢</h3>{bullets(data['trends'])}", False),
        html_section("其他考量", "<dl>" + "".join(
            f"<dt>{escape(i['topic'])}</dt><dd>{html_text(i['note'])}</dd>" for i in data["considerations"]) + "</dl>", False),
        html_section("調查缺口", "<dl>" + "".join(
            f"<dt>{escape(g['category'])}</dt><dd>{html_text(g['reason'])}</dd>" for g in gaps) + "</dl>"
            if gaps else '<p class="muted">每個來源類別都已查過。</p>', False),
        html_section("來源", f"<ol>{sources}</ol>", False),
    ]
    title = escape(data["idea"])
    return (
        "<!doctype html>\n"
        f'<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{title}</title><style>{HTML_STYLE}</style></head><body><main>"
        f"<header><h1>{title}</h1><p>想法評估・{data['date']}</p></header>"
        f'<section class="card verdict" style="--v:var(--{verdict})"><div class="label">{VERDICTS[verdict]}</div>'
        f"<p>{html_text(data['verdict_reason'])}</p>"
        f'<div class="extremes"><span>最強　<b>{escape("、".join(strong))}</b></span>'
        f'<span>最弱　<b>{escape("、".join(weak))}</b></span></div></section>'
        f'<section class="card">{html_bars(data)}</section>'
        + "".join(sections)
        + "</main></body></html>\n"
    )


def md_cell(text: str) -> str:
    return re.sub(r"([\\`*_<>|!])", r"\\\1", " ".join(text.split()))


def render_markdown(data: dict[str, Any]) -> str:
    low = data.get("axis_low_label", "不推薦")
    high = data.get("axis_high_label", "推薦")
    strong, weak = strongest_and_weakest(data)
    out = [
        f"# {md_cell(data['idea'])}：{VERDICTS[data['verdict']]}", "",
        f"評估日期：{data['date']}", "",
        md_cell(data["verdict_reason"]), "",
        f"最強：{md_cell('、'.join(strong))}　最弱：{md_cell('、'.join(weak))}", "",
        "## 評分", "", "![評分長條圖](chart.svg)", "",
        f"長條由左到右為 {md_cell(low)} → {md_cell(high)}（0–{data['scale_max']} 分）。", "",
        "| 面向 | 長條 | 分數 | 信心 | 依據 |", "| --- | --- | --- | --- | --- |",
    ]
    for d in data["dimensions"]:
        bar = "█" * (d["score"] * 2) + "░" * ((data["scale_max"] - d["score"]) * 2)
        out.append(f"| {md_cell(d['label'])} | `{bar}` | {d['score']}/{data['scale_max']} | "
                   f"{CONFIDENCE[d['confidence']]} | {md_cell(d['summary'])} |")
    out += ["", "## 想法與假設", ""]
    out += [f"- {md_cell(c['label'])}：{md_cell(c['value'])}" + ("（假設）" if c["assumed"] else "") for c in data["context"]]
    out += ["", "## 競品與替代做法", "", "| 名稱 | 類型 | 狀態 | 價格 | 差異 | 使用者抱怨 |", "| --- | --- | --- | --- | --- | --- |"]
    for c in data["competitors"]:
        name = md_cell(c["name"]) + (f"（{c['url']}）" if "url" in c else "")
        out.append(f"| {name} | {KINDS[c['kind']]} | {STATUSES[c['status']]} | {md_cell(c['price'])} | "
                   f"{md_cell(c['difference'])} | {md_cell(c['complaints'])} |")
    risk, exp = data["ai_risk"], data["experiment"]
    out += ["", "## AI 替代風險", "", f"- 通用 Agent：{md_cell(risk['general_agent'])}",
            f"- 平台內建：{md_cell(risk['platform'])}", f"- 價值所在：{md_cell(risk['value'])}",
            "", "## 最便宜的驗證實驗", "", f"- 要驗證：{md_cell(exp['hypothesis'])}"]
    out += [f"- 做法 {i}：{md_cell(m)}" for i, m in enumerate(exp["method"], 1)]
    out += [f"- 時間：{md_cell(exp['duration'])}", f"- 成本：{md_cell(exp['cost'])}",
            f"- 成功：{md_cell(exp['success'])}", f"- 失敗：{md_cell(exp['failure'])}", "", "## 放棄條件", ""]
    out += [f"- {md_cell(k)}" for k in data["kill_criteria"]]
    out += ["", "## 需求與趨勢", ""] + [f"- 需求：{md_cell(t)}" for t in data["demand"]] + [f"- 趨勢：{md_cell(t)}" for t in data["trends"]]
    out += ["", "## 其他考量", ""] + [f"- {md_cell(i['topic'])}：{md_cell(i['note'])}" for i in data["considerations"]]
    out += ["", "## 調查缺口", ""] + ([f"- {md_cell(g['category'])}：{md_cell(g['reason'])}" for g in data["research_gaps"]] or ["- 每個來源類別都已查過。"])
    out += ["", "## 來源", ""] + [f"{s['id']}. {md_cell(s['title'])}：{s['url']}（查閱 {s['accessed']}）"
                                  for s in sorted(data["sources"], key=lambda s: s["id"])]
    return "\n".join(out) + "\n"


def cmd_render(args: argparse.Namespace) -> dict[str, Any]:
    source = Path(args.assessment).expanduser().resolve()
    data = read_json(source, "評估檔")
    errors = validate_assessment(data)
    if errors:
        raise CliError("INVALID_ASSESSMENT", "評估檔不符合 assessment-v1：" + "；".join(errors))
    out = Path(args.output_dir).expanduser().resolve() if args.output_dir else source.parent
    out.mkdir(parents=True, exist_ok=True)
    svg_text = render_svg(data)
    files = {"svg": out / "chart.svg", "html": out / "report.html", "markdown": out / "report.md"}
    files["svg"].write_text(svg_text, encoding="utf-8", newline="\n")
    files["html"].write_text(render_html(data), encoding="utf-8", newline="\n")
    files["markdown"].write_text(render_markdown(data), encoding="utf-8", newline="\n")
    return {"schema_version": SCHEMA_VERSION, **{key: str(path) for key, path in files.items()}}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="idea_assessment.py", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    path = sub.add_parser("path", help="顯示報告根目錄與其來源（離線）")
    path.add_argument("--output-dir", help="本次使用的報告根目錄；相對路徑以目前目錄為準")
    path.set_defaults(func=cmd_path)
    init = sub.add_parser("init", help="建立 <日期>-<slug> 報告資料夾")
    init.add_argument("--slug", required=True, help="想法的短名稱")
    init.add_argument("--date", help="YYYY-MM-DD，預設今天")
    init.add_argument("--output-dir", help="本次使用的報告根目錄；相對路徑以目前目錄為準")
    init.set_defaults(func=cmd_init)
    render = sub.add_parser("render", help="驗證 assessment.json 並產生 report.html、report.md 與 chart.svg")
    render.add_argument("assessment", help="assessment-v1 JSON 檔")
    render.add_argument("--output-dir", help="輸出資料夾，預設與 assessment.json 相同")
    render.set_defaults(func=cmd_render)
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    try:
        result = args.func(args)
    except CliError as exc:
        print(json.dumps({"error": {"code": exc.code, "message": str(exc)}}, ensure_ascii=False), file=sys.stderr)
        return 2
    except OSError as exc:
        print(json.dumps({"error": {"code": "OS_ERROR", "message": str(exc)}}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
