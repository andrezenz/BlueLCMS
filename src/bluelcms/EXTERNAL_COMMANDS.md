# Opening measurements from external programs

Call the BlueLCMS executable with arguments as shown below. If BlueLCMS is
already running, the request is forwarded to that instance and its window is
brought to the foreground. File paths may be outside configured source folders.

## Open a file

Linux, with the installed command on PATH:

```bash
BlueLCMS --open "/path/to/sample.mzML"
```

Linux, using the default installed executable directly:

```bash
"$HOME/.local/bin/BlueLCMS" --open "/path/to/sample.mzML"
```

Windows PowerShell (adjust the executable path if installed elsewhere):

```powershell
& "C:\Program Files\BlueLCMS\BlueLCMS.exe" --open "C:\Data\sample.mzML"
```

Windows Command Prompt:

```text
"C:\Program Files\BlueLCMS\BlueLCMS.exe" --open "C:\Data\sample.mzML"
```

macOS, with the app installed in Applications:

```bash
"/Applications/BlueLCMS.app/Contents/MacOS/BlueLCMS" --open "/path/to/sample.mzML"
```

## Select a spectrum

Select a retention-time interval; all times are in **minutes**:

```bash
BlueLCMS --open "/path/to/sample.mzML" --start 2.35 --end 2.45
```

Select the nearest positive MS scan to a retention time:

```bash
BlueLCMS --open "/path/to/sample.mzML" --time 2.40 --polarity positive
```

Set the UV wavelength while opening an interval:

```bash
BlueLCMS --open "/path/to/sample.mzML" --start 2.35 --end 2.45 --wavelength 254
```

Use the same arguments after the Windows or macOS executable shown above.
`--polarity negative` selects negative scans for `--time`; with an interval it
focuses the corresponding mass panel. Both panels remain available.

## Source checkout

From the project directory on Linux/macOS:

```bash
.venv/bin/python launch.py --open "/path/to/sample.mzML" --start 2.35 --end 2.45
```

From the project directory in Windows PowerShell:

```powershell
& ".venv\Scripts\python.exe" "launch.py" --open "C:\Data\sample.mzML" --start 2.35 --end 2.45
```

## From another Python program

Pass an argument list rather than building a shell command. Paths with spaces
then work without additional quoting:

```python
import subprocess

executable = r"C:\Program Files\BlueLCMS\BlueLCMS.exe"
measurement = r"C:\Data\My sample.mzML"
subprocess.Popen([
    executable,
    "--open", measurement,
    "--start", "2.35",
    "--end", "2.45",
])
```

On Linux/macOS, set `executable` and `measurement` to the corresponding paths.
For a source checkout, put the Python executable and the absolute path to
`launch.py` before the options.

## Options and caching

- `--open FILE`: required for a file-opening request; supports mzML,
  gzip-compressed mzML, and BlueLCMS NPZ cache files.
- `--start MIN --end MIN`: select an interval; supply both, with end >= start.
- `--time MIN`: select the nearest individual MS scan instead of an interval.
- `--polarity positive|negative`: focus a panel and restrict nearest-scan lookup.
- `--wavelength NM`: UV wavelength between 1 and 2000 nm.

Times must be finite and non-negative. The view is selected after loading.

For an uncached file outside configured source folders, BlueLCMS asks whether to
cache its analysis data: **Yes** retains an offline copy, **No** opens it only for
this session, and **Cancel** leaves the current view unchanged. If needed, Yes
first asks for a cache folder. The original file is not moved. Existing caches
open without another prompt, including when the original file is unavailable.
