# Dev notes

Dated, additive notes from using wp-index in the field. Newest first. These are observations and gaps found downstream, not a changelog - see git history for releases.

---

## 2026-08-04 - `reconcile_orphans` sweeps non-content files into `orphaned/`

**Found in** `idd-blog-index`, running v0.2.2 vendored, against both the main site and the academy.

**Behaviour.** `reconcile_orphans(type_dir, written_paths, orphan_root)` moves every file in `type_dir` that is not in `written_paths` into `orphan_root`. That is correct for content whose post has left the site, which is the function's purpose. But it does not distinguish content from **repository files that live alongside content**.

On every extraction run it moved:

- `output/articles/CLAUDE.md`
- `output/pages/CLAUDE.md`

Those are per-directory documentation that `idd-blog-index`'s own root `CLAUDE.md` documents as expected to exist. Nothing is lost (the move is a move, not a delete) but it recurs on every run, it makes the diff noisy, and a session that does not notice will commit the repo's own docs into an `orphaned/` folder.

**Suggested fix.** Skip dotfiles and a small set of known repo filenames when collecting orphan candidates. Something like:

```python
SKIP = {'CLAUDE.md', 'README.md', '.gitkeep', '.DS_Store'}
# ... when scanning type_dir for orphan candidates:
if path.name in SKIP or path.name.startswith('.'):
    continue
```

A caller-supplied `ignore` set would be more flexible than a hardcoded list, since a consumer may keep other sidecar files in the same directory.

**Why it was not fixed downstream.** `idd-blog-index` vendors `wp_index.py` byte-identical to upstream and its CLAUDE.md states the file is never hand-edited - improvements belong here. The workaround there is to move the two files back after each run.

---

## 2026-08-04 - `_embed` is a reliability risk on large or slow WordPress sites

**Found in** `idd-blog-index`'s academy extractor (not wp-index code itself, but relevant to anything built on this pattern).

`academy.instituteofdigitaldentistry.com` runs WordPress plus LearnDash plus Patchstack with ~141 courses. Embedding author and featured media per item progressively degraded as the site grew - `per_page=50` began returning 500s, then `per_page=20` did too, and by 4 August the request was **timing out** rather than erroring, which killed the run outright. The identical request without `_embed` returns 200 immediately.

**Worth building in.** Treat `_embed` as best-effort rather than required. On the first failure, drop it for the remainder of the run and continue with whatever fallbacks the record-processing step already has (author name, featured image), then report the degradation. Failing an entire multi-hundred-item crawl because an optional enrichment parameter timed out is the wrong trade.

The downstream fix is in `idd-blog-index/extract-wp-academy.py`, `fetch_all_courses()`, if a reference implementation is useful.
