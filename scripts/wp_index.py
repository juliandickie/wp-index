#!/usr/bin/env python3
"""wp-index - extract and index any WordPress site via its REST API.

Standard library only. Optional auth via WP_USER / WP_APP_PASSWORD.
"""

import argparse
import base64
import csv
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser


def slugify(text, max_length=80):
    text = (text or "").lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    if len(text) > max_length:
        text = text[:max_length].rstrip("-")
    return text


def safe_path_part(text, max_length=80):
    """Sanitise a remote-supplied value (slug, rest_base) for use as a path component.

    Slugs and rest_base values come from the remote site's JSON and must never be
    able to escape the output directory (slashes, "..") or contain characters the
    filesystem or openpyxl reject.
    """
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", text or "")
    text = re.sub(r"-{2,}", "-", text).strip("-.")
    if ".." in text:
        text = text.replace("..", ".")
    return text[:max_length]


def grade_for_score(score):
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"


def score_seo(title, meta, slug):
    title = title or ""
    meta = meta or ""
    slug = slug or ""
    score = 0

    tlen = len(title)
    if 30 <= tlen <= 60:
        score += 40
    elif tlen >= 20:
        score += 25
    elif tlen > 0:
        score += 10

    mlen = len(meta)
    if 50 <= mlen <= 160:
        score += 40
    elif mlen > 0:
        score += 20

    slen = len(slug)
    if slen == 0:
        score += 0
    elif slen <= 60:
        score += 20
    else:
        score += 10

    return score, grade_for_score(score)


def parse_wp_date(value):
    if not value:
        return None
    value = value.split("T")[0]
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def is_stale(modified_iso, since_date):
    if not since_date:
        return False
    modified = parse_wp_date(modified_iso)
    threshold = parse_wp_date(since_date)
    if not modified or not threshold:
        return False
    return modified < threshold


def _render_table_rows(rows):
    rows = [r for r in rows if r]
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    lines = ["| " + " | ".join(rows[0]) + " |", "|" + " --- |" * width]
    for r in rows[1:]:
        lines.append("| " + " | ".join(r) + " |")
    return "\n\n" + "\n".join(lines) + "\n"


class _MarkdownParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self._list_stack = []
        self._href_stack = []
        self._suppress = 0
        self._in_pre = False
        self._table = None

    def _emit(self, text):
        # inside a table, output belongs to the current cell; text between
        # cells (whitespace, stray markup) is dropped
        if self._table is not None:
            if self._table["cell"] is not None:
                self._table["cell"].append(text)
        else:
            self.parts.append(text)

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._suppress += 1
            return
        if self._suppress:
            return
        if tag in ("strong", "b"):
            self._emit("**")
        elif tag in ("em", "i"):
            self._emit("*")
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._emit("\n\n" + "#" * int(tag[1]) + " ")
        elif tag == "p":
            self._emit("\n\n")
        elif tag == "br":
            self._emit("\n")
        elif tag == "blockquote":
            self._emit("\n\n> ")
        elif tag in ("ul", "ol"):
            if not self._list_stack:
                self._emit("\n")
            self._list_stack.append(tag)
        elif tag == "li":
            # indent by the marker width of each ancestor list ("- " vs "1. ")
            indent = "".join("  " if t == "ul" else "   " for t in self._list_stack[:-1])
            ordered = self._list_stack[-1:] == ["ol"]
            self._emit("\n" + indent + ("1. " if ordered else "- "))
        elif tag == "a":
            self._href_stack.append(dict(attrs).get("href"))
            self._emit("[")
        elif tag == "img":
            attr_map = dict(attrs)
            src = attr_map.get("src") or attr_map.get("data-src") or ""
            if src:
                self._emit("![%s](%s)" % (attr_map.get("alt") or "", src))
        elif tag == "iframe":
            # YouTube/Vimeo embeds carry no inner text; without this the video
            # would vanish from the extraction entirely. data-src parity with
            # img: cookie-consent plugins gate the real src behind consent.
            attr_map = dict(attrs)
            src = attr_map.get("src") or attr_map.get("data-src") or ""
            if src:
                self._emit("\n\n[embedded content](%s)\n\n" % src)
        elif tag == "pre":
            self._in_pre = True
            self._emit("\n\n```\n")
        elif tag == "code":
            if not self._in_pre:
                self._emit("`")
        elif tag == "table":
            if self._table is None:
                self._table = {"rows": [], "cell": None}
        elif tag == "tr":
            if self._table is not None:
                self._table["cell"] = None
                self._table["rows"].append([])
        elif tag in ("td", "th"):
            if self._table is not None:
                if not self._table["rows"]:
                    self._table["rows"].append([])
                self._table["cell"] = []

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            if self._suppress:
                self._suppress -= 1
            return
        if self._suppress:
            return
        if tag in ("strong", "b"):
            self._emit("**")
        elif tag in ("em", "i"):
            self._emit("*")
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._emit("\n")
        elif tag == "p":
            self._emit("\n")
        elif tag in ("ul", "ol"):
            if self._list_stack:
                self._list_stack.pop()
            if not self._list_stack:
                self._emit("\n")
        elif tag == "a":
            href = self._href_stack.pop() if self._href_stack else None
            self._emit("](%s)" % (href or ""))
        elif tag == "pre":
            self._in_pre = False
            self._emit("\n```\n")
        elif tag == "code":
            if not self._in_pre:
                self._emit("`")
        elif tag in ("td", "th"):
            if self._table is not None and self._table["cell"] is not None:
                text = re.sub(r"\s+", " ", "".join(self._table["cell"])).strip()
                self._table["rows"][-1].append(text.replace("|", "\\|"))
                self._table["cell"] = None
        elif tag == "table":
            if self._table is not None:
                rendered = _render_table_rows(self._table["rows"])
                self._table = None
                if rendered:
                    self.parts.append(rendered)

    def handle_data(self, data):
        if not self._suppress:
            self._emit(data)


def html_to_markdown(html_str):
    if not html_str:
        return ""
    parser = _MarkdownParser()
    parser.feed(html_str)
    parser.close()
    text = "".join(parser.parts)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def resolve_author(item, users_by_id):
    author_id = item.get("author")
    if users_by_id and author_id in users_by_id:
        return users_by_id[author_id]
    embedded = (item.get("_embedded") or {}).get("author")
    if embedded and isinstance(embedded, list) and isinstance(embedded[0], dict) and embedded[0].get("name"):
        return embedded[0]["name"]
    if author_id is not None:
        return "Author %s" % author_id
    return "Unknown"


# attachment is media, not content; nav_menu_item and the wp_-prefixed internal
# types (templates, reusable blocks, global styles, fonts) are listed publicly by
# /types but their collection endpoints require auth, so --type all would spray
# per-type 401s. Types outside the wp/v2 namespace are unreachable from api_base.
SKIPPED_TYPE_SLUGS = {"attachment", "nav_menu_item"}


def parse_public_types(types_json):
    bases = []
    for slug, entry in (types_json or {}).items():
        entry = entry or {}
        base = entry.get("rest_base")
        if not base or slug in SKIPPED_TYPE_SLUGS or slug.startswith("wp_"):
            continue
        if entry.get("rest_namespace", "wp/v2") != "wp/v2":
            continue
        bases.append(base)
    return bases


def extract_terms(item):
    categories, tags = [], []
    for group in ((item.get("_embedded") or {}).get("wp:term") or []):
        if not isinstance(group, list):
            continue
        for term in group:
            if not isinstance(term, dict) or not term.get("name"):
                continue
            if term.get("taxonomy") == "category":
                categories.append(term["name"])
            elif term.get("taxonomy") == "post_tag":
                tags.append(term["name"])
    return categories, tags


def extract_featured_image(item):
    media = (item.get("_embedded") or {}).get("wp:featuredmedia")
    if isinstance(media, list) and media and isinstance(media[0], dict):
        return media[0].get("source_url") or ""
    return ""


def build_record(item, type_name, users_by_id, since_date, do_score):
    title = html.unescape((item.get("title") or {}).get("rendered", "") or "")
    content_html = (item.get("content") or {}).get("rendered", "") or ""
    excerpt_html = (item.get("excerpt") or {}).get("rendered", "") or ""
    slug = item.get("slug", "") or ""
    content_md = html_to_markdown(content_html)
    excerpt_md = html_to_markdown(excerpt_html)
    categories, tags = extract_terms(item)

    record = {
        "id": item.get("id"),
        "type": type_name,
        "title": title,
        "slug": slug,
        "status": item.get("status", ""),
        "url": item.get("link", ""),
        "date": item.get("date", ""),
        "modified": item.get("modified", ""),
        "author": resolve_author(item, users_by_id),
        "categories": categories,
        "tags": tags,
        "featured_image": extract_featured_image(item),
        "excerpt": excerpt_md,
        "word_count": len(content_md.split()),
        "content_markdown": content_md,
        "stale": is_stale(item.get("modified", ""), since_date),
    }
    if do_score:
        # Yoast exposes the real meta description in the default REST response;
        # without it the excerpt is only a proxy, so label which one was scored
        yoast_desc = (item.get("yoast_head_json") or {}).get("description") or ""
        meta = yoast_desc or excerpt_md
        score, grade = score_seo(title, meta, slug)
        record["seo_score"] = score
        record["seo_grade"] = grade
        record["seo_meta_source"] = "yoast" if yoast_desc else "excerpt"
    return record


CSV_FIELDS = [
    "id", "type", "title", "slug", "status", "url", "date", "modified",
    "author", "categories", "tags", "featured_image", "word_count",
    "seo_score", "seo_grade", "seo_meta_source", "stale",
]


def flatten_for_table(record):
    row = dict(record)
    for key in ("categories", "tags"):
        if isinstance(row.get(key), list):
            row[key] = "; ".join(row[key])
    return row


def markdown_for_record(record):
    lines = ["---"]
    lines.append("title: %s" % json.dumps(record.get("title", "")))
    lines.append("id: %s" % record.get("id"))
    lines.append("type: %s" % record.get("type", ""))
    lines.append("slug: %s" % record.get("slug", ""))
    lines.append("status: %s" % record.get("status", ""))
    lines.append("url: %s" % json.dumps(record.get("url", "")))
    lines.append("date: %s" % record.get("date", ""))
    lines.append("modified: %s" % record.get("modified", ""))
    lines.append("author: %s" % json.dumps(record.get("author", "")))
    if record.get("categories"):
        lines.append("categories: %s" % json.dumps(record["categories"], ensure_ascii=False))
    if record.get("tags"):
        lines.append("tags: %s" % json.dumps(record["tags"], ensure_ascii=False))
    if record.get("featured_image"):
        lines.append("featured_image: %s" % json.dumps(record["featured_image"]))
    if "seo_score" in record:
        lines.append("seo_score: %s" % record["seo_score"])
        lines.append("seo_grade: %s" % record["seo_grade"])
        if record.get("seo_meta_source"):
            lines.append("seo_meta_source: %s" % record["seo_meta_source"])
    lines.append("stale: %s" % ("true" if record.get("stale") else "false"))
    lines.append("---")
    body = "# %s\n\n%s\n" % (record.get("title", ""), record.get("content_markdown", ""))
    return "\n".join(lines) + "\n\n" + body


def kb_entry_markdown(r):
    lines = ["## %s" % r.get("title", ""), ""]
    lines.append("- Type: %s" % r.get("type", ""))
    lines.append("- URL: %s" % r.get("url", ""))
    lines.append("- Author: %s" % r.get("author", ""))
    if r.get("categories"):
        lines.append("- Categories: %s" % ", ".join(r["categories"]))
    if r.get("tags"):
        lines.append("- Tags: %s" % ", ".join(r["tags"]))
    if "seo_grade" in r:
        lines.append("- SEO: %s (%s)" % (r.get("seo_score"), r.get("seo_grade")))
    lines.append("")
    if r.get("excerpt"):
        lines.append(r["excerpt"])
        lines.append("")
    return "\n".join(lines)


def knowledge_base_markdown(records, title="Content Knowledge Base"):
    parts = ["# %s" % title, "", "Total items: %d" % len(records), ""]
    for r in records:
        parts.append(kb_entry_markdown(r))
    return "\n".join(parts)


def write_csv(out_dir, type_name, records):
    path = os.path.join(out_dir, "index", "%s-index.csv" % type_name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for r in records:
            writer.writerow(flatten_for_table(r))
    return path


def write_json_archive(out_dir, data):
    path = os.path.join(out_dir, "index", "archive.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    return path


def write_markdown_files(out_dir, type_name, records):
    type_dir = os.path.join(out_dir, type_name)
    os.makedirs(type_dir, exist_ok=True)
    paths = []
    used = set()
    for r in records:
        # date and slug come from the remote site; sanitise before they touch paths
        date_part = (r.get("date") or "")[:10]
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_part):
            date_part = ""
        slug = (safe_path_part(r.get("slug", ""))
                or slugify(r.get("title", "")) or str(r.get("id")))
        base = ("%s_%s" % (date_part, slug)) if date_part else slug
        name = base + ".md"
        if name in used:
            name = "%s_%s.md" % (base, r.get("id"))
        used.add(name)
        path = os.path.join(type_dir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(markdown_for_record(r))
        paths.append(path)
    return paths


ORPHAN_README = (
    "# Orphaned files\n\n"
    "These Markdown files were written by earlier wp-index runs but were no\n"
    "longer visible to the run that moved them: the post was deleted, made\n"
    "private or reverted to draft (visible only with --drafts and auth), or\n"
    "its slug or date changed so it now lives under a new filename. They are\n"
    "moved here at the end of each run instead of being deleted, in case the\n"
    "removal was a mistake. Safe to delete this folder once you have checked\n"
    "them.\n"
)


def reconcile_orphans(type_dir, written_paths, orphan_root):
    """Move stale Markdown files out of a type directory.

    Anything in type_dir that this run did not write is no longer visible to
    this run (deleted, private/draft without auth, or renamed). Moved, never
    deleted, into orphan_root/<type>/ so a long-lived output directory cannot
    silently drift from reality.
    """
    moved = []
    if not os.path.isdir(type_dir):
        return moved
    if os.path.realpath(type_dir) == os.path.realpath(orphan_root):
        # a type whose rest_base sanitises to the orphan root's own name;
        # reconciling it would move its files into itself. No real WordPress
        # type does this, but never collide on purpose.
        return moved
    written = {os.path.realpath(p) for p in written_paths}
    for name in sorted(os.listdir(type_dir)):
        path = os.path.join(type_dir, name)
        if not name.endswith(".md") or not os.path.isfile(path):
            continue
        if os.path.realpath(path) in written:
            continue
        dest_dir = os.path.join(orphan_root, os.path.basename(type_dir))
        os.makedirs(dest_dir, exist_ok=True)
        os.rename(path, os.path.join(dest_dir, name))
        moved.append(name)
    if moved:
        readme = os.path.join(orphan_root, "README.md")
        if not os.path.exists(readme):
            with open(readme, "w", encoding="utf-8") as f:
                f.write(ORPHAN_README)
    return moved


# Claude project knowledge works best with files well under a few MB; split the
# knowledge base at item boundaries once it would exceed this
KB_CHUNK_BYTES = 1_500_000


def write_knowledge_base(out_dir, records, max_bytes=KB_CHUNK_BYTES):
    index_dir = os.path.join(out_dir, "index")
    os.makedirs(index_dir, exist_ok=True)
    # remove both single and part files from earlier runs so a rerun that
    # changes shape (split vs single) leaves no stale copy behind
    for name in os.listdir(index_dir):
        if name == "knowledge-base.md" or re.match(r"^knowledge-base-\d+\.md$", name):
            os.remove(os.path.join(index_dir, name))

    full = knowledge_base_markdown(records)
    if len(full.encode("utf-8")) <= max_bytes:
        path = os.path.join(index_dir, "knowledge-base.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(full)
        return [path]

    chunks = []
    current, current_bytes = [], 0
    for r in records:
        entry_bytes = len(kb_entry_markdown(r).encode("utf-8")) + 1
        if current and current_bytes + entry_bytes > max_bytes:
            chunks.append(current)
            current, current_bytes = [], 0
        current.append(r)
        current_bytes += entry_bytes
    if current:
        chunks.append(current)

    paths = []
    for i, chunk in enumerate(chunks, 1):
        title = "Content Knowledge Base (part %d of %d)" % (i, len(chunks))
        path = os.path.join(index_dir, "knowledge-base-%02d.md" % i)
        with open(path, "w", encoding="utf-8") as f:
            f.write(knowledge_base_markdown(chunk, title=title))
        paths.append(path)
    return paths


def write_xlsx_if_available(out_dir, records_by_type):
    try:
        from openpyxl import Workbook
    except ImportError:
        return None
    workbook = Workbook()
    workbook.remove(workbook.active)
    for type_name, records in records_by_type.items():
        sheet = workbook.create_sheet(title=(type_name[:31] or "sheet"))
        sheet.append(CSV_FIELDS)
        for r in records:
            row = flatten_for_table(r)
            sheet.append([row.get(k, "") for k in CSV_FIELDS])
    path = os.path.join(out_dir, "index", "index.xlsx")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    workbook.save(path)
    return path


def checkpoint_path(checkpoint_dir, name):
    return os.path.join(checkpoint_dir, "%s.json" % name)


def save_checkpoint(checkpoint_dir, name, items):
    # Checkpoints are per-type, written only after a type fully completes, so
    # an interrupted run restarts the in-flight type from page 1. Per-page
    # resume was considered and consciously deferred: it only pays off at
    # multi-thousand-item scale on a single type.
    os.makedirs(checkpoint_dir, exist_ok=True)
    payload = {
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "items": items,
    }
    with open(checkpoint_path(checkpoint_dir, name), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, default=str)


def load_checkpoint(checkpoint_dir, name):
    """Return {"items": [...], "fetched_at": str-or-None}, or None if absent/corrupt.

    Pre-0.2 checkpoints were a bare item list with no timestamp; accept both.
    """
    path = checkpoint_path(checkpoint_dir, name)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError):
        return None
    if isinstance(data, dict) and "items" in data:
        return {"items": data["items"], "fetched_at": data.get("fetched_at")}
    if isinstance(data, list):
        return {"items": data, "fetched_at": None}
    return None


def clear_checkpoints(checkpoint_dir):
    if os.path.isdir(checkpoint_dir):
        for name in os.listdir(checkpoint_dir):
            if name.endswith(".json"):
                os.remove(os.path.join(checkpoint_dir, name))
        try:
            os.rmdir(checkpoint_dir)
        except OSError:
            pass


# Deliberate Chrome spoof rather than an honest UA: several WAF setups block
# python-urllib's default agent outright, and reliability against arbitrary
# third-party sites wins over etiquette here. Documented so it is a choice,
# not an oversight.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


def build_headers(user=None, app_password=None):
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if user and app_password:
        token = base64.b64encode(("%s:%s" % (user, app_password)).encode()).decode()
        headers["Authorization"] = "Basic %s" % token
    return headers


REQUEST_TIMEOUT = 120  # seconds; embed-heavy WordPress responses can be slow to generate


def fetch_json(url, headers, max_retries=4, delay=1.0):
    last_err = None
    for attempt in range(max_retries):
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as resp:
                body = resp.read().decode("utf-8")
                resp_headers = {k.lower(): v for k, v in resp.headers.items()}
                try:
                    return json.loads(body), resp_headers
                except json.JSONDecodeError:
                    raise ValueError(
                        "non-JSON response from %s (bot challenge or maintenance page?)"
                        % url
                    ) from None
        except urllib.error.HTTPError as err:
            if err.code in (429, 500, 502, 503, 504):
                retry_after = err.headers.get("Retry-After") if err.headers else None
                try:
                    wait = float(retry_after)
                except (TypeError, ValueError):
                    # Retry-After may be an HTTP date rather than seconds
                    wait = delay * (2 ** attempt)
                last_err = err
                time.sleep(min(wait, 30))
                continue
            raise
        except OSError as err:
            # URLError, TimeoutError, ConnectionError and other socket errors are
            # transient; retry with exponential backoff. TimeoutError is an OSError
            # but NOT a URLError, so it must be caught here (a read timeout on a slow
            # embed-heavy response would otherwise escape and crash the whole run).
            last_err = err
            time.sleep(delay * (2 ** attempt))
    raise last_err


def fetch_all(api_base, rest_base, headers, per_page=50, delay=1.0,
              include_drafts=False, log=lambda m: None):
    items = []
    seen_ids = set()
    page = 1
    status = "any" if include_drafts else "publish"
    while True:
        params = {"per_page": per_page, "page": page, "_embed": "1", "status": status}
        url = "%s/%s?%s" % (api_base, rest_base, urllib.parse.urlencode(params))
        try:
            data, resp_headers = fetch_json(url, headers, delay=delay)
        except urllib.error.HTTPError as err:
            if err.code == 400:  # page beyond total
                break
            raise
        if not data:
            break
        # a post published mid-crawl shifts pagination, so later pages can
        # repeat items already seen; keep the first copy of each id
        for item in data:
            item_id = item.get("id") if isinstance(item, dict) else None
            if item_id is not None:
                if item_id in seen_ids:
                    continue
                seen_ids.add(item_id)
            items.append(item)
        try:
            total_pages = int(resp_headers.get("x-wp-totalpages", ""))
        except ValueError:
            total_pages = None
        if total_pages:
            log("  %s page %d/%d (+%d)" % (rest_base, page, total_pages, len(data)))
            if page >= total_pages:
                break
        else:
            # Some proxies strip X-WP-TotalPages; without it, keep paging until an
            # empty page or the 400 "page beyond total" rather than silently
            # stopping after page 1.
            log("  %s page %d/? (+%d; no X-WP-TotalPages header)"
                % (rest_base, page, len(data)))
        page += 1
        time.sleep(delay)
    return items


def fetch_users(api_base, headers, delay=1.0):
    users = {}
    page = 1
    while True:
        url = "%s/users?%s" % (api_base, urllib.parse.urlencode({"per_page": 100, "page": page}))
        try:
            data, resp_headers = fetch_json(url, headers, delay=delay)
        except (urllib.error.HTTPError, ValueError):
            break
        if not data:
            break
        for user in data:
            users[user.get("id")] = user.get("name", "")
        # mirror fetch_all: a stripped X-WP-TotalPages header must not silently
        # stop pagination after page 1; keep going until an empty page
        try:
            total_pages = int(resp_headers.get("x-wp-totalpages", ""))
        except ValueError:
            total_pages = None
        if total_pages and page >= total_pages:
            break
        page += 1
        time.sleep(delay)
    return users


def detect_rest_api(api_base, headers):
    try:
        data, _ = fetch_json(api_base, headers)
        return isinstance(data, dict) and "routes" in data
    except Exception:
        return False


def verify_auth(api_base, headers):
    """Preflight the credentials against /users/me.

    WordPress rejects every REST request (including public ones) when an invalid
    Application Password is presented, so bad credentials must be caught up front
    or they masquerade as "not a WordPress site".
    """
    try:
        data, _ = fetch_json("%s/users/me" % api_base, headers)
        return isinstance(data, dict) and "id" in data
    except (urllib.error.HTTPError, ValueError):
        return False


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Extract and index a WordPress site via its REST API."
    )
    parser.add_argument("--site", required=True, help="Base site URL, e.g. https://example.com")
    parser.add_argument("--type", default="posts,pages",
                        help="Comma list of REST bases, or 'all' for every public type")
    parser.add_argument("--out", default=None, help="Output directory")
    parser.add_argument("--since", default=None, help="Flag items not modified since YYYY-MM-DD")
    parser.add_argument("--fresh", action="store_true", help="Ignore checkpoints")
    parser.add_argument("--delay", type=float, default=1.0, help="Seconds between requests")
    parser.add_argument("--per-page", type=int, default=50, dest="per_page",
                        help="Items per API page (max 100)")
    parser.add_argument("--drafts", action="store_true", help="Include drafts (needs auth)")
    parser.add_argument("--no-score", action="store_true", dest="no_score",
                        help="Skip SEO scoring")
    args = parser.parse_args(argv)

    site = args.site.rstrip("/")
    api_base = "%s/wp-json/wp/v2" % site
    domain = urllib.parse.urlparse(site).netloc or "site"
    out_dir = args.out or ("./%s-wp-index" % domain)
    checkpoint_dir = os.path.join(out_dir, ".checkpoints")

    if args.per_page > 100:
        print("  NOTE: --per-page capped at 100 (WordPress maximum); using 100.")
        args.per_page = 100

    if args.since and parse_wp_date(args.since) is None:
        print("ERROR: --since must be a date in YYYY-MM-DD form (got %r)." % args.since)
        return 2

    user = os.environ.get("WP_USER")
    app_password = os.environ.get("WP_APP_PASSWORD")
    auth_enabled = bool(user and app_password)
    headers = build_headers(user, app_password)

    if args.drafts and not auth_enabled:
        print("WARNING: --drafts needs WP_USER / WP_APP_PASSWORD; running public mode.")

    if not detect_rest_api(api_base, headers):
        print("ERROR: %s does not look like a REST-enabled WordPress site "
              "(no /wp-json/wp/v2)." % site)
        if auth_enabled:
            print("  NOTE: WordPress rejects every REST request when WP_USER / "
                  "WP_APP_PASSWORD are invalid; try unsetting them to test public access.")
        return 2

    if auth_enabled and not verify_auth(api_base, headers):
        if args.drafts:
            print("ERROR: WP_USER / WP_APP_PASSWORD were rejected (/users/me failed); "
                  "--drafts needs valid credentials.")
            return 2
        print("WARNING: WP_USER / WP_APP_PASSWORD were rejected (/users/me failed); "
              "continuing in public mode.")
        auth_enabled = False
        headers = build_headers(None, None)

    if args.fresh:
        clear_checkpoints(checkpoint_dir)

    if args.type == "all":
        try:
            types_json, _ = fetch_json("%s/types" % api_base, headers)
            rest_bases = parse_public_types(types_json)
        except Exception as err:
            print("  WARNING: could not enumerate post types (%s); falling back to posts,pages." % err)
            rest_bases = ["posts", "pages"]
    else:
        rest_bases = [t.strip() for t in args.type.split(",") if t.strip()]

    users_by_id = fetch_users(api_base, headers, delay=args.delay) if auth_enabled else {}

    archive = {"site": site, "types": {}}
    records_by_type = {}
    failed_types = []
    seen_safe = set()
    for rest_base in rest_bases:
        # rest_base can come from the remote /types endpoint; use a sanitised
        # variant wherever it becomes a directory, file, or sheet name
        safe_type = safe_path_part(rest_base) or "type"
        if safe_type in seen_safe:
            safe_type = "%s-%d" % (safe_type, len(seen_safe))
        seen_safe.add(safe_type)
        cached = None if args.fresh else load_checkpoint(checkpoint_dir, "items_%s" % safe_type)
        if cached is not None:
            raw_items = cached["items"]
            print("  Loaded checkpoint for %s (%d items, fetched %s); use --fresh to refetch."
                  % (rest_base, len(raw_items), cached.get("fetched_at") or "unknown time"))
        else:
            try:
                raw_items = fetch_all(
                    api_base, rest_base, headers, per_page=args.per_page, delay=args.delay,
                    include_drafts=args.drafts and auth_enabled, log=print,
                )
            except Exception as err:
                print("  ERROR: failed to fetch %s after retries (%s); skipping this type." % (rest_base, err))
                failed_types.append(rest_base)
                continue
            save_checkpoint(checkpoint_dir, "items_%s" % safe_type, raw_items)
        records = []
        for item in raw_items:
            try:
                records.append(
                    build_record(item, rest_base, users_by_id, args.since, not args.no_score)
                )
            except Exception as err:
                print("  WARNING: skipped %s item id=%s (%s)" % (rest_base, item.get("id"), err))
        records_by_type[safe_type] = records
        # the archive is the backup surface; keep the raw API items so nothing
        # (custom fields, media ids, taxonomy, original HTML) is lost
        archive["types"][rest_base] = raw_items
        written = write_markdown_files(out_dir, safe_type, records)
        moved = reconcile_orphans(
            os.path.join(out_dir, safe_type), written,
            os.path.join(out_dir, "orphaned"))
        if moved:
            print("  %s: %d orphaned file(s) moved to orphaned/%s/ "
                  "(no longer visible to this run)" % (rest_base, len(moved), safe_type))
        write_csv(out_dir, safe_type, records)
        print("  %s: %d items" % (rest_base, len(records)))

    all_records = [r for records in records_by_type.values() for r in records]
    write_json_archive(out_dir, archive)
    kb_paths = write_knowledge_base(out_dir, all_records)
    if len(kb_paths) > 1:
        print("  NOTE: knowledge base split into %d parts to stay ingestible." % len(kb_paths))
    xlsx_path = write_xlsx_if_available(out_dir, records_by_type)

    # checkpoints exist to resume an interrupted run; after a fully successful one
    # they would only serve stale data on the next invocation
    if not failed_types:
        clear_checkpoints(checkpoint_dir)

    print("\nDone. %d items across %d type(s) -> %s"
          % (len(all_records), len(records_by_type), out_dir))
    print("  XLSX: %s" % xlsx_path if xlsx_path else "  (XLSX skipped; openpyxl not installed)")
    if failed_types:
        print("  WARNING: %d type(s) failed and were skipped: %s"
              % (len(failed_types), ", ".join(failed_types)))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
