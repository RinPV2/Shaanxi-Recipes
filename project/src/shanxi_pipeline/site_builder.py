"""从 vault 生成 GitHub Pages 静态站(纯 HTML/CSS/JS,无外部依赖)。

站点直接以仓库根为发布目录:页图 `assets/pages/` 原地复用,不复制 53MB。
"""

from __future__ import annotations

import html
import json
import logging
import re
from pathlib import Path
from typing import Any

import yaml

LOGGER = logging.getLogger(__name__)

REPO_URL = "https://github.com/RinPV2/Shaanxi-Recipes"
SITE_BASE = "https://rinpv2.github.io/Shaanxi-Recipes"
SITE_TITLE = "陕西菜谱"
SITE_SUBTITLE = "1970 年代《陕西菜谱》全四册数字化"
FULL_PAGE_PREFIX = "【整页】"
BOOK_LABELS = {"sxcp-1": "第一册", "sxcp-2": "第二册", "sxcp-3": "第三册", "sxcp-4": "第四册"}
UNCATEGORIZED = "未分类"


def _book_label(book_id: str) -> str:
    return BOOK_LABELS.get(book_id, book_id)


def _esc(text: Any) -> str:
    return html.escape(str(text if text is not None else ""), quote=True)


def load_recipes(vault_root: Path) -> list[dict[str, Any]]:
    """读取 vault/recipes 下的笔记,解析 YAML frontmatter。"""
    recipes: list[dict[str, Any]] = []
    for path in sorted((vault_root / "recipes").glob("*.md")):
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---"):
            continue
        _, _, rest = text.partition("---\n")
        front, _, _body = rest.partition("\n---")
        try:
            data = yaml.safe_load(front) or {}
        except yaml.YAMLError:
            LOGGER.warning("跳过无法解析的笔记: %s", path.name)
            continue
        data["slug"] = path.stem
        recipes.append(data)
    return recipes


def build_category_lookup(anchor_map: dict[str, Any]) -> dict[str, list[tuple[int, str]]]:
    """每册按页码排序的 (起始页, 分类) 列表——分类沿用最近的前置锚点。"""
    lookup: dict[str, list[tuple[int, str]]] = {}
    for book_id, pages in anchor_map.items():
        points: dict[int, str] = {}
        for entries in pages.values():
            for entry in entries:
                category = (entry.get("category") or "").replace(FULL_PAGE_PREFIX, "").strip()
                page = entry.get("local_page")
                if category and isinstance(page, int):
                    # 同页多条目时保留首次出现的分类
                    points.setdefault(page, category)
        lookup[book_id] = sorted(points.items())
    return lookup


def category_for(lookup: dict[str, list[tuple[int, str]]], book_id: str, page: int | None) -> str:
    points = lookup.get(book_id) or []
    if not points or page is None:
        return UNCATEGORIZED
    current = UNCATEGORIZED
    for start, category in points:
        if start <= page:
            current = category
        else:
            break
    return current


def _first_page(recipe: dict[str, Any]) -> int | None:
    pages = recipe.get("local_pages") or []
    return pages[0] if pages else None


def _page_range(pages: list[int]) -> str:
    if not pages:
        return ""
    if len(pages) == 1:
        return f"第 {pages[0]} 页"
    return f"第 {pages[0]}–{pages[-1]} 页"


def _issue_url(recipe: dict[str, Any], page_url: str) -> str:
    from urllib.parse import quote

    title = f"纠错：{recipe.get('title', '')}（{_book_label(recipe.get('book_id', ''))} {_page_range(recipe.get('local_pages') or [])}）"
    body = (
        f"**菜谱**：{recipe.get('title', '')}\n"
        f"**出处**：{_book_label(recipe.get('book_id', ''))} {_page_range(recipe.get('local_pages') or [])}\n"
        f"**页面**：{page_url}\n\n"
        "**问题描述**（哪一句、应该是什么、依据原书页图的哪个位置）：\n\n"
    )
    return f"{REPO_URL}/issues/new?title={quote(title)}&body={quote(body)}"


# ---------------------------------------------------------------- 渲染

def _layout(title: str, body: str, *, depth: int, extra_head: str = "") -> str:
    prefix = "../" * depth
    return f"""<!DOCTYPE html>
<html lang="zh-Hans">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)}</title>
<link rel="stylesheet" href="{prefix}site/style.css">
{extra_head}
</head>
<body>
<header class="topbar">
  <a class="brand" href="{prefix}index.html">{SITE_TITLE}<span class="brand-sub">{SITE_SUBTITLE}</span></a>
  <nav><a href="{REPO_URL}" rel="noopener">GitHub</a></nav>
</header>
{body}
<footer class="footer">
  <p>《陕西菜谱》(全四册)，陕西省副食服务公司、西安市饮食公司编写，1970 年代内部发行。本站为非营利数字化整理。</p>
  <p>整理内容 CC BY 4.0 · 站点代码 MIT · <a href="{REPO_URL}" rel="noopener">项目仓库</a></p>
</footer>
</body>
</html>
"""


def render_recipe_page(recipe: dict[str, Any], category: str, site_base: str) -> str:
    title = recipe.get("title") or recipe.get("slug", "")
    book_id = recipe.get("book_id", "")
    pages: list[int] = recipe.get("local_pages") or []
    slug = recipe["slug"]
    page_url = f"{site_base}/recipes/{slug}.html" if site_base else f"recipes/{slug}.html"

    def section(heading: str, items: list[str], cls: str = "") -> str:
        rows = [i for i in (items or []) if str(i).strip()]
        if not rows:
            return ""
        lis = "\n".join(f"<li>{_esc(row)}</li>" for row in rows)
        return f'<section class="block {cls}"><h2>{heading}</h2><ul>{lis}</ul></section>'

    images = "\n".join(
        f'<figure><a href="../assets/pages/{_esc(book_id)}/p{page:04d}.webp" target="_blank" rel="noopener">'
        f'<img loading="lazy" src="../assets/pages/{_esc(book_id)}/p{page:04d}.webp" '
        f'alt="{_esc(title)} 原书第 {page} 页"></a>'
        f"<figcaption>原书 {_book_label(book_id)} 第 {page} 页</figcaption></figure>"
        for page in pages
    )

    aliases = recipe.get("aliases") or []
    alias_html = (
        f'<p class="aliases">又作：{_esc("、".join(str(a) for a in aliases))}</p>' if aliases else ""
    )
    flag = ""
    if recipe.get("review_needed"):
        flag = '<p class="warn">此条 OCR 置信度较低，欢迎对照原书页图纠错。</p>'

    body = f"""
<main class="recipe">
  <p class="crumbs"><a href="../index.html">全部菜谱</a> › <a href="../index.html?book={_esc(book_id)}">{_book_label(book_id)}</a> › {_esc(category)}</p>
  <h1>{_esc(title)}</h1>
  {alias_html}
  <p class="meta">{_book_label(book_id)} · {_esc(_page_range(pages))} · {_esc(category)}</p>
  {flag}
  <div class="cols">
    <div class="text">
      {section("食材", recipe.get("ingredients"))}
      {section("调料", recipe.get("seasonings"))}
      {section("做法", recipe.get("steps"), "steps")}
      {section("特点", recipe.get("tips"))}
      <p class="report"><a class="btn" href="{_esc(_issue_url(recipe, page_url))}" target="_blank" rel="noopener">发现错误？提交纠错</a></p>
    </div>
    <aside class="scans">
      <h2>原书页图</h2>
      {images}
    </aside>
  </div>
</main>
"""
    return _layout(f"{title} · {SITE_TITLE}", body, depth=1)


def render_index_page(recipes: list[dict[str, Any]], categories: list[str]) -> str:
    book_chips = "".join(
        f'<button class="chip" data-filter="book" data-value="{bid}">{_book_label(bid)}</button>'
        for bid in sorted(BOOK_LABELS)
    )
    cat_chips = "".join(
        f'<button class="chip" data-filter="category" data-value="{_esc(c)}">{_esc(c)}</button>'
        for c in categories
    )
    body = f"""
<main class="home">
  <div class="hero">
    <h1>{SITE_TITLE}</h1>
    <p>{SITE_SUBTITLE}——共 <strong>{len(recipes)}</strong> 道菜，641 页原书扫描图逐页校对。</p>
  </div>
  <div class="controls">
    <input id="q" type="search" placeholder="搜索菜名、食材、做法…" autocomplete="off">
    <div class="chips">
      <button class="chip active" data-filter="book" data-value="">全部册</button>{book_chips}
    </div>
    <div class="chips">
      <button class="chip active" data-filter="category" data-value="">全部分类</button>{cat_chips}
    </div>
    <p class="count"><span id="count">{len(recipes)}</span> 道菜</p>
  </div>
  <ul id="list" class="grid"></ul>
  <p id="empty" class="empty" hidden>没有匹配的菜谱。</p>
</main>
"""
    return _layout(SITE_TITLE, body, depth=0, extra_head='<script defer src="site/data.js"></script>\n<script defer src="site/app.js"></script>')


STYLE_CSS = """
:root{
  --bg:#f6f1e7; --panel:#fffdf8; --ink:#2f2a24; --muted:#7b7168; --line:#e0d6c6;
  --accent:#9c3024; --accent-soft:#f2e2df;
}
@media (prefers-color-scheme:dark){
  :root{ --bg:#1b1815; --panel:#232019; --ink:#ece5da; --muted:#a1978a; --line:#3a342c;
    --accent:#e2705f; --accent-soft:#3a251f; }
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font-family:"PingFang SC","Microsoft YaHei","Hiragino Sans GB",system-ui,sans-serif;
  line-height:1.75;}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
.topbar{display:flex;justify-content:space-between;align-items:center;gap:1rem;
  padding:.9rem 1.4rem;border-bottom:1px solid var(--line);background:var(--panel);
  position:sticky;top:0;z-index:10}
.brand{font-size:1.15rem;font-weight:700;color:var(--ink);display:flex;flex-direction:column}
.brand-sub{font-size:.72rem;font-weight:400;color:var(--muted)}
main{max-width:1100px;margin:0 auto;padding:1.5rem 1.4rem 3rem}
.hero h1{font-size:2rem;margin:.2rem 0 .4rem;letter-spacing:.06em}
.hero p{color:var(--muted);margin:0 0 1.4rem}
.controls{position:sticky;top:57px;background:var(--bg);padding:.6rem 0 .8rem;z-index:5}
#q{width:100%;padding:.7rem .9rem;font-size:1rem;border:1px solid var(--line);
  border-radius:8px;background:var(--panel);color:var(--ink)}
.chips{display:flex;flex-wrap:wrap;gap:.4rem;margin-top:.6rem}
.chip{border:1px solid var(--line);background:var(--panel);color:var(--muted);
  padding:.28rem .7rem;border-radius:999px;font-size:.82rem;cursor:pointer}
.chip:hover{border-color:var(--accent)}
.chip.active{background:var(--accent);border-color:var(--accent);color:#fff}
.count{color:var(--muted);font-size:.85rem;margin:.7rem 0 0}
.grid{list-style:none;padding:0;margin:1rem 0 0;display:grid;gap:.7rem;
  grid-template-columns:repeat(auto-fill,minmax(210px,1fr))}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:.8rem .9rem}
.card:hover{border-color:var(--accent)}
.card a{display:block;color:var(--ink);font-weight:600}
.card .sub{color:var(--muted);font-size:.78rem;margin-top:.25rem}
.empty{color:var(--muted);text-align:center;padding:2rem}
.crumbs{color:var(--muted);font-size:.85rem;margin:0 0 .6rem}
.recipe h1{font-size:1.9rem;margin:.2rem 0 .3rem}
.aliases,.meta{color:var(--muted);font-size:.88rem;margin:.1rem 0}
.warn{background:var(--accent-soft);border-left:3px solid var(--accent);
  padding:.5rem .8rem;font-size:.86rem;margin:.9rem 0}
.cols{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:2rem;margin-top:1.4rem;align-items:start}
.block{margin:0 0 1.4rem}
.block h2{font-size:1rem;letter-spacing:.14em;color:var(--accent);
  border-bottom:1px solid var(--line);padding-bottom:.3rem;margin:0 0 .6rem}
.block ul{margin:0;padding-left:1.1rem}
.block li{margin:.3rem 0}
.steps li{margin:.7rem 0;list-style:none;margin-left:-1.1rem}
.scans{position:sticky;top:75px}
.scans h2{font-size:1rem;letter-spacing:.14em;color:var(--accent);
  border-bottom:1px solid var(--line);padding-bottom:.3rem;margin:0 0 .6rem}
.scans figure{margin:0 0 1rem}
.scans img{width:100%;border:1px solid var(--line);border-radius:6px;background:#fff}
.scans figcaption{color:var(--muted);font-size:.78rem;text-align:center;margin-top:.3rem}
.btn{display:inline-block;border:1px solid var(--accent);color:var(--accent);
  padding:.45rem 1rem;border-radius:8px;font-size:.88rem}
.btn:hover{background:var(--accent);color:#fff;text-decoration:none}
.footer{border-top:1px solid var(--line);margin-top:2rem;padding:1.2rem 1.4rem;
  color:var(--muted);font-size:.78rem;text-align:center}
.footer p{margin:.25rem 0}
@media (max-width:820px){
  .cols{grid-template-columns:1fr;gap:1.2rem}
  .scans{position:static}
}
"""

APP_JS = """
(function () {
  var data = (window.SHANXI_DATA || {}).recipes || [];
  var list = document.getElementById('list');
  var countEl = document.getElementById('count');
  var emptyEl = document.getElementById('empty');
  var q = document.getElementById('q');
  var filters = { book: '', category: '' };

  var params = new URLSearchParams(location.search);
  if (params.get('book')) filters.book = params.get('book');
  if (params.get('category')) filters.category = params.get('category');

  function matches(r) {
    if (filters.book && r.b !== filters.book) return false;
    if (filters.category && r.c !== filters.category) return false;
    var term = q.value.trim();
    if (!term) return true;
    return r.s.indexOf(term) !== -1;
  }

  function render() {
    var frag = document.createDocumentFragment();
    var n = 0;
    for (var i = 0; i < data.length; i++) {
      var r = data[i];
      if (!matches(r)) continue;
      n++;
      var li = document.createElement('li');
      li.className = 'card';
      var a = document.createElement('a');
      a.href = 'recipes/' + encodeURIComponent(r.u) + '.html';
      a.textContent = r.t;
      var sub = document.createElement('div');
      sub.className = 'sub';
      sub.textContent = r.bl + ' · ' + r.p + ' · ' + r.c;
      li.appendChild(a);
      li.appendChild(sub);
      frag.appendChild(li);
    }
    list.textContent = '';
    list.appendChild(frag);
    countEl.textContent = n;
    emptyEl.hidden = n > 0;
  }

  q.addEventListener('input', render);
  document.querySelectorAll('.chip').forEach(function (chip) {
    chip.addEventListener('click', function () {
      var kind = chip.dataset.filter;
      filters[kind] = chip.dataset.value;
      document.querySelectorAll('.chip[data-filter="' + kind + '"]').forEach(function (c) {
        c.classList.toggle('active', c === chip);
      });
      render();
    });
  });

  document.querySelectorAll('.chip').forEach(function (chip) {
    if (chip.dataset.value && chip.dataset.value === filters[chip.dataset.filter]) {
      document.querySelectorAll('.chip[data-filter="' + chip.dataset.filter + '"]').forEach(function (c) {
        c.classList.toggle('active', c === chip);
      });
    }
  });

  render();
})();
"""


def build_site(root: Path) -> dict[str, Any]:
    """生成静态站到仓库根目录,返回统计信息。"""
    vault_root = root / "work" / "vault"
    anchor_path = root / "work" / "reports" / "toc_anchor_map.json"
    recipes = load_recipes(vault_root)
    anchor_map = json.loads(anchor_path.read_text(encoding="utf-8")) if anchor_path.exists() else {}
    lookup = build_category_lookup(anchor_map)

    site_dir = root / "site"
    recipes_dir = root / "recipes"
    site_dir.mkdir(exist_ok=True)
    recipes_dir.mkdir(exist_ok=True)

    entries: list[dict[str, Any]] = []
    categories: set[str] = set()
    for recipe in recipes:
        book_id = recipe.get("book_id", "")
        category = category_for(lookup, book_id, _first_page(recipe))
        categories.add(category)
        pages = recipe.get("local_pages") or []
        blob = " ".join(
            [str(recipe.get("title", ""))]
            + [str(a) for a in (recipe.get("aliases") or [])]
            + [str(i) for i in (recipe.get("ingredients") or [])]
            + [str(i) for i in (recipe.get("seasonings") or [])]
            + [str(i) for i in (recipe.get("steps") or [])]
            + [str(i) for i in (recipe.get("tips") or [])]
        )
        entries.append(
            {
                "u": recipe["slug"],
                "t": recipe.get("title") or recipe["slug"],
                "b": book_id,
                "bl": _book_label(book_id),
                "p": _page_range(pages),
                "c": category,
                "s": blob,
            }
        )
        (recipes_dir / f"{recipe['slug']}.html").write_text(
            render_recipe_page(recipe, category, SITE_BASE), encoding="utf-8"
        )

    entries.sort(key=lambda e: (e["b"], e["u"]))
    ordered_categories = sorted(c for c in categories if c != UNCATEGORIZED)
    if UNCATEGORIZED in categories:
        ordered_categories.append(UNCATEGORIZED)

    (root / "index.html").write_text(
        render_index_page(recipes, ordered_categories), encoding="utf-8"
    )
    (site_dir / "style.css").write_text(STYLE_CSS.strip() + "\n", encoding="utf-8")
    (site_dir / "app.js").write_text(APP_JS.strip() + "\n", encoding="utf-8")
    (site_dir / "data.js").write_text(
        "window.SHANXI_DATA=" + json.dumps({"recipes": entries}, ensure_ascii=False, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )
    (root / ".nojekyll").write_text("", encoding="utf-8")

    stats = {
        "recipes": len(recipes),
        "categories": len(ordered_categories),
        "uncategorized": sum(1 for e in entries if e["c"] == UNCATEGORIZED),
    }
    LOGGER.info(
        "Site built: %s recipes, %s categories (%s uncategorized)",
        stats["recipes"],
        stats["categories"],
        stats["uncategorized"],
    )
    return stats
