# Feature Branches

This file tracks custom feature branches and their deployment status.

## Active Branches (v2 - Clean)

| Branch | Status | Description | Commits | Dependencies |
|--------|--------|-------------|---------|--------------|
| `feat/nextcloud-v2` | ✅ Ready | Nextcloud WebDAV connector | 6 | None |
| `feat/mediawiki-auth-v2` | ✅ Ready | Private wiki authentication | 1 | None |
| `fix/oidc-gitlab-offline-access-v2` | ✅ Ready | OIDC disable offline access option | 1 | None |
| `fix/poll-connector-checkpoint-resume-v2` | ✅ Ready | Poll connector checkpoint fixes | 2 | None |
| `fix/indexing-reliability-v2` | ✅ Ready | Batch idempotency + retry logic | 5 | Requires migration |

## Branch Details

### feat/nextcloud-v2
**Nextcloud connector via WebDAV API**

Derived from external repo with local modifications:
- **Original:** https://github.com/sudheer1994/onyx-danswer-nextcloud
- **Fork:** https://github.com/olvidalo/onyx-danswer-nextcloud

Features:
- Full connector implementation with WebDAV client
- Supports private Nextcloud instances with authentication
- File types: PDF, DOC, TXT, MD, and common formats
- Proper URL encoding (handles `&` and special chars)
- Uses global `INDEX_BATCH_SIZE` instead of hardcoded value
- Debug logging for troubleshooting

Files:
- `backend/onyx/connectors/nextcloud/` (new directory)
- `backend/onyx/configs/constants.py` (DocumentSource enum)
- `web/src/lib/connectors/credentials.ts`
- Various web UI files for connector configuration

### feat/mediawiki-auth-v2
**MediaWiki connector authentication for private wikis**

- Username/password authentication support
- `create_simple_family_class()` for private wiki configuration

Files:
- `backend/onyx/connectors/mediawiki/family.py`
- `backend/onyx/connectors/mediawiki/wiki.py`

### fix/oidc-gitlab-offline-access-v2
**GitLab OIDC compatibility fix**

- `OIDC_DISABLE_OFFLINE_ACCESS` environment variable
- Fixes authentication with GitLab which doesn't support offline_access scope

Files:
- `backend/onyx/auth/oidc.py`

### fix/poll-connector-checkpoint-resume-v2
**Poll connector checkpoint handling**

- Proper checkpoint resume after partial indexing
- Prevents re-indexing already processed documents

Files:
- `backend/onyx/background/celery/tasks/indexing/tasks.py`

### fix/indexing-reliability-v2
**Indexing reliability improvements**

Addresses several issues with batch processing:

1. **Batch double-counting prevention**: Uses `completed_batch_nums` JSONB array to track which batches have been counted, preventing overcounting when Celery visibility timeout causes task requeuing.

2. **Transient error retry**: `MAX_TRANSIENT_RETRIES = 3` with exponential backoff for 500 errors, timeouts, etc.

3. **Permanent failure handling**: `mark_batch_permanently_failed()` records errors and increments completion count to prevent stuck states.

4. **Idempotent batch updates**: Both success and failure paths check if batch was already counted.

Files:
- `backend/onyx/background/celery/tasks/docprocessing/tasks.py`
- `backend/onyx/db/indexing_coordination.py`
- `backend/onyx/db/models.py`
- `backend/alembic/versions/6a62e30d89f9_add_completed_batch_nums_to_index_.py`

**Migration required:** Run `alembic upgrade head` to add `completed_batch_nums` column.

## Deployment

### Creating deploy branch

```bash
# Start from origin/main
git checkout origin/main -b deploy/v2

# Merge all feature branches
git merge feat/nextcloud-v2
git merge feat/mediawiki-auth-v2
git merge fix/oidc-gitlab-offline-access-v2
git merge fix/poll-connector-checkpoint-resume-v2
git merge fix/indexing-reliability-v2

# Run migration
cd backend && alembic upgrade head
```

### Backup tags

Original branches backed up at `backup/20260218_110417/*`

## Notes

- All v2 branches based on `origin/main` (clean cherry-picks)
- Each branch is independent (no cross-dependencies)
- Previous messy branches replaced with clean versions
