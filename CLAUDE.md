# wp-index - Repo Context

## What this is

A Claude Code plugin that extracts any WordPress site to local Markdown, CSV, JSON, and a knowledge-base file via the WordPress REST API. One Python script does everything.

## Design - single stdlib file

The entire extractor lives in `scripts/wp_index.py`. There are no third-party runtime dependencies. The rationale is that the skill invokes the script by absolute path from arbitrary working directories, so a single self-contained file avoids package import-path fragility entirely. `openpyxl` is the one optional dependency, used only if already installed in the environment, and the script degrades gracefully without it.

The pure functions (`slugify`, `html_to_markdown`, `score_seo`, `build_record`, the renderers, the writers, the checkpoint helpers) are module-level and importable by the test suite without running the CLI. The CLI entry point is `main()`, guarded by `if __name__ == "__main__"`.

## Origin

Generalised from `idd-blog-index/extract-wp-blogs.py`. All iDD-specific logic (fixed site URL, iDD-specific post types, Hubstaff-linked output paths) was removed. The generic version accepts any site, any post type, and any output directory.

## Running the tests

Unit tests (fast, no network):

```bash
python3 -m unittest discover -s test -p "test_*.py" -v
```

Smoke test (import check, --help, and the full unit suite):

```bash
./test/smoke.test.sh
```

## Key files

- `scripts/wp_index.py` - the entire extractor

- `skills/wp-index/SKILL.md` - Claude-facing skill (when and how to run it)

- `skills/wp-index/references/application-passwords.md` - auth setup guide

- `commands/wp-index.md` - the `/wp-index` slash command

- `test/test_wp_index.py` - unit tests covering pure functions and mocked HTTP

- `test/smoke.test.sh` - shell smoke test
