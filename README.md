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
4. The lower plots show positive ions on the left and negative ions on the
   right. Each bar sums measured MS1 intensities in a **0.1 Th m/z bin** across
   scans in the inclusive selected interval. These are m/z distributions,
   not neutral-mass deconvolutions. MS2+ spectra and scans lacking polarity or
   usable time metadata are excluded. Missing polarity data is never guessed.

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

## Verification

```sh
QT_QPA_PLATFORM=offscreen python -m pytest
```

Tests use locally generated synthetic mzML, including binary decoding, DAD
extraction, retention-time conversion, MS1 filtering, polarity splitting,
region aggregation, and an offscreen desktop workflow.
