"""Pre-warms the EXE artifact cache so the first user request is instant."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from package_builder.release_catalog import find_artifact
from routers.packages import _download_or_cache

_, artifact = find_artifact("exe", "x64")
if not artifact:
    print("warm_cache: no exe artifact found in release catalog")
    sys.exit(0)

url = str(artifact["url"])
sha256 = artifact.get("sha256")
print(f"warm_cache: downloading {url}")
data = _download_or_cache(url, sha256, "exe")
print(f"warm_cache: done, {len(data)} bytes cached")
