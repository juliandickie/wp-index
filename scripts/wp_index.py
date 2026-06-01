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
from datetime import datetime
from html.parser import HTMLParser


def slugify(text, max_length=80):
    text = (text or "").lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    if len(text) > max_length:
        text = text[:max_length].rstrip("-")
    return text


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


class _MarkdownParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self._list_stack = []
        self._href = None

    def handle_starttag(self, tag, attrs):
        if tag in ("strong", "b"):
            self.parts.append("**")
        elif tag in ("em", "i"):
            self.parts.append("*")
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.parts.append("\n\n" + "#" * int(tag[1]) + " ")
        elif tag == "p":
            self.parts.append("\n\n")
        elif tag == "br":
            self.parts.append("\n")
        elif tag == "blockquote":
            self.parts.append("\n\n> ")
        elif tag in ("ul", "ol"):
            self._list_stack.append(tag)
            self.parts.append("\n")
        elif tag == "li":
            ordered = self._list_stack[-1:] == ["ol"]
            self.parts.append("\n" + ("1. " if ordered else "- "))
        elif tag == "a":
            self._href = dict(attrs).get("href")
            self.parts.append("[")
        elif tag in ("code", "pre"):
            self.parts.append("`")

    def handle_endtag(self, tag):
        if tag in ("strong", "b"):
            self.parts.append("**")
        elif tag in ("em", "i"):
            self.parts.append("*")
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.parts.append("\n")
        elif tag == "p":
            self.parts.append("\n")
        elif tag in ("ul", "ol"):
            if self._list_stack:
                self._list_stack.pop()
            self.parts.append("\n")
        elif tag == "a":
            self.parts.append("](%s)" % (self._href or ""))
            self._href = None
        elif tag in ("code", "pre"):
            self.parts.append("`")

    def handle_data(self, data):
        self.parts.append(data)


def html_to_markdown(html_str):
    if not html_str:
        return ""
    parser = _MarkdownParser()
    parser.feed(html_str)
    text = "".join(parser.parts)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def resolve_author(item, users_by_id):
    author_id = item.get("author")
    if users_by_id and author_id in users_by_id:
        return users_by_id[author_id]
    embedded = (item.get("_embedded") or {}).get("author")
    if embedded and isinstance(embedded, list) and embedded[0].get("name"):
        return embedded[0]["name"]
    if author_id is not None:
        return "Author %s" % author_id
    return "Unknown"


def parse_public_types(types_json):
    bases = []
    for slug, entry in (types_json or {}).items():
        base = (entry or {}).get("rest_base")
        if base and slug != "attachment":
            bases.append(base)
    return bases


def build_record(item, type_name, users_by_id, since_date, do_score):
    title = html.unescape((item.get("title") or {}).get("rendered", "") or "")
    content_html = (item.get("content") or {}).get("rendered", "") or ""
    excerpt_html = (item.get("excerpt") or {}).get("rendered", "") or ""
    slug = item.get("slug", "") or ""
    content_md = html_to_markdown(content_html)
    excerpt_md = html_to_markdown(excerpt_html)

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
        "excerpt": excerpt_md,
        "word_count": len(content_md.split()),
        "content_markdown": content_md,
        "stale": is_stale(item.get("modified", ""), since_date),
    }
    if do_score:
        score, grade = score_seo(title, excerpt_md, slug)
        record["seo_score"] = score
        record["seo_grade"] = grade
    return record


CSV_FIELDS = [
    "id", "type", "title", "slug", "status", "url", "date", "modified",
    "author", "word_count", "seo_score", "seo_grade", "stale",
]


def markdown_for_record(record):
    lines = ["---"]
    lines.append("title: %s" % json.dumps(record.get("title", "")))
    lines.append("id: %s" % record.get("id"))
    lines.append("type: %s" % record.get("type", ""))
    lines.append("slug: %s" % record.get("slug", ""))
    lines.append("status: %s" % record.get("status", ""))
    lines.append("url: %s" % record.get("url", ""))
    lines.append("date: %s" % record.get("date", ""))
    lines.append("modified: %s" % record.get("modified", ""))
    lines.append("author: %s" % json.dumps(record.get("author", "")))
    if "seo_score" in record:
        lines.append("seo_score: %s" % record["seo_score"])
        lines.append("seo_grade: %s" % record["seo_grade"])
    lines.append("stale: %s" % ("true" if record.get("stale") else "false"))
    lines.append("---")
    body = "# %s\n\n%s\n" % (record.get("title", ""), record.get("content_markdown", ""))
    return "\n".join(lines) + "\n\n" + body


def knowledge_base_markdown(records):
    lines = ["# Content Knowledge Base", "", "Total items: %d" % len(records), ""]
    for r in records:
        lines.append("## %s" % r.get("title", ""))
        lines.append("")
        lines.append("- Type: %s" % r.get("type", ""))
        lines.append("- URL: %s" % r.get("url", ""))
        lines.append("- Author: %s" % r.get("author", ""))
        if "seo_grade" in r:
            lines.append("- SEO: %s (%s)" % (r.get("seo_score"), r.get("seo_grade")))
        lines.append("")
        if r.get("excerpt"):
            lines.append(r["excerpt"])
            lines.append("")
    return "\n".join(lines)


def write_csv(out_dir, type_name, records):
    path = os.path.join(out_dir, "index", "%s-index.csv" % type_name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for r in records:
            writer.writerow(r)
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
    for r in records:
        date_part = (r.get("date") or "")[:10]
        slug = r.get("slug") or slugify(r.get("title", "")) or str(r.get("id"))
        name = ("%s_%s.md" % (date_part, slug)) if date_part else ("%s.md" % slug)
        path = os.path.join(type_dir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(markdown_for_record(r))
        paths.append(path)
    return paths


def write_knowledge_base(out_dir, records):
    path = os.path.join(out_dir, "index", "knowledge-base.md")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(knowledge_base_markdown(records))
    return path


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
            sheet.append([r.get(k, "") for k in CSV_FIELDS])
    path = os.path.join(out_dir, "index", "index.xlsx")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    workbook.save(path)
    return path


if __name__ == "__main__":
    sys.exit(0)
