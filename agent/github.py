"""Thin GitHub REST client — issue comments and release-asset uploads.

Auth is the workflow's own GITHUB_TOKEN (env GH_TOKEN). REPO is "owner/name".
"""
import json
import os
import time
import urllib.request
import urllib.error

API = "https://api.github.com"
UPLOADS = "https://uploads.github.com"


def _repo():
    r = os.environ["REPO"]
    return r.split("/", 1)


def _token():
    t = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not t:
        raise RuntimeError("no GH_TOKEN / GITHUB_TOKEN in env")
    return t


def _req(method, url, *, data=None, headers=None, parse=True):
    h = {
        "Authorization": f"Bearer {_token()}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "empire-clip-editor",
    }
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = resp.read()
                return json.loads(body) if parse and body else body
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:400]
            if e.code in (403, 429, 500, 502, 503) and attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            raise RuntimeError(f"GitHub {method} {url} -> {e.code}: {detail}") from None
        except urllib.error.URLError:
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            raise


def get_issue(number):
    owner, repo = _repo()
    return _req("GET", f"{API}/repos/{owner}/{repo}/issues/{number}")


def list_comments(number):
    owner, repo = _repo()
    out, page = [], 1
    while True:
        batch = _req(
            "GET",
            f"{API}/repos/{owner}/{repo}/issues/{number}/comments?per_page=100&page={page}",
        )
        out.extend(batch)
        if len(batch) < 100:
            return out
        page += 1


def comment(number, body):
    owner, repo = _repo()
    data = json.dumps({"body": body}).encode()
    return _req(
        "POST",
        f"{API}/repos/{owner}/{repo}/issues/{number}/comments",
        data=data,
        headers={"Content-Type": "application/json"},
    )


def _get_release_by_tag(tag):
    owner, repo = _repo()
    try:
        return _req("GET", f"{API}/repos/{owner}/{repo}/releases/tags/{tag}")
    except RuntimeError as e:
        if "404" in str(e):
            return None
        raise


def upload_release_asset(tag, name, path, *, title=None, notes=""):
    """Create (or reuse) a release for `tag` and attach `path` as `name`.

    Returns the public browser_download_url.
    """
    owner, repo = _repo()
    rel = _get_release_by_tag(tag)
    if rel is None:
        data = json.dumps(
            {"tag_name": tag, "name": title or tag, "body": notes, "make_latest": "false"}
        ).encode()
        rel = _req(
            "POST",
            f"{API}/repos/{owner}/{repo}/releases",
            data=data,
            headers={"Content-Type": "application/json"},
        )

    # Drop any existing asset with the same name so re-runs replace cleanly.
    for a in rel.get("assets", []):
        if a.get("name") == name:
            _req("DELETE", f"{API}/repos/{owner}/{repo}/releases/assets/{a['id']}", parse=False)

    with open(path, "rb") as fh:
        blob = fh.read()
    asset = _req(
        "POST",
        f"{UPLOADS}/repos/{owner}/{repo}/releases/{rel['id']}/assets?name={name}",
        data=blob,
        headers={"Content-Type": "video/mp4"},
    )
    return asset["browser_download_url"]
