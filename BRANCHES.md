# Feature Branches

This file tracks custom feature branches and their deployment status.

## Active Branches

| Branch | Status | Description | Lines | Dependencies |
|--------|--------|-------------|-------|--------------|
| `feat/nextcloud` | ✅ Ready | Nextcloud WebDAV connector | +1,200 | None |
| `feat/mediawiki-auth` | ✅ Ready | Private wiki auth + robustness | +239 | None |
| `dev/tooling` | ✅ Ready | Dev compose files, DB fix scripts | +319 | None |
| `wip/mattermost-bot` | 🚧 WIP | Mattermost bot integration | +2,340 | Needs: migration, admin UI, docker service |

## Branch Details

### feat/nextcloud
**New Nextcloud connector via WebDAV API**

Derived from external repo with local modifications:
- **Original:** https://github.com/sudheer1994/onyx-danswer-nextcloud
- **Fork:** https://github.com/olvidalo/onyx-danswer-nextcloud

Features:
- Full connector implementation with WebDAV client
- Supports private Nextcloud instances with authentication
- File types: PDF, DOC, TXT, MD, and common formats
- Proper URL encoding (handles `&` and special chars)
- File ID-based URLs for direct file access

Modifications from original:
- Uses Onyx's `extract_text_and_images` for PDF/DOC extraction
- Credential keys use `nextcloud_*` prefix
- Improved error handling and logging

Files:
- `backend/onyx/connectors/nextcloud/` (new, includes SOURCE.md)
- `backend/onyx/connectors/registry.py`
- `backend/onyx/configs/constants.py`
- `web/src/lib/sources.ts`, `types.ts`
- `web/src/lib/connectors/connectors.tsx`, `credentials.ts`
- `web/src/components/icons/icons.tsx`
- `web/public/Nextcloud.svg`

### feat/mediawiki-auth
**MediaWiki connector improvements for private wikis**

- Username/password authentication support
- `create_simple_family_class()` for private wikis
- `safe_edittime_filter_generator()` for robustness
- Fetch ALL pages mode (no categories required)
- Better error handling for problematic pages

Files:
- `backend/onyx/connectors/mediawiki/family.py`
- `backend/onyx/connectors/mediawiki/wiki.py`

### dev/tooling
**Development environment and maintenance scripts**

- Docker compose overlays for hot-reload development
- Database fix scripts for Nextcloud URL corrections

Files:
- `deployment/docker_compose/DEV-SETUP.md`
- `deployment/docker_compose/docker-compose.backend-dev.yml`
- `deployment/docker_compose/docker-compose.mediawiki-dev.yml`
- `deployment/docker_compose/docker-compose.dev.yml`
- `deployment/docker_compose/fix_nextcloud_links.py`
- `deployment/docker_compose/fix_vespa_links.py`

### wip/mattermost-bot
**Self-hosted Mattermost bot integration (Work in Progress)**

- WebSocket-based real-time messaging
- Multi-tenant support with team→tenant mapping
- Registration flow via `!register` command
- Channel configuration for per-channel behavior

Still needed:
- [ ] Database migration (Alembic)
- [ ] Admin UI for configuration
- [ ] Docker service definition
- [ ] Registration key generation API

Files:
- `backend/onyx/onyxbot/mattermost/` (new, 9 files)
- `backend/onyx/db/mattermost_bot.py`
- `backend/onyx/db/models.py`
- `backend/onyx/db/utils.py`
- `backend/onyx/server/query_and_chat/models.py`
- `pyproject.toml`

## Deployment Guide

### To deploy a feature to production:

```bash
# 1. On production server, fetch branches
git fetch origin

# 2. Review changes
git log main..origin/feat/nextcloud --oneline

# 3. Merge when ready
git checkout main
git merge origin/feat/nextcloud

# 4. Or cherry-pick specific commits
git cherry-pick <commit-hash>
```

### Recommended deployment order:
1. `feat/mediawiki-auth` - Backwards compatible improvements
2. `feat/nextcloud` - New feature, no breaking changes
3. `dev/tooling` - Optional, development convenience only
4. `wip/mattermost-bot` - Only after completing TODO items

## Notes

- All branches are based on `main` at commit `605e808`
- Each branch is independent (no cross-dependencies)
- Run `git pull` on main before merging to stay current
