#!/usr/bin/env python3
"""Fix URL encoding for Nextcloud document links in Vespa.

Uses document API with continuation for efficient pagination.
"""

import json
import requests
from urllib.parse import urlparse, parse_qs, quote, unquote

VESPA_URL = "http://index:8081"
SCHEMA = "danswer_chunk_qwen3_embedding_4b"


def extract_file_id(doc_id: str) -> str:
    """Extract file_id from document ID (e.g., 'nextcloud_8769' -> '8769')."""
    if doc_id and doc_id.startswith("nextcloud_"):
        return doc_id[len("nextcloud_"):]
    return ""


def fix_url(url: str, file_id: str) -> str:
    """Convert Nextcloud URL to proper format with file_id."""
    if not file_id:
        return url

    parsed = urlparse(url)
    query_params = parse_qs(parsed.query)

    if 'dir' not in query_params:
        return url

    dir_path = query_params['dir'][0]
    dir_decoded = unquote(dir_path)
    dir_encoded = quote(dir_decoded, safe='/')

    server_url = f"{parsed.scheme}://{parsed.netloc}"
    return f"{server_url}/apps/files/files/{file_id}?dir={dir_encoded}&editing=false&openfile=true"


def fix_source_links(source_links_json: str, file_id: str) -> tuple[str, bool]:
    """Fix URLs in source_links JSON. Returns (fixed_json, was_changed)."""
    try:
        links = json.loads(source_links_json)
        changed = False
        for key, url in links.items():
            new_url = fix_url(url, file_id)
            if new_url != url:
                links[key] = new_url
                changed = True
        return json.dumps(links), changed
    except:
        return source_links_json, False


# Use document API with continuation for efficient pagination
print("Fetching nextcloud documents from Vespa...")

total_updated = 0
total_checked = 0
continuation = None

# Build selection query once
selection = quote(f'{SCHEMA}.source_type=="nextcloud"', safe='')

while True:
    # Document visit API with selection to only visit nextcloud documents
    url = f"{VESPA_URL}/document/v1/default/{SCHEMA}/docid?wantedDocumentCount=500&cluster=danswer_index&selection={selection}"
    if continuation:
        url += f"&continuation={continuation}"

    resp = requests.get(url, timeout=60)
    if resp.status_code != 200:
        print(f"Request failed: {resp.status_code}")
        break

    data = resp.json()
    docs = data.get('documents', [])

    if not docs:
        break

    for doc in docs:
        fields = doc.get('fields', {})
        total_checked += 1

        onyx_doc_id = fields.get('document_id', '')
        source_links = fields.get('source_links', '')
        vespa_doc_id = doc.get('id', '')

        file_id = extract_file_id(onyx_doc_id)
        new_links, changed = fix_source_links(source_links, file_id)

        if changed:
            # Extract UUID from vespa doc id (format: id:default:schema::uuid)
            actual_id = vespa_doc_id.split("::")[-1] if "::" in vespa_doc_id else vespa_doc_id

            update_url = f"{VESPA_URL}/document/v1/default/{SCHEMA}/docid/{actual_id}"
            update_data = {
                "fields": {
                    "source_links": {"assign": new_links}
                }
            }
            update_resp = requests.put(update_url, json=update_data, timeout=30)
            if update_resp.status_code == 200:
                total_updated += 1
                if total_updated <= 5:
                    print(f"Updated: {onyx_doc_id}")
            else:
                print(f"Failed to update {onyx_doc_id}: {update_resp.status_code}")

    continuation = data.get('continuation')
    if not continuation:
        break

    if total_checked % 1000 == 0:
        print(f"Progress: checked {total_checked}, updated {total_updated}...")

print(f"\nDone! Checked {total_checked} nextcloud docs, updated {total_updated}")
