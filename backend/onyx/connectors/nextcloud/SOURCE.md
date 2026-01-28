# Nextcloud Connector - Source Attribution

## Origin

This connector is derived from:
- **Repository:** https://github.com/sudheer1994/onyx-danswer-nextcloud
- **Fork:** https://github.com/olvidalo/onyx-danswer-nextcloud

## Changes from Original

- Uses Onyx's `extract_text_and_images` for proper PDF/DOC extraction
- URL encoding with `quote()` for special characters (handles `&` in paths)
- Credential keys use `nextcloud_*` prefix for Onyx compatibility
- File ID-based URLs for direct file access in Nextcloud UI
- Improved error handling and logging
- Incremental directory traversal with progress logging

## Contributing Back

If you make improvements to this connector, consider contributing them back:

1. Clone the fork: `git clone https://github.com/olvidalo/onyx-danswer-nextcloud`
2. Apply your changes maintaining the original structure
3. Submit a PR to the upstream repo
