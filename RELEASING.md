# Releasing

Publishing used to be manual, and it drifted: the repository reached v2.1.2 while
PyPI still served 0.5.2, Docker Hub's `latest` pointed at 0.5.3, and the public demo
ran v0.5.3 — the line the README calls legacy and unsupported. Everything below exists
so that cannot happen again.

## Cutting a release

```bash
# 1. Version, in both places the tests check
echo "2.3.0" > VERSION
sed -i 's/^version = .*/version = "2.3.0"/' pyproject.toml

# 2. A CHANGELOG.md entry. The GitHub release body is this section verbatim,
#    and the release fails if there isn't one.
$EDITOR CHANGELOG.md && cp CHANGELOG.md docs/changelog.md

# 3. Local gate — the same checks CI runs
uv run ruff check src/ tests/ scripts/
uv run ruff format --check src/ tests/ scripts/
uv run pytest tests/ -q

# 4. Tag and push
git commit -am "v2.3.0: ..." && git push origin main
git tag -a v2.3.0 -m "v2.3.0 — ..." && git push origin v2.3.0
```

Pushing the tag is the whole release. `.github/workflows/release.yml` then:

1. **verifies** the tag, `VERSION` and `pyproject.toml` agree, and that the changelog
   has a section for it;
2. **runs the full CI suite** on the tagged commit — tests on 3.11/3.12/3.13, lint,
   formatting, a Docker build that must actually start and answer, and a strict docs
   build. Nothing is published if any of it fails;
3. **publishes to PyPI** via trusted publishing;
4. **pushes `linux/amd64` and `linux/arm64` images** to Docker Hub as the version and
   as `latest`, and syncs the Docker Hub description from the README;
5. **creates the GitHub release**, with the changelog section as its body.

Publishing the release then triggers `demo.yml`, which deploys
[webgate-demo.fly.dev](https://webgate-demo.fly.dev/) and fails if the demo does not
come back reporting the version just released.

## One-time setup

None of these are stored in the repository, and none of them should ever be pasted
into a chat window or a commit.

### PyPI — no token needed

webgate publishes with [trusted publishing](https://docs.pypi.org/trusted-publishers/),
so there is no API token to leak or rotate. On
<https://pypi.org/manage/project/webgate/settings/publishing/>, add a publisher:

| Field | Value |
|---|---|
| Owner | `kalexnolasco` |
| Repository | `webgate` |
| Workflow | `release.yml` |
| Environment | `pypi` |

Then in the repository, **Settings → Environments → New environment → `pypi`**. Adding
required reviewers there turns every publish into an approval step, which is worth it.

### Docker Hub

**Settings → Secrets and variables → Actions**, as repository secrets:

| Secret | Value |
|---|---|
| `DOCKERHUB_USERNAME` | your Docker Hub username |
| `DOCKERHUB_TOKEN` | an access token from <https://hub.docker.com/settings/security> — scope it to *Read, Write*, not *Admin* |

### The demo (Fly.io)

A token, and the app's own secret key:

```bash
flyctl tokens create deploy --app webgate-demo     # -> repository secret FLY_API_TOKEN
flyctl secrets set WEBGATE_SECRET_KEY=$(openssl rand -hex 32) --app webgate-demo
```

The second one is not optional: since v2.2.0 webgate refuses to start under the shipped
default key on any address other than loopback, so a deploy without it replaces a
working demo with a crash loop. `demo.yml` checks for it before deploying and stops
with that message rather than breaking the demo.

Create the `demo` environment the same way as `pypi` if you want deploys to be gated.

## Republishing a release

If a publish fails halfway — Docker Hub rate limits, an expired token — re-run it
without cutting a new version: **Actions → Release → Run workflow**, and give it the
existing tag. PyPI will refuse a version it already has, which is correct; the other
steps are idempotent.

## What is checked, and what is not

CI runs tests, lint, formatting, a real Docker start-up, and a strict docs build.

It does **not** run pyright. Strict mode currently reports around a hundred findings,
roughly eighty of them `reportUnknown*` where asyncssh and ldap3 ship no type
information, so a zero-tolerance gate would only ever be red. Run it locally and watch
whether the count moves:

```bash
uv run pyright src/
```
