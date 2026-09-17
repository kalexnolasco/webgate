"""A throwaway SSH and SFTP server for the end-to-end tests.

Built on asyncssh, which webgate already depends on, so the browser tests need no
container, no root and no daemon. It serves a real shell over a PTY and a real SFTP
subsystem rooted wherever it is started, which is what makes "delete a file in the
browser and check the audit log names it" a test of the whole path rather than a mock.
"""

from __future__ import annotations

import asyncio
import contextlib
import fcntl
import os
import pty
import struct
import sys
import termios
from pathlib import Path

import asyncssh

USER = "demo"
PASSWORD = "demo"


def ensure_keys(directory: Path) -> Path:
    host_key = directory / "lab_host_key"
    if not host_key.exists():
        asyncssh.generate_private_key("ssh-ed25519").write_private_key(str(host_key))
    host_key.chmod(0o600)
    return host_key


async def _run_shell(process: object, banner: str) -> None:
    proc_any = process  # asyncssh's SSHServerProcess is untyped enough to fight about
    if proc_any.command:  # type: ignore[attr-defined]
        try:
            proc = await asyncio.create_subprocess_shell(
                proc_any.command,  # type: ignore[attr-defined]
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, err = await proc.communicate()
            if out:
                proc_any.stdout.write(out)  # type: ignore[attr-defined]
            if err:
                proc_any.stderr.write(err)  # type: ignore[attr-defined]
            proc_any.exit(proc.returncode or 0)  # type: ignore[attr-defined]
        except Exception as exc:  # pragma: no cover - lab plumbing
            proc_any.stderr.write(f"lab exec error: {exc}\r\n".encode())  # type: ignore[attr-defined]
            proc_any.exit(1)  # type: ignore[attr-defined]
        return

    try:
        size = proc_any.get_terminal_size()  # type: ignore[attr-defined]
        rows, cols = (size[1], size[0]) if size else (24, 80)
        master, slave = pty.openpty()
        fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        env = dict(os.environ)
        env.update(
            TERM="xterm-256color",
            PS1=f"\\[\\e[32m\\]{banner}\\[\\e[0m\\]:\\w\\$ ",
            HISTFILE="/dev/null",
        )
        proc = await asyncio.create_subprocess_exec(
            "/bin/bash",
            "--noprofile",
            "--norc",
            "-i",
            stdin=slave,
            stdout=slave,
            stderr=slave,
            env=env,
            start_new_session=True,
        )
        os.close(slave)

        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader()
        transport, _ = await loop.connect_read_pipe(
            lambda: asyncio.StreamReaderProtocol(reader), os.fdopen(os.dup(master), "rb", 0)
        )
        writer = os.fdopen(master, "wb", 0)
        proc_any.stdout.write(f"\r\n\x1b[36m*** {banner} ***\x1b[0m\r\n".encode())  # type: ignore[attr-defined]

        async def to_client() -> None:
            while True:
                data = await reader.read(4096)
                if not data:
                    break
                proc_any.stdout.write(data)  # type: ignore[attr-defined]
                await proc_any.stdout.drain()  # type: ignore[attr-defined]

        async def to_shell() -> None:
            while True:
                try:
                    data = await proc_any.stdin.read(4096)  # type: ignore[attr-defined]
                except asyncssh.TerminalSizeChanged as change:
                    # asyncssh delivers a window-change by raising it out of the read.
                    # A real sshd resizes the pty and carries on reading; letting it
                    # end this loop killed the shell on the client's first resize --
                    # which nothing noticed for as long as the terminal never resized.
                    fcntl.ioctl(
                        master,
                        termios.TIOCSWINSZ,
                        struct.pack("HHHH", change.height, change.width, 0, 0),
                    )
                    continue
                if not data:
                    break
                writer.write(data if isinstance(data, bytes) else data.encode())

        tasks = [asyncio.create_task(to_client()), asyncio.create_task(to_shell())]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                task.cancel()
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            await proc.wait()
            transport.close()
            with contextlib.suppress(Exception):
                writer.close()
        proc_any.exit(0)  # type: ignore[attr-defined]
    except (asyncssh.BreakReceived, asyncssh.TerminalSizeChanged):
        proc_any.exit(0)  # type: ignore[attr-defined]
    except Exception as exc:  # pragma: no cover - lab plumbing
        print(f"  ! session: {type(exc).__name__}: {exc}", flush=True)
        proc_any.exit(1)  # type: ignore[attr-defined]


class _LabServer(asyncssh.SSHServer):
    def begin_auth(self, username: str) -> bool:
        return True

    def password_auth_supported(self) -> bool:
        return True

    def validate_password(self, username: str, password: str) -> bool:
        return username == USER and password == PASSWORD

    def connection_requested(self, *_args: object) -> bool:
        return True  # so it can also act as a jump host


async def serve(port: int, root: Path, banner: str = "lab") -> None:
    await asyncssh.listen(
        "127.0.0.1",
        port,
        server_factory=_LabServer,
        server_host_keys=[str(ensure_keys(root))],
        process_factory=lambda p: _run_shell(p, banner),
        sftp_factory=asyncssh.SFTPServer,
        encoding=None,
        reuse_address=True,
    )
    print(f"lab listening on 127.0.0.1:{port}", flush=True)
    await asyncio.Event().wait()


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 2222
    root = Path(sys.argv[2]) if len(sys.argv) > 2 else Path.cwd()
    banner = sys.argv[3] if len(sys.argv) > 3 else "lab"
    try:
        asyncio.run(serve(port, root, banner))
    except (KeyboardInterrupt, SystemExit):
        sys.exit(0)


if __name__ == "__main__":
    main()
