---
description: Extract and index a WordPress site via its REST API
argument-hint: <site-url> [extra flags]
---

Use the wp-index skill to extract and index the WordPress site at $ARGUMENTS.

Run the bundled extractor:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wp_index.py" --site $ARGUMENTS
```

If the user passed only a URL, use the defaults (posts and pages). If they named post types, output locations, or other options, pass them through. If authentication is needed for drafts or author names, point them to the Application Password guide in the skill's references.
