# Development Setup Notes

## Starting the Docker Stack

### Standard Development (with local code mounting)

```bash
cd deployment/docker_compose

# Start all services with dev overrides and local backend code mounted
docker compose -f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.backend-dev.yml up -d

# Or just use the dev compose (without backend code mounting)
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

### Quick restart (after code changes to connectors)

```bash
docker compose restart background api_server
```

### View logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f background

# Recent logs only
docker compose logs --since 5m background
```

## Frontend Development

Run the frontend outside of Docker for hot-reloading:

```bash
cd web
npm install
npm run dev
```

Frontend runs at http://localhost:3000 and proxies API requests to backend at :8080.

## What the dev compose files do

- `docker-compose.dev.yml` - Base dev config with exposed ports
- `docker-compose.backend-dev.yml` - Mounts local `backend/onyx/connectors` and `constants.py` into containers (read-only)

## Database Access

```bash
# PostgreSQL CLI
docker compose exec relational_db psql -U postgres -d postgres

# Example queries
SELECT * FROM connector WHERE source = 'nextcloud';
SELECT id, status, new_docs_indexed FROM index_attempt ORDER BY id DESC LIMIT 5;
```

## Nextcloud Connector

Added from: https://github.com/sudheer1994/onyx-danswer-nextcloud

Files modified:
- `backend/onyx/connectors/nextcloud/` - Connector code
- `backend/onyx/configs/constants.py` - Added NEXTCLOUD to DocumentSource
- `backend/onyx/connectors/registry.py` - Registered connector
- `web/src/lib/types.ts` - Added to ValidSources
- `web/src/lib/sources.ts` - Added source metadata
- `web/src/lib/connectors/credentials.ts` - Credential config
- `web/src/lib/connectors/connectors.tsx` - Connector UI config
- `web/public/Nextcloud.svg` - Icon
