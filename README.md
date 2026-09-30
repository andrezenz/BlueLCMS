# BlueLCMS

Standalone LC-MS analysis desktop application, with a Qt-independent analysis
module for future integration with SynthesisMapper.

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
are needed. Open **BlueLCMS** from your desktop's application menu afterward.

The shortcut uses this checkout's `.venv` and imports directly from its `src`
directory. Every launch uses the **currently checked-out local branch and its
local edits**. It does not fetch, pull, or switch Git branches. Rerun the
installer if dependencies change or the checkout moves. Running it again
updates the existing shortcut. To remove the shortcut, delete
`bluelcms.desktop` from the applications directory above.

### Viewing data

1. Use **Settings → Choose mzML folder…**. The folder is remembered between
   sessions. Files directly in that folder appear in the sidebar; `.mzML`
   extensions are matched case-insensitively. Use **Refresh file list** after
   adding files.
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
   there. Keep the share mounted while using BlueLCMS.
2. In BlueLCMS, choose **Settings → Choose mounted remote folder…**. Open the
   share (usually named `afp-volume:host=…,volume=…`) and select the directory
   containing the mzML files. The picker exposes the GVFS mount directory even
   when the native folder dialog does not show network locations.
3. Select a file as usual. Directory listing and mzML loading run in background
   workers. After a disconnect, reconnect in the file manager and use
   **Settings → Refresh file list**. If the mount path changes, reselect it.

This requires the desktop's AFP backend and GVFS FUSE bridge (on Ubuntu/Debian,
typically `gvfs-backends` and `gvfs-fuse`). BlueLCMS locates shares through
`$XDG_RUNTIME_DIR/gvfs`, `/run/user/<uid>/gvfs`, or the legacy `~/.gvfs` path.
Shares mounted at regular paths such as `/mnt` or `/media` work with the normal
folder picker. BlueLCMS reads the mounted files directly and remembers the
selected path; authentication is handled by the desktop, not BlueLCMS.

### Debug terminal

Use **Settings → Open debug terminal…** to start a separate BlueLCMS instance
inside the system terminal. Python tracebacks and other standard output remain
visible there after that instance exits. This is interactive diagnostics only;
BlueLCMS does not write log files.

### AFP local cache

Choose **Settings → Choose local cache folder…** to select a persistent local
folder for AFP mzML caches. After an AFP-backed file has fully loaded,
BlueLCMS copies it to that folder in the background. Later selections use the
local copy instead of reading the AFP share. A save icon and **Cached locally**
tooltip identify cached entries in the sidebar. Cache entries use an atomic
copy and include a hash of the full remote path, so equal filenames from
different shares cannot collide. Re-selecting the cache folder or deleting its
file makes the next load use the remote source again.

The graphs visibly grey out with an animated loading label while a file is
parsed. A persistent status-bar progress bar reports bytes read against the
selected file's size. After a remote parse succeeds, it switches to byte-based
progress for the copy into the local cache.

For DAD-enabled mzML files, the UV trace appears progressively as spectra are
decoded. The title shows **(streaming)** until the full run is ready. The
complete, sorted trace replaces the preview when loading finishes; the heatmap
remains unavailable until that point.

BlueLCMS first makes a lightweight DAD-only pass that skips MS binary-array
decoding, then makes the full MS pass. Once the first pass establishes the full
UV time range, an orange cursor advances through that range with the currently
decoded MS1 scan.

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
