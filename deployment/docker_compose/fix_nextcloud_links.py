#!/usr/bin/env python3
"""Fix URL encoding and format for Nextcloud document links in the database.

Transforms links to the correct Nextcloud format:
https://server/apps/files/files/{file_id}?dir={encoded_path}&editing=false&openfile=true
"""

from urllib.parse import urlparse, parse_qs, quote, unquote
import psycopg2

# Database connection (inside docker network)
conn = psycopg2.connect(
    host="relational_db",
    port=5432,
    dbname="postgres",
    user="postgres",
    password="password"
)


def extract_file_id(doc_id: str) -> str:
    """Extract file_id from document ID (e.g., 'nextcloud_8769' -> '8769')."""
    if doc_id.startswith("nextcloud_"):
        return doc_id[len("nextcloud_"):]
    return ""


def fix_url(doc_id: str, url: str) -> str:
    """Convert Nextcloud URL to proper format with file_id and URL-encoding."""
    file_id = extract_file_id(doc_id)
    if not file_id:
        return url

    # Parse URL properly (handles & in query params correctly)
    parsed = urlparse(url)
    query_params = parse_qs(parsed.query)

    # Get dir parameter
    if 'dir' not in query_params:
        return url

    dir_path = query_params['dir'][0]

    # Decode then re-encode to normalize encoding
    dir_decoded = unquote(dir_path)
    dir_encoded = quote(dir_decoded, safe='/')

    # Build new URL with file_id format
    server_url = f"{parsed.scheme}://{parsed.netloc}"
    return f"{server_url}/apps/files/files/{file_id}?dir={dir_encoded}&editing=false&openfile=true"


# Get all nextcloud documents
cur = conn.cursor()
cur.execute("""
    SELECT id, link FROM document
    WHERE id LIKE 'nextcloud_%'
    AND link IS NOT NULL
""")

rows = cur.fetchall()
print(f"Found {len(rows)} Nextcloud documents")

updated = 0
for doc_id, link in rows:
    new_link = fix_url(doc_id, link)
    if new_link != link:
        cur.execute("UPDATE document SET link = %s WHERE id = %s", (new_link, doc_id))
        updated += 1
        if updated <= 5:
            print(f"\nFixed: {doc_id}")
            print(f"  Old: {link[:100]}...")
            print(f"  New: {new_link[:100]}...")

conn.commit()
print(f"\nUpdated {updated} documents")
cur.close()
conn.close()
