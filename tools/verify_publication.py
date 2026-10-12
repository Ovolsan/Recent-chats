"""Verify the public branch, release metadata and downloaded plugin bytes."""
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
REPO = "Ovolsan/Recent-chats"
API = "https://api.github.com/repos/" + REPO


def download(url):
    request = urllib.request.Request(url, headers={"User-Agent": "Recent-chats-verification"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def api(path):
    return json.loads(download(API + path))


def main():
    source = (ROOT / "recent_chats.plugin").read_bytes()
    metadata = {node.targets[0].id: ast.literal_eval(node.value)
                for node in ast.parse(source).body if isinstance(node, ast.Assign)
                and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id in {"__id__", "__version__"}}
    assert metadata["__id__"] == "recent_chats"
    version = metadata["__version__"]
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    repository = api("")
    assert repository["visibility"] == "public"
    assert repository["default_branch"] == "main"
    assert api("/git/ref/heads/main")["object"]["sha"] == commit
    assert api("/git/ref/tags/" + version)["object"]["sha"] == commit
    release = api("/releases/latest")
    assert release["tag_name"] == version and not release["draft"] and not release["prerelease"]
    assets = [asset for asset in release["assets"] if asset["name"] == "recent_chats.plugin"]
    assert len(assets) == 1
    asset = assets[0]
    raw_url = "https://raw.githubusercontent.com/" + REPO + "/main/recent_chats.plugin"
    digest = hashlib.sha256(source).hexdigest()
    assert download(raw_url) == source, "RAW plugin differs from local source"
    assert download(asset["browser_download_url"]) == source, "Release plugin differs from local source"
    assert asset["size"] == len(source)
    assert asset.get("digest") in (None, "sha256:" + digest)
    print(json.dumps({"repository": repository["html_url"], "commit": commit,
                      "version": version, "release": release["html_url"],
                      "asset": asset["browser_download_url"], "raw": raw_url,
                      "bytes": len(source), "sha256": digest, "result": "OK"}, indent=2))


if __name__ == "__main__":
    main()
