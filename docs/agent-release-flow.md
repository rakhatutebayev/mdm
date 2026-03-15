# NOCKO MDM Agent Release Flow

NOCKO MDM no longer builds `MSI` or `EXE` installers on the production server.
The main end-user delivery path is now a single customer-specific `EXE` file with
embedded bootstrap configuration.

## Target Workflow

1. Develop locally.
2. Push code to GitHub.
3. Build Windows agent artifacts in GitHub Actions on a Windows runner.
4. Publish the base Windows release artifacts and update the manifest.
5. Deploy backend/frontend to production.
6. Production personalizes the base `EXE` by embedding tenant config and serves it as a single file.

## Why

- Windows installers are more reliable when built on Windows.
- Production should deploy and serve artifacts, not compile them.
- Customer-specific enrollment should happen through embedded bootstrap config, not by rebuilding Windows installers on the production server.

## Backend Contract

The backend reads the latest artifact catalog from:

- default: `backend/package_builder/agent_releases.json`
- override: `AGENT_RELEASES_MANIFEST`

Manifest format:

```json
{
  "channel": "stable",
  "generated_at": "2026-03-15T12:00:00Z",
  "releases": [
    {
      "version": "1.2.3",
      "artifacts": [
        {
          "format": "exe",
          "arch": "x64",
          "filename": "nocko-agent-1.2.3-x64-portable.exe",
          "url": "https://github.com/org/repo/releases/download/agent-v1.2.3/nocko-agent-1.2.3-x64-portable.exe",
          "sha256": "optional",
          "size_bytes": 12345678,
          "notes": "Optional human note"
        },
        {
          "format": "msi",
          "arch": "x64",
          "filename": "nocko-agent-1.2.3-x64.msi",
          "url": "https://github.com/org/repo/releases/download/agent-v1.2.3/nocko-agent-1.2.3-x64.msi"
        }
      ]
    }
  ]
}
```

Convention: newest release goes first.

## Portal Behavior

- The main portal action generates one customer-specific `EXE`.
- The backend downloads the latest base `EXE`, embeds tenant bootstrap JSON into the file, and returns the personalized result.
- `ZIP` can still exist as a fallback bootstrap path for internal use.
- If no base `EXE` artifact exists for the selected architecture, the portal blocks the download and shows an actionable error.

## Recommended GitHub Actions Responsibilities

- run backend/frontend tests
- build the Windows agent on `windows-latest`
- package `.msi` and `.exe`
- upload assets to GitHub Releases
- update `backend/package_builder/agent_releases.json`

Repository workflow added:

- `.github/workflows/agent-release.yml`

Current prerequisite:

- the actual agent source files must exist in `agent-gui/` (`main.py`, `agent.spec`, `make_icons.py`, installer files)
- right now the repository only contains `agent-gui/README.md`, so the workflow is intentionally set to fail early with a clear error until the source is added

## Production Responsibilities

- pull latest code
- deploy containers
- expose the package catalog and package download endpoints
- never install `nsis`, `wixl`, or other Windows packaging tools for runtime package generation
