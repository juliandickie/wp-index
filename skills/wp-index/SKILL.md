---
name: wp-index
description: Extract, index, archive, or back up a WordPress site via its REST API, or build a knowledge base from one. Use when the user wants to pull all posts, pages, or custom post types (products, courses) from a WordPress site to local Markdown, CSV, and JSON. Triggers on phrases like extract a WordPress site, index a WP blog, archive WordPress content, scrape wp-json, or back up a WordPress site.
---

# wp-index

Extract and index any WordPress site through its public REST API. Bundled, standard-library Python - no install needed.

## When to use

The user wants a local copy or index of a WordPress site's content - for SEO audits, content migration, a knowledge base, or a backup. Works on any REST-enabled WordPress site (5.6+).

## How to run

The script is at `${CLAUDE_PLUGIN_ROOT}/scripts/wp_index.py`. Run it with the system `python3` (3.8+).

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wp_index.py" --site https://example.com
```

Common variations:

- Specific post types - `--type posts,pages` (default) or `--type products` or `--type sfwd-courses`.

- Every public type - `--type all`.

- Custom output location - `--out ./my-export`.

- Flag stale content - `--since 2025-01-01`.

- Re-run from scratch - `--fresh` (checkpoints only survive an interrupted or failed run; a completed run clears them and refetches next time).

- Include drafts and private items - `--drafts` (requires auth, see below).

## Authentication (optional)

Published content needs no auth. To include drafts and private items, or to get reliable author names, set a WordPress Application Password as environment variables before running:

```bash
export WP_USER="your-wp-username"
export WP_APP_PASSWORD="xxxx xxxx xxxx xxxx xxxx xxxx"
```

Setting up the Application Password is the one step that commonly trips people up, because security plugins (Patchstack, Wordfence, Solid Security) hide the option by default and the site must be on HTTPS. The full setup and troubleshooting guide is in [references/application-passwords.md](references/application-passwords.md). Read it whenever the user cannot find the Application Passwords option or authentication fails.

## Output

Written under the output directory (default `./<domain>-wp-index`):

- `index/<type>-index.csv` - one row per item (title, author, categories, tags, featured image, SEO score).

- `index/archive.json` - full JSON backup of the raw REST API items, exactly as the site returned them.

- `index/knowledge-base.md` - a single Markdown file for Claude project knowledge. On very large sites it becomes numbered parts (`knowledge-base-01.md`, ...) so each file stays ingestible.

- `index/index.xlsx` - only if openpyxl is installed.

- `<type>/YYYY-MM-DD_slug.md` - one Markdown file per item.

- `orphaned/<type>/` - Markdown files from earlier runs whose items no longer exist on the site (moved here, not deleted).

The SEO score uses the real Yoast meta description when the site exposes one; otherwise it scores the excerpt as a proxy, and the `seo_meta_source` column records which one was scored.

The run is read-only against the site. If interrupted it resumes from the last fully fetched post type, and a completed run clears its checkpoints so the next run fetches fresh data. It uses a one-second default delay between requests to stay polite; raise it with `--delay` on rate-limited hosts.
