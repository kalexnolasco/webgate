# SSH Terminal

## Opening a Terminal

From the Site Manager, click **SSH** on any server. A new tab opens with a full terminal.

## Features

- **xterm.js** -- real terminal emulator, not a text area
- **Auto-resize** -- terminal adapts to window size
- **Copy/paste** -- Ctrl+C/Ctrl+V (or right-click)
- **Multiple tabs** -- open several terminals simultaneously
- **Web links** -- clickable URLs in terminal output
- **Color support** -- full 256-color and true-color
- **Search the scrollback** -- `Ctrl+Shift+F`

## Searching the scrollback

`Ctrl+Shift+F` opens a search bar over the terminal. `Enter` goes to the next match,
`Shift+Enter` to the previous one, `Esc` closes it and hands the keyboard back to the
shell. A search that matches nothing says so rather than doing nothing.

!!! note "Why not `Ctrl+F`"
    `Ctrl+F` is readline's *forward-char*, and a terminal that swallows it is a
    terminal that fights you. Same reason the command palette is on `Ctrl+Shift+P`
    and leaves `Ctrl+P` to previous-command.

## Quick Connect

Use the toolbar for one-off connections:

1. Fill in Host, Username, Password, Port
2. Click **Quickconnect**

## Terminal Theme

The terminal uses the **Tokyo Night** color scheme:

- Background: `#1a1b26`
- Foreground: `#c0caf5`
- Font: Consolas / Courier New, 13px
