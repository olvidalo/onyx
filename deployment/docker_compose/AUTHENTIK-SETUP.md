# Authentik LDAP-to-OIDC Setup Guide

This guide configures Authentik as an identity bridge between your LDAP directory and Onyx's OIDC authentication.

## Prerequisites

- Docker and Docker Compose installed
- Access to your LDAP server (hostname, bind credentials)
- Onyx already deployed (or deploying alongside)

## 1. Clone and Configure

```bash
# Clone your fork
git clone https://github.com/olvidalo/onyx.git
cd onyx/deployment/docker_compose

# Checkout the tooling branch (has Authentik config)
git checkout dev/tooling

# Create your environment file
cp env.authentik.example .env.authentik
```

## 2. Edit Environment Variables

Edit `.env.authentik`:

```bash
# Generate a secret key
openssl rand -base64 36
# Copy output to AUTHENTIK_SECRET_KEY

# Generate database password
openssl rand -base64 24
# Copy output to AUTHENTIK_DB_PASS

# Fill in your LDAP details
LDAP_HOST=ldap.uni-koeln.de
LDAP_USER=cn=serviceaccount,ou=services,dc=uni-koeln,dc=de
LDAP_PASS=your-ldap-password
```

## 3. Start Authentik

```bash
# Start Authentik stack
docker compose -f docker-compose.yml -f docker-compose.authentik.yml --env-file .env --env-file .env.authentik up -d authentik-db authentik-redis authentik-server authentik-worker

# Check logs
docker compose logs -f authentik-server
```

Wait for: `Starting gunicorn` message.

## 4. Initial Authentik Setup

1. Open browser: `http://your-server:9000/if/flow/initial-setup/`
2. Create admin account (save these credentials!)
3. Log in to admin interface

## 5. Configure LDAP Source

Navigate to: **Directory → Federation → Create → LDAP Source**

| Field | Value |
|-------|-------|
| **Name** | Uni Köln LDAP |
| **Slug** | uni-koeln-ldap |
| **Server URI** | `ldaps://your-ldap-host:636` |
| **TLS Verification** | ✓ (enabled) |
| **Bind CN** | Your bind DN (e.g., `cn=service,dc=uni-koeln,dc=de`) |
| **Bind Password** | Your LDAP password |
| **Base DN** | `ou=people,dc=uni-koeln,dc=de` |
| **Addition User DN** | (leave empty) |
| **Addition Group DN** | (leave empty) |
| **User object filter** | `(objectClass=person)` |
| **Group object filter** | `(objectClass=groupOfNames)` |
| **Sync users** | ✓ |
| **Sync groups** | ✓ (if you want group sync) |

### Property Mappings (User)

Under **User Property Mappings**, select or create:

- `uid` → `username`
- `mail` → `email`
- `cn` → `name`

Click **Save**, then **Sync** to test the connection.

## 6. Create OIDC Provider for Onyx

Navigate to: **Applications → Providers → Create → OAuth2/OpenID Provider**

| Field | Value |
|-------|-------|
| **Name** | Onyx OIDC |
| **Authorization flow** | default-provider-authorization-implicit-consent |
| **Client type** | Confidential |
| **Client ID** | (auto-generated, copy this) |
| **Client Secret** | (auto-generated, copy this) |
| **Redirect URIs** | `https://your-onyx-domain/auth/oauth/callback` |
| **Signing Key** | authentik Self-signed Certificate |
| **Scopes** | OpenID, Email, Profile |

**Save** and note the Client ID and Secret.

## 7. Create Application

Navigate to: **Applications → Applications → Create**

| Field | Value |
|-------|-------|
| **Name** | Onyx |
| **Slug** | onyx |
| **Provider** | Onyx OIDC (the one you just created) |
| **Launch URL** | `https://your-onyx-domain` |

## 8. Configure Onyx

Add to your Onyx `.env` file:

```bash
# Authentication
AUTH_TYPE=oidc

# OIDC Configuration (from Authentik)
OIDC_CLIENT_ID=<paste Client ID from step 6>
OIDC_CLIENT_SECRET=<paste Client Secret from step 6>

# Issuer URL format: https://<authentik-domain>/application/o/<app-slug>/
OIDC_ISSUER=https://your-server:9443/application/o/onyx/

# Optional: Display name on login button
OIDC_DISPLAY_NAME=Uni Köln Login

# Optional: Map LDAP groups to Onyx (if syncing groups)
# OIDC_GROUPS_ATTRIBUTE=groups
```

## 9. Restart Onyx

```bash
docker compose -f docker-compose.yml -f docker-compose.authentik.yml --env-file .env --env-file .env.authentik up -d
```

## 10. Test Login

1. Open Onyx in browser
2. Click "Login with Uni Köln Login" (or your OIDC_DISPLAY_NAME)
3. Authenticate with your LDAP credentials
4. You should be redirected back to Onyx, logged in

## Troubleshooting

### LDAP Connection Failed
```bash
# Check Authentik logs
docker compose logs authentik-server | grep -i ldap

# Test LDAP connectivity from container
docker compose exec authentik-server python -c "
import ldap3
server = ldap3.Server('ldaps://your-ldap-host:636', use_ssl=True)
conn = ldap3.Connection(server, 'your-bind-dn', 'your-password')
print(conn.bind())
"
```

### Certificate Issues
If using self-signed certs for LDAPS:
```yaml
# In docker-compose.authentik.yml, add to authentik-server volumes:
volumes:
  - /path/to/your/ca-cert.pem:/etc/ssl/certs/ldap-ca.pem:ro
```

### OIDC Redirect Issues
- Ensure `Redirect URIs` in Authentik exactly matches your Onyx callback URL
- Check for http vs https mismatch
- Verify OIDC_ISSUER URL is accessible from Onyx container

### Check LDAP Sync Status
In Authentik UI: **Directory → Federation → Your LDAP Source → Sync Status**

## Architecture Overview

```
┌─────────────┐     LDAPS      ┌─────────────┐
│ LDAP Server │◄──────────────►│  Authentik  │
│ (Uni Köln)  │                │   Server    │
└─────────────┘                └──────┬──────┘
                                      │ OIDC
                                      ▼
                               ┌─────────────┐
                               │    Onyx     │
                               │   Server    │
                               └─────────────┘
```

## Security Notes

- Keep `.env.authentik` out of version control (it's gitignored)
- Use strong passwords for `AUTHENTIK_SECRET_KEY` and `AUTHENTIK_DB_PASS`
- Consider running Authentik behind a reverse proxy with TLS
- Regularly update Authentik image for security patches
