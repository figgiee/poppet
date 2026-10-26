# Publishing

Releases are built by `.github/workflows/release.yml` on every `v*` tag push: it
builds the wheel + sdist, creates the GitHub release, and publishes to PyPI.

The GitHub release step works with the default `GITHUB_TOKEN`. The PyPI step needs
one of these, configured once in the repository/PyPI:

## Option A — PyPI Trusted Publishing (recommended, no secrets)

1. Sign in to <https://pypi.org> and add a **pending trusted publisher** for the
   *new* project name:

   | Field | Value |
   |---|---|
   | PyPI project name | `cascadeur-mcp` |
   | Owner | `figgiee` |
   | Repository | `poppet` |
   | Workflow name | `release.yml` |
   | Environment | `pypi` |

2. In the GitHub repository, keep the `pypi` environment
   (Settings → Environments → `pypi`).
3. Remove the `password:` line from the `pypi-publish` step in
   `.github/workflows/release.yml` so the OIDC identity is used:

   ```yaml
   - uses: pypa/gh-action-pypi-publish@release/v1
     with:
       skip-existing: true
   ```

Then re-run the failed job:

```bash
gh run rerun 40417604766 --failed -R figgiee/poppet
```

## Option B — PyPI API token secret

1. Create a PyPI API token that can upload the `cascadeur-mcp` project (an
   account-scoped token works for a brand-new project name).
2. Add it as the repository secret `PYPI_API_TOKEN`
   (Settings → Secrets and variables → Actions).
3. Re-run the failed `release.yml` run as above.

The workflow already passes `password: ${{ secrets.PYPI_API_TOKEN }}`; the token
path is used when that secret is non-empty.

## Option C — publish manually

Build and upload from a machine that has a token:

```bash
python -m build --wheel --sdist
uv publish --token "$env:UV_PUBLISH_TOKEN" dist/*
# or: twine upload dist/*
```

`scripts/publish.sh` wraps this flow.

## Verifying a release

```bash
gh release view v1.0.0 -R figgiee/poppet
pip install --dry-run cascadeur-mcp==1.0.0
```

The release assets are named `cascadeur_mcp-1.0.0-py3-none-any.whl` and
`cascadeur_mcp-1.0.0.tar.gz`.
