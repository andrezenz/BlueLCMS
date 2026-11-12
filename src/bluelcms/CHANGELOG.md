## 1.0.3.dev3

- Added reaction-monitoring collections created from multiple selected measurements, with explicitly assigned elapsed reaction times, named targets, common retention windows and per-measurement window adjustments.
- Added endpoint-baseline integration, area/fraction/ratio/internal-standard progress plots, chromatogram overlays and a portable ZIP snapshot with JSON metadata and CSV results.
- Embed verified original AIA CDF files when available; offline and mzML UV snapshots retain lossless chromatogram arrays. Collections reopen without their original sources and support an optional full-chromatogram CSV copy export.

## 1.0.3.dev2

- Automatically hide mass-spectrum panes when selected measurements have no scans of the corresponding polarity. Chromatogram-only AIA and TIC-only measurements show no mass panes; saved manual visibility preferences are retained.
- Added a separate Integration toolbar below Display with interval integration, show-results, remove-selected, and clear actions, plus current wavelength/channel and interval feedback.
- Enable integration only for a valid nonzero interval on one loaded measurement and one recorded channel or UV wavelength; quiet MS intervals do not change pane visibility.

## 1.0.3.dev1

- Added Agilent `.AIA` folder and standalone `.cdf` chromatogram discovery, with one sidebar measurement per export, named channel overlays, recorded units, and channel selection.
- Added channel-specific integration and local offline caches that detect re-exported, added, or removed CDF channels. AIA exports remain read-only.
- Preserved negative absorbance values and reconstructed uniformly sampled retention times from delay/interval metadata when exported retention arrays are empty or zero-filled.
- Added external-open support for AIA/CDF and disabled unavailable wavelength/heatmap controls for chromatogram-only measurements.

## 1.0.2

- Added oligonucleotide charge-envelope deconvolution for selected intervals, with configurable mass/charge limits, a relative-signal results list, species-colored MS bins, and charge-state labels. A persistent highlight limit defaults to seven species per spectrum.
- Added adjustable DAD heatmap palettes, linear absorption scaling, baseline controls, drag zoom, cursor guidelines, and UV spectra at the cursor in heatmap and trace modes.
- Added time-click spectrum selection, zero-anchored UV intensity scrolling, and persistent Display-menu controls for positive and negative mass-spectrum panes. UV selection respects the UV spectrum visibility preference.
- Improved extracted TIC controls, mass-cursor snapping, and reference-mass guides for common ion offsets.
- Added external-program commands, bundled offline help and changelog, and prefilled GitHub bug reports with runtime diagnostics.
- Added cached chromatogram previews and Linux file-manager thumbnails, with improved desktop registration and new-measurement notifications.
- Improved measurement sidebar organization, memory release, and development/stable package version handling.

## 1.0.2.dev33

- Limited deconvolution coloring and charge labels to the strongest seven species per spectrum by default, with a persistent maximum in deconvolution settings; all species remain in the results list.
- Fixed UV trace and DAD clicks opening the UV spectrum dock when “UV spectrum at cursor” is disabled.
- Added persistent Display-menu toggles to show or hide the positive and negative ion mass-spectrum panes independently.

## 1.0.2.dev32

- Added a Deconvolute toolbar toggle for probable oligonucleotide charge-envelope matching in the selected interval, with right-click mass/charge limits and matching settings.
- Added a colored results list with neutral-mass estimates and relative assigned signal, matching spectrum-bin colors, and small polarity-aware charge-state labels.
- Kept deconvolution independent of display zoom, with bounded background calculations and stale-result rejection when the interval changes.

## 1.0.2.dev31

- Made scrolling over the UV trace plot zoom the y-axis while keeping zero fixed.

## 1.0.2.dev30

- Clicking a DAD or UV trace time now pins the UV spectrum and displays the corresponding positive and negative MS spectra at that time.

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
