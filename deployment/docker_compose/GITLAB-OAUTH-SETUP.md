# GitLab OAuth Setup for Onyx

Instructions for configuring Onyx to use GitLab as OAuth/OIDC provider.

## Prerequisites

- Onyx instance running
- Access to GitLab admin or ability to create OAuth applications

## Step 1: Create GitLab OAuth Application

In your GitLab instance, go to:
**Admin Area → Applications → New Application**

| Field | Value |
|-------|-------|
| Name | `Onyx` |
| Redirect URI | `https://vps2.schaeben.info:3001/auth/oidc/callback` |
| Confidential | ✓ checked |
| Scopes | ✓ `read_user`, ✓ `openid`, ✓ `profile`, ✓ `email` |

Click **Save** and copy the **Application ID** and **Secret**.

## Step 2: Configure Onyx Environment

Add the following to your Onyx `.env` file:

```bash
# Authentication
AUTH_TYPE=oidc

# GitLab OAuth credentials
OAUTH_CLIENT_ID=<Application ID from GitLab>
OAUTH_CLIENT_SECRET=<Secret from GitLab>

# GitLab OpenID Configuration URL
OPENID_CONFIG_URL=https://gitlab.dh.uni-koeln.de/.well-known/openid-configuration

# Scope override for GitLab compatibility
OIDC_SCOPE_OVERRIDE=openid,profile,email,read_user
```

**Important:** If there's an existing `AUTH_TYPE=basic` line in `.env`, comment it out or remove it.

## Step 3: Restart Onyx

```bash
docker compose down api_server
docker compose up -d api_server
```

Or if using compose overrides:
```bash
docker compose -f docker-compose.yml [other compose files] up -d --force-recreate api_server
```

## Step 4: Verify

1. Open your Onyx instance in a browser
2. You should see a "Continue with OIDC" or similar login button
3. Click it and authenticate with your GitLab credentials
4. You should be redirected back to Onyx, logged in

## Troubleshooting

### "Redirect URI is invalid"
- Ensure the redirect URI in GitLab exactly matches: `https://vps2.schaeben.info:3001/auth/oidc/callback`
- Check for http vs https mismatch
- Check port number

### "Scope is invalid"
- Ensure `OIDC_SCOPE_OVERRIDE=openid,profile,email,read_user` is set
- Verify the scopes are enabled in your GitLab OAuth application

### Still seeing basic auth login
- Check that `AUTH_TYPE=oidc` is set (not `basic`)
- Ensure there's no duplicate `AUTH_TYPE` setting earlier in `.env`
- Force recreate the container: `docker compose up -d --force-recreate api_server`

### Check container env vars
```bash
docker exec <api_server_container> env | grep -E "AUTH_TYPE|OAUTH|OPENID|OIDC"
```

Expected output:
```
AUTH_TYPE=oidc
OAUTH_CLIENT_ID=<your-id>
OAUTH_CLIENT_SECRET=<your-secret>
OPENID_CONFIG_URL=https://gitlab.dh.uni-koeln.de/.well-known/openid-configuration
OIDC_SCOPE_OVERRIDE=openid,profile,email,read_user
```

## Configuration Reference

| Environment Variable | Description | Example |
|---------------------|-------------|---------|
| `AUTH_TYPE` | Authentication type | `oidc` |
| `OAUTH_CLIENT_ID` | GitLab Application ID | `045923b7...` |
| `OAUTH_CLIENT_SECRET` | GitLab Secret | `gloas-93f32...` |
| `OPENID_CONFIG_URL` | GitLab OIDC discovery URL | `https://gitlab.example.com/.well-known/openid-configuration` |
| `OIDC_SCOPE_OVERRIDE` | OAuth scopes to request | `openid,profile,email,read_user` |
| `WEB_DOMAIN` | Onyx public URL (for callbacks) | `https://vps2.schaeben.info:3001` |
