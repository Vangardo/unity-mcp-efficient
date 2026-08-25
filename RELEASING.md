# Release process

We publish semantic version tags from a clean `main` branch after CI passes.

## Prepare

1. Update the package version in `pyproject.toml`.
2. Move the relevant entries from `Unreleased` in `CHANGELOG.md` into a dated version section.
3. Update version-pinned installation examples in `README.md` when the public command changes.
4. Run the deterministic checks:

   ```bash
   uv sync --extra dev
   uv lock --check
   uv run pytest -q
   uv build
   ```

5. With MCP for Unity running over HTTP, repeat the benchmark and live smoke checks when compatibility or response handling changed.
6. Confirm that benchmark claims identify the upstream version and distinguish measured schema size from actual API billing.

## Publish

1. Merge the release commit into `main` and wait for CI.
2. Create an annotated `vX.Y.Z` tag on that commit.
3. Push the tag and create a GitHub Release from the matching changelog section.
4. Check the release archive, README installation command, and latest-release badge from a signed-out browser.

Do not move an existing release tag. Publish a patch release when a released artifact needs correction.
