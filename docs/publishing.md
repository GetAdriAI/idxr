# Publishing to GitHub Pages

Use MkDocs to serve and publish these docs. The public repository already contains `mkdocs.yml` and the `docs/` directory, so GitHub Pages can build the site automatically.

## 1. Install MkDocs and the Material theme (optional)

```bash
pip install mkdocs mkdocs-material
```

Material is optional—the default theme works out of the box—but it provides a polished navigation chrome.

## 2. Preview locally

```bash
cd indexer
mkdocs serve
```

Navigate to <http://127.0.0.1:8000/> to browse the site. MkDocs reloads pages whenever you edit Markdown files.

## 3. Publish with GitHub Actions (recommended)

1. In the public repo at `GetAdriAI/idxr`, enable GitHub Pages with the **GitHub Actions** source.
2. Add a workflow (for example `.github/workflows/docs.yml`):

```yaml
name: Build docs

on:
  push:
    branches: [main]
  workflow_dispatch:

jobs:
  deploy:
    permissions:
      contents: write
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install mkdocs mkdocs-material
      - run: mkdocs gh-deploy --force
```

3. Merge to `main`. The workflow pushes the rendered site to the `gh-pages` branch that GitHub Pages serves.

## 4. Manual publish (fallback)

If you prefer not to use Actions, run:

```bash
mkdocs gh-deploy --force
```

This command builds the static site, pushes it to the `gh-pages` branch of the active remote, and prints the Pages URL.

## 5. Keeping docs in sync

- Run `mkdocs build --strict` in CI to catch broken links before merging.
- Update the docs whenever you add or rename CLI flags. The navigation already groups pages by command and argument.
- After publishing a new package release, sync the public repo (using `scripts/sync_public_repo.sh --tag`) so the documentation reflects the same version that shipped to PyPI.
