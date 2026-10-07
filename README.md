# ⌊Blue⌋ LCMS

Standalone LC-MS analysis desktop application, with a Qt-independent analysis
module for future integration with SynthesisMapper.

## License

BlueLCMS is available under the [MIT License](LICENSE). Commercial use is
welcome. If you use BlueLCMS commercially, please consider contacting the
maintainer; this request is voluntary and is not a license condition.

See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for dependency licenses.

## Updates

Use the **Update** menu to check the official GitHub repository, fast-forward
to `dev` or `stable`, or select an immutable `v*` release tag. Updates refuse
checkouts with local source changes, use only the official repository URL, and
reinstall project dependencies before offering a restart. Application settings,
raw data, caches, and integration sidecars are not changed by an update.

## Installers

Users download the small bootstrap installer from the project website, not from
the repository. It prompts for `stable` or `development`, then downloads the
matching full application package from GitHub Releases. Pushing a `v*` tag
builds the stable packages; every `dev` push rebuilds the moving `dev-latest`
prerelease. Both releases contain a Linux x86_64 archive, a macOS disk image,
and a Windows installer, built on their native GitHub-hosted runners.

Run the manually triggered **Build website installer** workflow when a new
website bootstrap download is needed. Its output is an Actions artifact for
uploading to the project website; it is never committed to Git or published as
a GitHub release asset. Packaged applications also check GitHub Releases on
their first launch and offer to open the latest release download page when a
newer version is available.

On Linux, extract the release archive and run `sh install.sh` from the extracted
directory to install the application and desktop entry under `~/.local`.

## Install and run

Python 3.12 or newer is required.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
bluelcms
# Alternatively: python -m bluelcms
```

## Using the viewer

### Linux application-menu installation

Run the executable installer from this checkout:

```sh
./install.py
```

It creates `.venv` if necessary, installs the current project and dependencies,
and writes `bluelcms.desktop` into
`${XDG_DATA_HOME:-~/.local/share}/applications`. No administrator privileges
are needed. Open **⌊Blue⌋ LCMS** from your desktop's application menu afterward.

The shortcut uses this checkout's `.venv` and imports directly from its `src`
directory. Every launch uses the **currently checked-out local branch and its
local edits**. It does not fetch, pull, or switch Git branches. Rerun the
installer if dependencies change or the checkout moves. Running it again
updates the existing shortcut. To remove the shortcut, delete
`bluelcms.desktop` from the applications directory above.

### Viewing data

1. Use **Settings → Manage mzML locations…** to add one or more folders. The
   locations are remembered between sessions and their files appear together in
   the sidebar; `.mzML` and gzip-compressed `.gz` mzML files are supported.
   extensions are matched case-insensitively. Use **Refresh file list** after
   adding files.
   Files beginning with `yyyy_mm_dd` sort newest first. Toggle **Settings →
   Show date prefix in file list** to hide that prefix in sidebar labels without
   renaming source files.
2. Select a file to load it in the background. The upper plot extracts the
   nearest recorded wavelength to **254 nm** from full DAD spectra whose
   wavelength arrays cover that target. Its title reports the actual wavelength.
   Retention times are normalized to minutes; UV values retain their recorded
   scale. An unavailable message appears if usable DAD spectra are absent.
3. Left-drag across the upper plot to select a time interval, or resize
   the shaded region using its edge handles. Initially the full UV time interval is selected.
4. The lower plots show positive ions above negative ions. Each bar sums measured MS1 intensities in a **0.1 Th m/z bin** across
   scans in the inclusive selected interval. These are m/z distributions,
   not neutral-mass deconvolutions. MS2+ spectra and scans lacking polarity or
   usable time metadata are excluded. Missing polarity data is never guessed.

## Display Controls

- Select multiple files in the sidebar with Ctrl-click or Shift-click to overlay
  their UV traces. The matching MS1 contributions use the same color in the
  mass plots. Contributions that share a rendered mass pixel are stacked in
  color rather than overdrawn, so every selected measurement remains visible.
- Change **Wavelength** to redraw all selected DAD traces without rereading the
  source files. Choose **DAD heatmap** to view wavelength versus retention time
  for the first selected run.
- Positive and negative histograms are stacked and share their m/z navigation.
  When zoomed out, all 0.1 Th source bins that fall into one screen pixel are
  summed into that pixel's bar. Zooming back in restores the source resolution.
  The strongest non-overlapping visible peaks are labelled with their original
  0.1 Th bin m/z, never a screen-pixel average.
- In mass plots, the wheel scales intensity only and keeps zero fixed at the
  bottom of the y-axis. Left-drag an m/z interval to
  zoom both mass graphs to that range; double-click restores the full m/z view.
  Drag the shaded UV interval or its edge handles to recompute the mass plots.
- While files, remote folders, or a new selection are being read, graphs are
  greyed out with an animated loading label. The chosen folder remains stored
  between sessions.

The active file's decoded MS1 arrays are held in memory to support repeated
selection. Loading and histogram computation run in background workers.
The reader currently expects full DAD spectra with standard mzML wavelength
and intensity arrays; it does not reconstruct UV signals from MS data or
vendor-specific external DAD files.

### AFP-mounted remote folders (Linux)

1. Connect to `afp://server/share` in your system file manager and authenticate
   there. Keep the share mounted while using ⌊Blue⌋ LCMS.
2. In ⌊Blue⌋ LCMS, choose **Settings → Choose mounted remote folder…**. Open the
   share (usually named `afp-volume:host=…,volume=…`) and select the directory
   containing the mzML files. The picker exposes the GVFS mount directory even
   when the native folder dialog does not show network locations.
3. Select a file as usual. Directory listing and mzML loading run in background
   workers. After a disconnect, reconnect in the file manager and use
   **Settings → Refresh file list**. If the mount path changes, reselect it.

This requires the desktop's AFP backend and GVFS FUSE bridge (on Ubuntu/Debian,
typically `gvfs-backends` and `gvfs-fuse`). ⌊Blue⌋ LCMS locates shares through
`$XDG_RUNTIME_DIR/gvfs`, `/run/user/<uid>/gvfs`, or the legacy `~/.gvfs` path.
Shares mounted at regular paths such as `/mnt` or `/media` work with the normal
folder picker. ⌊Blue⌋ LCMS reads the mounted files directly and remembers the
selected path; authentication is handled by the desktop, not ⌊Blue⌋ LCMS.

### Debug terminal

Use **Settings → Open debug terminal…** to start a separate ⌊Blue⌋ LCMS instance
inside the system terminal. Python tracebacks and other standard output remain
visible there after that instance exits. This is interactive diagnostics only;
⌊Blue⌋ LCMS does not write log files.

### Local analysis cache

Choose **Settings → Choose local cache folder…** to select a persistent local
folder for compact mzML analysis caches. After a file has fully loaded,
⌊Blue⌋ LCMS writes a compact local analysis cache in the background. It retains
full DAD spectra plus native-grid MS1 intensities, scan times, and polarities,
while omitting unused mzML XML and metadata. Later selections use that local
cache instead of reading the original mzML. A save icon and **Cached locally**
tooltip identify cached entries in the sidebar. Cache entries are written
atomically and include a hash of the full remote path, so equal filenames from
different shares cannot collide. Re-selecting the cache folder or deleting its
file makes the next load use the remote source again.

The graphs visibly grey out with an animated loading label while a file is
parsed. A persistent status-bar progress bar reports bytes read against the
selected file's size. After a remote parse succeeds, it switches to compacting
the local cache.

Set **Cache expiry** in the left sidebar to remove cached entries after a chosen
number of days; the default is seven days and zero disables automatic expiry.

For DAD-enabled mzML files, the UV trace appears progressively as spectra are
decoded. The title shows **(streaming)** until the full run is ready. The
complete, sorted trace replaces the preview when loading finishes; the heatmap
remains unavailable until that point.

Preview points are transferred in small batches and the graph redraw is capped
at roughly 13 frames per second, so a dense DAD run does not make the interface
sluggish while it streams.

⌊Blue⌋ LCMS reads each source only once. DAD points appear as their spectra are
encountered in the mzML stream, avoiding a second remote traversal before MS
analysis begins.

The same upper plot also shows dashed positive (green) and negative (red) MS1
total-ion-current traces on its right-hand axis as MS spectra are decoded. They
provide useful loading feedback before DAD spectra become available without
changing the UV signal scale.

Use the **MS TIC** toolbar toggle to persistently show or hide completed-run
TIC traces. Streaming TIC remains visible while a file is loading even when the
saved preference is off.

## UV Integrations

With exactly one fully loaded measurement selected, right-click inside the
shaded UV region and choose **Integrate**. The bottom **UV integrations** panel
lists its start/stop times, wavelength, absolute trapezoidal integral, and its
percentage of all listed integrals. Integrals are tied to their selected
wavelength and can be removed or cleared from the panel.

BlueLCMS does not modify mzML files. It saves records in a
`.mzML.bluelcms-integrations.json` sidecar beside a writable source. For AFP or
other read-only sources, it atomically falls back to
`${XDG_DATA_HOME:-~/.local/share}/BlueLCMS/integrations`. Sidecars include the
raw source path, size, and modification time; changed source files are marked
stale and their prior records are not loaded.

An uncached AFP entry shows a refresh-and-download icon and a **Downloading
remote source…** tooltip while it is being parsed or copied. Changing the
selection does not block the application: completed results from the old
selection are ignored. The active parser cannot be forcibly interrupted, so a
very slow abandoned remote read may still occupy one background worker until it
finishes.

## Verification

```sh
QT_QPA_PLATFORM=offscreen python -m pytest
```

Tests use locally generated synthetic mzML, including binary decoding, DAD
extraction, retention-time conversion, MS1 filtering, polarity splitting,
region aggregation, and an offscreen desktop workflow.
