# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Primary: engineers, SREs, and on-call staff who need SSH and SFTP to internal hosts from a browser because only HTTP(S) reaches the gateway. They work under time pressure (incidents, pair debugging), often on a laptop, sometimes on a tablet.

Secondary: admins who register servers, assign group visibility, manage users, 2FA, API keys, webhooks, and session recordings.

Inferred from README and shipped features (not a live interview).

## Product Purpose

Self-hosted remote-server console: one app for SSH terminal, SFTP browser, and a credentialed server registry. Success is connecting to the right host quickly, transferring files without a VPN, and leaving an audit trail.

## Positioning

A Python FastAPI gateway that combines webssh + Filebrowser with encrypted credentials, jump-host chaining, shared live terminals, and optional LDAP — deployed where only HTTPS is allowed inbound.

## Product Principles

- Task first: get a session open; chrome must not compete with the terminal or file list.
- Trust and control: credentials stay on the gateway; admins gate SSH/SFTP per server.
- Familiar ops density: FileZilla-like workflow (quick connect, site list, path bar) without a 2000s UI clone.
- One surface: vanilla HTML + Alpine; no frontend build step.

## Constraints

- Single-file frontend at `src/webgate/static/index.html` (Alpine, xterm.js, CodeMirror 6 via CDN).
- Dark and light themes; demo mode is read-only with a public banner.
- Reverse-proxy sub-path (`WEBGATE_ROOT_PATH`); all asset URLs must honor `BASE`.
- Accessibility: keyboard shortcuts (Ctrl+1 Site Manager, Ctrl+N new server), visible focus, contrast in both themes.
- Do not break WebSocket terminal, SFTP ops, share-join URLs, or Alpine state.

## Voice

Terse, technical, English UI. Labels name the action (Sign in, Open SSH, Share session). No marketing fluff in the app chrome.

## Terminology

- Site Manager — the server registry / home view (not “dashboard”).
- Quick connect — one-off SSH without saving a site.
- Jump via — bastion / SSH proxy hop.
- Shared session — one PTY, multiple browsers.
- Groups — visibility ACL for non-admins; tags are search-only.

## Evidence

Shipped v0.1–v0.4: terminal, SFTP, registry, jump hosts, snippets, LDAP, recordings, webhooks, HA notes. Live demo at webgate-demo.fly.dev. Users have called the current UI the weakest part of the product.
