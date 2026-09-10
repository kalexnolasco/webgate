"""Company branding, set once by an admin and seen by everyone.

Open source deployed inside a company wants to look like that company: its name, its
colours, its logo on the login screen, its icon in the browser tab. This is that,
owned by the admin panel rather than by a rebuild.

Images live in the database rather than on disk. `compose.ha.yml` runs stateless
workers behind a load balancer, so a file written by one of them would be missing on
the next request; a row is there for all of them, and travels in the backup for free.
"""
