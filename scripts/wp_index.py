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


if __name__ == "__main__":
    sys.exit(0)
