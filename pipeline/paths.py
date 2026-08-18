"""Heavy-data root resolution. Policy: large datasets (raw DEMs, region-scale
derived artifacts) live PRIMARILY on Google Drive, not the local disk.
Local data/raw is a transient cache, safe to delete at any time.

Resolution order:
1. $BLUESPOT_DATA_ROOT if set
2. Google Drive for desktop mount (bluespot-data/)
3. local data/raw (fallback only, e.g. offline)
"""
import os

def _drive():
    """Google Drive for desktop mount holding bluespot-data.

    Prefer a mount where the folder already exists and has data in it (a
    machine may have several accounts mounted); fall back to the first mount
    only when nothing has been created yet. $BLUESPOT_DATA_ROOT overrides.
    """
    import glob
    mounts = sorted(glob.glob(os.path.expanduser(
        "~/Library/CloudStorage/GoogleDrive-*/My Drive")))
    candidates = [os.path.join(m, "bluespot-data") for m in mounts]
    for c in candidates:
        if os.path.isdir(os.path.join(c, "dem")):
            return c
    for c in candidates:
        if os.path.isdir(c):
            return c
    return candidates[0] if candidates else None
_LOCAL = os.path.join(os.path.dirname(__file__), "..", "data", "raw")

def data_root():
    p = os.environ.get("BLUESPOT_DATA_ROOT")
    if p:
        return p
    d = _drive()
    if d and os.path.isdir(os.path.dirname(d)):
        os.makedirs(d, exist_ok=True)
        return d
    return _LOCAL
