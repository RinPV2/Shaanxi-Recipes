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

全部命令见 `project/scripts/`(编号 01–11 的 PowerShell 脚本)与 `python -m shanxi_pipeline.cli --help`。

## 网站

**<https://rinpv2.github.io/Shaanxi-Recipes>** — 浏览全部 636 道菜、原书页图逐页对照、一键提交纠错。

站点由 `python -m shanxi_pipeline.cli build-site --root .` 从 vault 生成:纯静态 HTML/CSS/JS,无外部依赖与构建步骤,以仓库根为发布目录(页图 `assets/pages/` 原地复用)。

后续计划:食材反向索引、标签浏览(待校对复审完成后再做)。

## 许可与版权

- **代码**(`project/`):[MIT](LICENSE)
- **整理内容**(转写文本、校对记录、索引):[CC BY 4.0](LICENSE-CONTENT.md)
  —— 仅涵盖本项目的转写与整理成果,**不包括原书内容本身**。
- **原书扫描图**(`assets/pages/`):原书系陕西省副食服务公司、西安市饮食公司编写的法人作品,
  1970 年代内部发行。依《著作权法》,法人作品的保护期为首次发表后五十年,据此推定已进入公有领域。
  但原书未标注确切出版年份,且「内部发行」是否构成法律意义上的「发表」存在解释空间,
  **故上述推定不构成法律意见**。

本项目为非营利的文献整理,页图仅用于与转写文本逐页对照校核。
若权利人认为本项目侵犯其权益,请通过 [GitHub Issue](https://github.com/RinPV2/Shaanxi-Recipes/issues) 联系,我们将立即下架相关内容。
