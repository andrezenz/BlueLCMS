## 1.0.2.dev29

- Reduced memory growth by sharing loaded array axes, releasing compact-load copies, and prompting native/Python release of unused measurements.

## 1.0.2.dev28

- Allowed the live UV spectrum cursor tool to work in ordinary UV trace mode as well as DAD heatmap mode.

## 1.0.2.dev27

- Added an About action/dialog that reports a bug through a prefilled GitHub issue, including version and runtime diagnostics.

elog

Versions use Python's development-version notation in the app (for example,
`1.0.2.dev4`) and GitHub prerelease tags (for example, `v1.0.2-dev.4`).

## 1.0.2.dev27

- Clicking a DAD heatmap point sets a temporary cursor guideline and shows the matching MS and UV spectra at that retention time.

## 1.0.2.dev24

- Made PuBu the default DAD heatmap palette, with zero-baseline absorption sensitivity, interactive drag zoom, double-click reset, and shift-wheel baseline adjustment.

## 1.0.2.dev26

- Added a solid DAD heatmap zoom rectangle, a vertical cursor guideline, and a togglable live UV spectrum window at the cursor.

## 1.0.2.dev25

- Made DAD heatmap sensitivity linear in the displayed absorption scale, eliminating harsh percentile jumps, while retaining the zero baseline.

## 1.0.2.dev24

- Made PuBu the default DAD heatmap palette, with zero-baseline absorption sensitivity, interactive drag zoom, double-click reset, and shift-wheel baseline adjustment.

## 1.0.2.dev22

- Removed the redundant mounted-remote folder action; **Manage mzML locations**
  now handles mounted and local folders together.
- Combined cursor snap units and range into one settings dialog, with screen
  pixels (±10 px) as the default for new preferences.
- Added a persistent, per-version changelog splash on first launch.
- Added persistent DAD heatmap intensity sensitivity and palette controls.

## 1.0.2.dev21

- Reduced contrast of the positive and negative TIC lines in cached and
  headlessly generated thumbnails; the UV trace color is unchanged.

## 1.0.2.dev20

- Increased cached and headless thumbnail trace width and switched to a light
  background with darker blue, green, and red trace colors.
- Versioned embedded previews so opening an older compact cache regenerates its
  PNG sidecars and standard desktop thumbnails in the updated style.

## 1.0.2.dev19

- Fixed Nautilus thumbnailing of compact `.npz` caches: detect the archive by
  its ZIP signature because GNOME's sandbox renames input files to a generic
  temporary basename before invoking the thumbnailer.
- Changed cached and headless previews to a light theme with thicker, darker
  colored UV and TIC traces.
- Changed the headless thumbnailer, which also invalidates the previous failed
  thumbnail records on upgrade so Files retries these caches.

## 1.0.2.dev18

- Added a startup migration that installs the Linux MIME and Nautilus thumbnailer
  registration. This supports upgrades from older packages whose updater only
  replaced app files and skipped `install.sh`.
- Cleared GNOME's remembered failed thumbnail records for mzML/cache files during
  migration, so Files retries previews it rejected before registration.
- Cleared GNOME's cached thumbnail failures for mzML and BlueLCMS cache files when
  the thumbnailer registration changes, so Files retries earlier failed previews.
- Asked users to restart Files after startup migration so it reloads the updated
  MIME and thumbnailer registration.

## 1.0.2.dev17

## 1.0.2.dev16

- Fixed Linux package updates skipping `install.sh`; in-app updates now refresh
  the desktop launcher, MIME database, and Nautilus thumbnailer registration.

## 1.0.2.dev15

- Added cached chromatogram PNG previews at 128, 256, and 512 px with nearest
  254 nm UV, positive TIC, and negative TIC overlaid in separate colors.
- Embedded previews in compact caches, exposed private PNG sidecars for other
  programs, and primed Ubuntu's standard thumbnail cache for original files.
- Registered a Nautilus thumbnailer for BlueLCMS cache, mzML, and gzip-mzML files;
  it reads embedded previews or parses unopened mzML headlessly on demand.

## 1.0.2.dev13

- Added screen-pixel cursor snapping. Its m/z search radius narrows as the user
  zooms in; m/z-based snapping remains available. Pixel units default to ±10
  screen pixels and have an independent persistent range.
- Made Ubuntu new-result notifications more robust: packaged builds explicitly
  include Qt D-Bus, `notify-send` is used when D-Bus is unavailable, and failed
  notifications no longer trigger GNOME's generic focus alert.

## 1.0.2.dev12

- Fixed Ubuntu notifications falling back to GNOME's generic “BlueLCMS is
  ready” message when Qt D-Bus was unavailable. Packaged builds now include
  PySide6.QtDBus, and Linux has a custom-title `notify-send` fallback.
- Notification failures no longer request window focus on Linux; clicking a
  supported notification still brings BlueLCMS forward.

## 1.0.2.dev11

- Changed sodium guide offsets to the Na⁺ ion mass.
- Added positive-direction NH₃, Na⁺, double-loss/adduct, and mixed guides to
  complement the negative-direction guides.

## 1.0.2.dev10

- Sorted measurements within each sidebar folder by newest filename/acquisition
  date first, with undated measurements following dated ones.

## 1.0.2.dev9

- Kept clicked-reference subtraction guide lines visible, but made their labels
  appear only while the pointer hovers within 8 screen pixels of a guide. The
  nearest guide label is shown; all guide labels hide when the pointer leaves.

## 1.0.2.dev8

- Fixed update restarts leaving the original session open: source, packaged, and
  Windows installer restart paths now explicitly close the old window.
- Shutdown cancels paused/active loaders and stops timers, preventing suspended
  workers and late callbacks from keeping or reopening the old session.
- The external-open endpoint is released before launching the replacement;
  failed launches leave the current session available.

## 1.0.2.dev7

- Added an m/z entry beside the TIC controls. Enter creates a toggleable extracted
  TIC button with a default ±2 m/z window; right-click changes the range or removes
  it. Buttons, ranges, and enabled states persist across restarts.
- Extracted traces are calculated in background workers and show positive and
  negative ion currents separately, even when the total TIC buttons are off.
- Added a shaded preview of the m/z interval while dragging to zoom a spectrum.
- On Linux desktops, new-file alerts now use a native **New result available**
  notification instead of triggering GNOME's generic ready message. Clicking the
  notification requests focus for the running app.

## 1.0.2.dev6

- Clicking a mass spectrum pins a reference mass and displays NH₃, 2NH₃, Na,
  2Na, and NH₃+Na subtraction guides with labeled m/z values.
- Single-loss guides have lower contrast than the mouse cursor; combined-loss
  guides are fainter still. Guides survive zoom and histogram redraws.
- Added persistent cursor snapping to the highest-intensity peak in an adjustable
  range, defaulting to ±5 m/z. Snapping also sets the clicked reference mass.

## 1.0.2.dev5

- Added a persistent, default-on **Alert when new measurements are found** setting.
- Background rescans announce new mzML files, request window focus, and signal
  taskbar attention without changing the current measurement or plots.
- Initial scans, repeated scans, cached originals, and returning files after a
  remote-share reconnect do not cause duplicate notifications.

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

- Added adjustable DAD heatmap color range and offset controls, plus mouse-wheel and reset support.

## 1.0.2.dev22

- Removed the redundant mounted-remote folder action; **Manage mzML locations**
  now handles mounted and local folders together.
- Combined cursor snap units and range into one settings dialog, with screen
  pixels (±10 px) as the default for new preferences.
- Added a persistent, per-version changelog splash on first launch.
- Added persistent DAD heatmap intensity sensitivity and palette controls.

## 1.0.2.dev21

- Reduced contrast of the positive and negative TIC lines in cached and
  headlessly generated thumbnails; the UV trace color is unchanged.

## 1.0.2.dev20

- Increased cached and headless thumbnail trace width and switched to a light
  background with darker blue, green, and red trace colors.
- Versioned embedded previews so opening an older compact cache regenerates its
  PNG sidecars and standard desktop thumbnails in the updated style.

## 1.0.2.dev19

- Fixed Nautilus thumbnailing of compact `.npz` caches: detect the archive by
  its ZIP signature because GNOME's sandbox renames input files to a generic
  temporary basename before invoking the thumbnailer.
- Changed cached and headless previews to a light theme with thicker, darker
  colored UV and TIC traces.
- Changed the headless thumbnailer, which also invalidates the previous failed
  thumbnail records on upgrade so Files retries these caches.

## 1.0.2.dev18

- Added a startup migration that installs the Linux MIME and Nautilus thumbnailer
  registration. This supports upgrades from older packages whose updater only
  replaced app files and skipped `install.sh`.
- Cleared GNOME's remembered failed thumbnail records for mzML/cache files during
  migration, so Files retries previews it rejected before registration.
- Cleared GNOME's cached thumbnail failures for mzML and BlueLCMS cache files when
  the thumbnailer registration changes, so Files retries earlier failed previews.
- Asked users to restart Files after startup migration so it reloads the updated
  MIME and thumbnailer registration.

## 1.0.2.dev17

## 1.0.2.dev16

- Fixed Linux package updates skipping `install.sh`; in-app updates now refresh
  the desktop launcher, MIME database, and Nautilus thumbnailer registration.

## 1.0.2.dev15

- Added cached chromatogram PNG previews at 128, 256, and 512 px with nearest
  254 nm UV, positive TIC, and negative TIC overlaid in separate colors.
- Embedded previews in compact caches, exposed private PNG sidecars for other
  programs, and primed Ubuntu's standard thumbnail cache for original files.
- Registered a Nautilus thumbnailer for BlueLCMS cache, mzML, and gzip-mzML files;
  it reads embedded previews or parses unopened mzML headlessly on demand.

## 1.0.2.dev13

- Added screen-pixel cursor snapping. Its m/z search radius narrows as the user
  zooms in; m/z-based snapping remains available. Pixel units default to ±10
  screen pixels and have an independent persistent range.
- Made Ubuntu new-result notifications more robust: packaged builds explicitly
  include Qt D-Bus, `notify-send` is used when D-Bus is unavailable, and failed
  notifications no longer trigger GNOME's generic focus alert.

## 1.0.2.dev12

- Fixed Ubuntu notifications falling back to GNOME's generic “BlueLCMS is
  ready” message when Qt D-Bus was unavailable. Packaged builds now include
  PySide6.QtDBus, and Linux has a custom-title `notify-send` fallback.
- Notification failures no longer request window focus on Linux; clicking a
  supported notification still brings BlueLCMS forward.

## 1.0.2.dev11

- Changed sodium guide offsets to the Na⁺ ion mass.
- Added positive-direction NH₃, Na⁺, double-loss/adduct, and mixed guides to
  complement the negative-direction guides.

## 1.0.2.dev10

- Sorted measurements within each sidebar folder by newest filename/acquisition
  date first, with undated measurements following dated ones.

## 1.0.2.dev9

- Kept clicked-reference subtraction guide lines visible, but made their labels
  appear only while the pointer hovers within 8 screen pixels of a guide. The
  nearest guide label is shown; all guide labels hide when the pointer leaves.

## 1.0.2.dev8

- Fixed update restarts leaving the original session open: source, packaged, and
  Windows installer restart paths now explicitly close the old window.
- Shutdown cancels paused/active loaders and stops timers, preventing suspended
  workers and late callbacks from keeping or reopening the old session.
- The external-open endpoint is released before launching the replacement;
  failed launches leave the current session available.

## 1.0.2.dev7

- Added an m/z entry beside the TIC controls. Enter creates a toggleable extracted
  TIC button with a default ±2 m/z window; right-click changes the range or removes
  it. Buttons, ranges, and enabled states persist across restarts.
- Extracted traces are calculated in background workers and show positive and
  negative ion currents separately, even when the total TIC buttons are off.
- Added a shaded preview of the m/z interval while dragging to zoom a spectrum.
- On Linux desktops, new-file alerts now use a native **New result available**
  notification instead of triggering GNOME's generic ready message. Clicking the
  notification requests focus for the running app.

## 1.0.2.dev6

- Clicking a mass spectrum pins a reference mass and displays NH₃, 2NH₃, Na,
  2Na, and NH₃+Na subtraction guides with labeled m/z values.
- Single-loss guides have lower contrast than the mouse cursor; combined-loss
  guides are fainter still. Guides survive zoom and histogram redraws.
- Added persistent cursor snapping to the highest-intensity peak in an adjustable
  range, defaulting to ±5 m/z. Snapping also sets the clicked reference mass.

## 1.0.2.dev5

- Added a persistent, default-on **Alert when new measurements are found** setting.
- Background rescans announce new mzML files, request window focus, and signal
  taskbar attention without changing the current measurement or plots.
- Initial scans, repeated scans, cached originals, and returning files after a
  remote-share reconnect do not cause duplicate notifications.

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
