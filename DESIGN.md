---
name: webgate
description: Dense ops console for SSH and SFTP through a browser gateway
colors:
  bg: "#121410"
  bg-elevated: "#1c1f1a"
  bg-sunken: "#0c0e0b"
  border: "#2e332c"
  text: "#eceee6"
  text-muted: "#9aa392"
  accent: "#3dcf8e"
  accent-dim: "#1a4a36"
  danger: "#f07167"
  warning: "#e0b04a"
  info: "#7ec8e3"
  light-bg: "#f3f0e8"
  light-text: "#1c1f18"
  light-accent: "#0f7a4d"
  light-bg-elevated: "#e8e4d8"
  light-bg-raised: "#faf8f2"
  scrim: "rgba(0,0,0,0.55)"
  qr-paper: "#ffffff"
typography:
  ui:
    fontFamily: "IBM Plex Sans, Segoe UI, sans-serif"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.4
    letterSpacing: "normal"
  mono:
    fontFamily: "IBM Plex Mono, ui-monospace, monospace"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "normal"
  title:
    fontFamily: "IBM Plex Sans, Segoe UI, sans-serif"
    fontSize: "22px"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "-0.02em"
rounded:
  sm: "4px"
  md: "6px"
  lg: "10px"
  full: "999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "24px"
components:
  button:
    backgroundColor: "{colors.bg-elevated}"
    textColor: "{colors.text}"
    rounded: "{rounded.md}"
    padding: "6px 10px"
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.bg-sunken}"
    rounded: "{rounded.md}"
    padding: "6px 12px"
---

## Overview

Operate-mode product UI. Dark-first warm charcoal with a single phosphor-green accent for connect/primary. IBM Plex Sans for chrome, IBM Plex Mono for hosts, paths, and permissions. Tight groups, quiet chrome, no emoji-as-icons. FileZilla workflow (sites, quick connect, path bar) without mimicking its chrome.

Incumbent anti-references: GitHub Primer clone, Inter, rainbow emoji toolbar, always-on log + quick-connect stacking, 3px accent rails on list rows, bright blue status strip.

## Colors

Dark: olive-black surfaces (`#121410` / `#1c1f1a` / `#0c0e0b`), sage secondary text, green accent only on primary actions, selection, and online. Semantic danger/warning/info; never gray text on colored fills.

Light: warm paper `#f3f0e8`, ink `#1c1f18`, forest accent `#0f7a4d`. Same component geometry.

## Typography

One UI family (IBM Plex Sans) at 13px for dense chrome; 14px on forms. Titles 22px/600. Mono only for host strings, paths, keys, audit IPs. Scale: 11 / 12 / 13 / 14 / 16 / 22 (11 for chips and counts only; explanatory prose starts at 12). No all-caps micro-labels.

## Layout

App shell: 40px header → optional quick-connect → optional log → tab strip → main (280px site list + detail or session). Status bar is a quiet footer, not a brand billboard. Collapse secondary chrome by default. Breakpoints: stack header and hide extra file columns at 768 / 1024.

## Elevation & Depth

1px borders, 0 8px 28px shadows on overlays (offset + blur). No glow halos. Login card sits on a faint grid, not a gradient mash.

## Shapes

Radius 6px controls, 10px dialogs. Full-round (999px) is reserved for true pills: group chips, the upload progress track, scrollbar thumbs. Focus ring 2px accent, 2px offset. Icons: 16px stroke SVGs, 1.75 weight, round caps, drawn from the inline `#i-*` sprite — never Unicode glyphs or emoji.

## Components

Buttons: default (surface + border), primary (accent fill, dark text), danger (transparent + danger border/text), ghost in toolbars. Inputs share height 28px chrome / 36px login. Tabs are underlines, not floating pills. Server rows: hover fill, selected fill — no thick left rail. Empty Site Manager teaches: add a server or quick-connect.

## Do's and Don'ts

- Do: one primary action per cluster (SSH or Sign in).
- Do: persist density, theme, and chrome toggles in localStorage.
- Don't: Inter, purple gradients, nested cards, emoji icons, uppercase letter-spacing labels.
- Don't: show Users / Audit / Webhooks as equal peers to Site Manager — park them in Admin.
