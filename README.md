# 陕西菜谱数字化 / Shaanxi Cookbook Digitization

《陕西菜谱》(全四册,1970 年代内部发行)的数字化整理项目:OCR → 人工/AI 校对 → 结构化菜谱库 → 现代化菜谱网站。

## 项目内容

- **原书**:陕西省副食服务公司、西安市饮食公司编写,四册共 641 页、六百余道传统陕菜。
- **管线**(`project/`):基于 MinerU OCR 输出的解析、清洗、菜谱分割与 Obsidian 风格 vault 导出,Python 实现。
- **页面图片**(`assets/pages/`):全部 641 页的灰度 WebP 扫描图,供校对与网站原文对照。
- **校对记录**(`work/page_review_md/`):逐页人工+AI 校对,修正结果经管线自动回灌到菜谱文本。

## 使用

```bash
# 依赖:Python 3.12+,PyYAML / PyMuPDF / Pillow
python -m shanxi_pipeline.cli process-existing-json --root <repo-root>
```

详细命令与项目状态见 [CLAUDE.md](CLAUDE.md)。

## 网站

**<https://rinpv2.github.io/Shaanxi-Recipes>** — 浏览全部 636 道菜、原书页图逐页对照、一键提交纠错。

站点由 `python -m shanxi_pipeline.cli build-site --root .` 从 vault 生成:纯静态 HTML/CSS/JS,无外部依赖与构建步骤,以仓库根为发布目录(页图 `assets/pages/` 原地复用)。

后续计划:食材反向索引、标签浏览(待校对复审完成后再做)。

## 许可

- **代码**(`project/`):[MIT](LICENSE)
- **整理内容**(菜谱文本、校对记录等):[CC BY 4.0](LICENSE-CONTENT.md)
- **原书扫描图**:原书著作权保护期已届满,视为公有领域(详见 [LICENSE-CONTENT.md](LICENSE-CONTENT.md))
