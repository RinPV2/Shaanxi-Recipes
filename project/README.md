# Shanxi Pipeline

This project converts existing MinerU JSON outputs for `陕西菜谱2-4` into a resumable Obsidian vault under `work/vault`.

## Scope

- Source of truth for books 2-4 is the existing MinerU JSON.
- Book 1 remains pending and can be imported later without rebuilding successful outputs.
- Traceability stays book-local and page-local.

## Quick Start

From `.`:

```powershell
.\project\scripts\01_prepare.ps1
.\project\scripts\02_process_existing_json.ps1
.\project\scripts\03_review_ambiguous.ps1
```

## Incremental Import

When `sxcp-1` MinerU JSON becomes available:

```powershell
.\project\scripts\04_import_book1_later.ps1 -MineruJson ".\MinerU_陕西菜谱1__YYYYMMDDHHMMSS.json"
```

That command only processes `sxcp-1` and then refreshes aggregate indexes.

## Direct Commands

```powershell
$env:PYTHONPATH = ".\project\src"
.\.venv\Scripts\python.exe -m shanxi_pipeline.cli prepare
.\.venv\Scripts\python.exe -m shanxi_pipeline.cli process-existing-json --book-id sxcp-2 --book-id sxcp-3 --book-id sxcp-4
.\.venv\Scripts\python.exe -m shanxi_pipeline.cli review-ambiguous --book-id sxcp-3
.\.venv\Scripts\python.exe -m shanxi_pipeline.cli import-book --book-id sxcp-1 --mineru-json "D:\path\to\MinerU_陕西菜谱1.json"
```

## Validation

```powershell
$env:PYTHONPATH = ".\project\src"
.\.venv\Scripts\python.exe -m unittest discover -s .\project\tests -v
```
