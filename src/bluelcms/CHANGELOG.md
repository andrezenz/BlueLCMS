# BlueLCMS changelog

Versions use Python's development-version notation in the app (for example,
`1.0.2.dev4`) and GitHub prerelease tags (for example, `v1.0.2-dev.4`).

## 1.0.2.dev4

- Added **About → Changelog…**, available offline in source and packaged apps.
- Added **About → External program commands…** with Windows, Linux, macOS,
  source-checkout, and Python integration examples.
- Added a maintained version history and automatic changelog inclusion in
  development workflows and release notes.

## 1.0.2.dev3

- Added a vertical cursor guideline with a four-decimal m/z readout in both
  mass-spectrum plots.
- Kept the cursor overlay through histogram redraws without affecting zoom.

## 1.0.2.dev2

- Added automatic immutable numbered development releases alongside `dev-latest`.
- Added exact package-version and source-revision reporting in About.
- Added cursor-centered m/z zoom when scrolling over a mass-spectrum x-axis;
  scrolling inside a spectrum still controls intensity zoom.

## 1.0.2.dev1

- Added startup checks for newer stable releases and missing cache folders.
- Added persistent, default-on background source refresh every minute.
- Added queued Ctrl+click loading with `[i/n]` progress and single-click priority.
- Added pause/resume of partially loaded files, followed by background caching.
- Added recursive discovery and a folder-tree sidebar that preserves cached-only
  measurements and selection during background rescans.
- Added external-open commands and forwarding to an already-running instance,
  including a cache prompt for files outside configured source folders.
- Split the TIC toolbar control into independent positive and negative buttons.
- Added Windows application, installer, and bootstrapper icon configuration.

## 1.0.1

- Added the same version-selection interface to packaged and source apps.
- Added platform-package download and installation with a restart prompt.

## 1.0.0

- Added matched Agilent UV and Advion MS measurements, including TIC and optional
  expanded raw spectra.
- Kept cached measurements available when their original source is unavailable.
- Added source-only, source-plus-cache, and cache-only sidebar icons.
- Made cache expiration default to Never.
- Added About/version information and published-release selection.
