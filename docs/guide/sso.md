# Single sign-on

**Admin → Settings → Single sign-on.** OpenID Connect, which is what Entra ID, Okta,
Google Workspace, Keycloak and Authentik all speak.

LDAP still works, and so do local accounts. Turning this on adds a button to the
sign-in screen; it does not take anything away.

## What to register with your provider

One redirect URI:

```
https://your-webgate/api/auth/sso/callback
```

Then fill in four things here: the **issuer URL**, the **client ID**, the **client
secret** if your provider issued one, and the **scopes**. Everything else — the
authorize and token endpoints, the signing keys — is read from
`{issuer}/.well-known/openid-configuration`, so there is nothing else to copy across.

| Provider | Issuer looks like |
|---|---|
| Entra ID | `https://login.microsoftonline.com/<tenant-id>/v2.0` |
| Okta | `https://<org>.okta.com/oauth2/default` |
| Google Workspace | `https://accounts.google.com` |
| Keycloak | `https://<host>/realms/<realm>` |
| Authentik | `https://<host>/application/o/<slug>/` |

!!! tip "Behind a proxy that rewrites the host"
    webgate works out its own address from the request. If a proxy changes it, set
    **Public URL** and the redirect will be that plus `/api/auth/sso/callback`.

## Groups decide what people can reach

A group from your directory means nothing here until an admin maps it:

```json
{"infra-oncall": "prod", "platform": "core"}
```

An unmapped group grants nothing. That is deliberate: a directory group created next
month must not quietly open a webgate group that happens to share its name.

**Admin groups** is a separate list — membership in any of them makes the person a
webgate admin, and admins see every server.

Both are re-read on every sign-in, so removing somebody from a group in your directory
takes effect the next time they sign in. It does not end a session already open; the
session-token lifetime under **Security** decides that.

### If nobody gets any groups

Your provider is probably not sending the claim. Two things to check: the **scopes**
usually need an extra one (`groups` on Okta and Keycloak, `GroupMember.Read.All`
consented on Entra), and the **groups claim** has to match the name your provider
uses. Entra sends group *object ids* by default rather than names, unless the app
registration is set to emit names.

## What happens on sign-in

1. The button sends the browser to your provider, with PKCE and a one-time `state` and
   `nonce`.
2. Your provider sends it back to the callback with a code.
3. webgate exchanges the code, then **verifies the ID token** — signature against your
   provider's published keys, issuer, audience, expiry, and that the nonce matches the
   one it issued for this sign-in.
4. The account is created or refreshed, with the groups from the mapping.
5. The browser is handed a **one-time code**, and trades it for a session. The session
   token is never put in a URL, so it cannot end up in browser history or a proxy log.

The in-progress sign-in lives in the database, not in memory, so the browser can come
back to a different worker than the one it left. Abandoned attempts are cleared after
ten minutes.

## Notes

- A person who signs in this way has **no local password**. There is nothing to reset
  and nothing to leak; your provider is the credential.
- 2FA is your provider's business here. webgate's own TOTP applies to local accounts.
- Every sign-in is recorded as `sso_login` in the audit log, with the groups granted.
- Turning SSO off leaves the accounts it created. They simply have no working password
  until an admin sets one.
