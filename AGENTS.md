# BlueLCMS development workflow

- For each completed user-requested code change, increment the development
  version in `pyproject.toml`, add a corresponding entry to
  `src/bluelcms/CHANGELOG.md`, run appropriate checks, and create a local commit
  on `dev`. The user has requested this as the default workflow.
- Stage only changes belonging to the completed task; preserve unrelated work.
- Do not push to GitHub or publish a stable release unless explicitly requested.
  Pushing `dev` runs the workflow that allocates numbered development tags.
- Keep changelog entries newest first, with concise descriptions of visible
  changes and fixes. The changelog is bundled and shown under About.
- Keep `src/bluelcms/EXTERNAL_COMMANDS.md` synchronized with the external-open
  command interface; it is also shown under About.
