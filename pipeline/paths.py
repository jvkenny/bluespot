"""Heavy-data root resolution. Policy: large datasets (raw DEMs, region-scale
derived artifacts) live PRIMARILY on Google Drive, not the local disk.
Local data/raw is a transient cache, safe to delete at any time.

Resolution order:
1. $BLUESPOT_DATA_ROOT if set
2. Google Drive for desktop mount (bluespot-data/)
3. local data/raw (fallback only, e.g. offline)
"""
import os

_DRIVE = os.path.expanduser(
    "~/Library/CloudStorage/GoogleDrive-jkenny2334@gmail.com/My Drive/bluespot-data")
_LOCAL = os.path.join(os.path.dirname(__file__), "..", "data", "raw")

def data_root():
    p = os.environ.get("BLUESPOT_DATA_ROOT")
    if p:
        return p
    if os.path.isdir(os.path.dirname(_DRIVE)):
        os.makedirs(_DRIVE, exist_ok=True)
        return _DRIVE
    return _LOCAL
