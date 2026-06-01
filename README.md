wp-index extracts and indexes any WordPress site through its REST API, writing every post, page, or custom post type to per-item Markdown files, a CSV index, a full JSON archive, and a single knowledge-base file ready to load into a Claude project. It is standard-library Python (no install, no third-party packages) and is read-only against the site it runs against.

## Install

Via the Outfit marketplace (recommended):

```
/plugin install wp-index@outfit
```

Standalone, direct from this repo:

```
/plugin marketplace add juliandickie/wp-index
/plugin install wp-index@wp-index
```

## Quickstart

```bash
python3 scripts/wp_index.py --site https://example.com
```

Output lands in `./example.com-wp-index/` by default.

## Flags

| Flag | Default | What it does |
|---|---|---|
| `--site` | (required) | Base URL of the WordPress site |
| `--type` | `posts,pages` | Comma-separated REST bases, or `all` for every public type |
| `--out` | `./<domain>-wp-index` | Output directory |
| `--since` | off | Flag items not modified since this date (YYYY-MM-DD) |
| `--fresh` | off | Ignore saved checkpoints and re-fetch everything |
| `--delay` | `1.0` | Seconds between requests (raise on rate-limited hosts) |
| `--per-page` | `50` | Items per API page (max 100, WordPress limit) |
| `--drafts` | off | Include drafts and private items (requires auth) |
| `--no-score` | off | Skip the SEO score calculation |

## Output layout

```
<domain>-wp-index/
  index/
    posts-index.csv        one row per post
    pages-index.csv        one row per page
    archive.json           full JSON backup of every item
    knowledge-base.md      single Markdown file for Claude project knowledge
    index.xlsx             only written if openpyxl is installed
  posts/
    2024-03-15_my-slug.md  one file per post, YAML frontmatter + Markdown body
  pages/
    2024-01-10_about.md
```

The run resumes safely from checkpoints if interrupted. Use `--fresh` to start over.

## Authentication - Application Passwords

Published content needs no authentication. You only need credentials if you want to include drafts and private items, or to resolve author display names reliably.

When you do need auth, set these environment variables before running:

```bash
export WP_USER="your-wp-username"
export WP_APP_PASSWORD="xxxx xxxx xxxx xxxx xxxx xxxx"
```

The most common friction point is that security plugins (Patchstack, Wordfence, Solid Security) hide the Application Passwords option in the WordPress admin by default, and the site must be on HTTPS. Full setup steps and per-plugin fixes are in `skills/wp-index/references/application-passwords.md`.

## Requirements

Python 3.8 or newer. No packages to install. `openpyxl` is optional and used only if it is already present in the environment.
