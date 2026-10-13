#!/usr/bin/env python3
"""Release helper for the shared App Store release workflow.

Subcommands:
  next-version  Work out the next YYYYMM.N version from git tags and the date.
  notes         Turn a commit message into "What's New" text.
  prepare       Check the version against App Store Connect and create/update
                the App Store version with its "What's New" text.
  attach        Wait for the Xcode Cloud build to finish processing, then attach
                it to the App Store version and set TestFlight "What to Test".
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.appstoreconnect.apple.com"
VERSION_RE = re.compile(r"^\d{6}\.\d+$")  # YYYYMM.N

# States where the App Store version can still be edited.
EDITABLE = {"PREPARE_FOR_SUBMISSION", "DEVELOPER_REJECTED", "REJECTED",
            "METADATA_REJECTED", "INVALID_BINARY"}
# States where Apple won't accept a new version until this one is finished.
BLOCKING = {"WAITING_FOR_REVIEW", "IN_REVIEW", "ACCEPTED",
            "PENDING_DEVELOPER_RELEASE", "PENDING_APPLE_RELEASE",
            "PROCESSING_FOR_DISTRIBUTION", "PROCESSING_FOR_APP_STORE",
            "WAITING_FOR_EXPORT_COMPLIANCE"}


def fail(msg):
    print(f"::error::{msg}")
    sys.exit(1)


def output(key, value):
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a") as f:
            f.write(f"{key}={value}\n")
    print(f"{key}={value}")


def parse(v):
    return tuple(int(x) for x in v.split("."))


def fmt(t):
    return ".".join(str(x) for x in t)


# ---------------------------------------------------------------- versioning

def next_version(floor):
    tags = subprocess.run(["git", "tag", "-l", "v*"], capture_output=True,
                          text=True, check=True).stdout.split()
    released = [parse(t[1:]) for t in tags if VERSION_RE.match(t[1:])]
    now = datetime.datetime.now(datetime.timezone.utc)
    candidates = [(now.year * 100 + now.month, 1), parse(floor)]
    if released:
        last = max(released)
        candidates.append((last[0], last[1] + 1))
        print(f"Latest release tag: v{fmt(last)}")
    version = fmt(max(candidates))
    if not VERSION_RE.match(version):
        fail(f"Generated version '{version}' is not valid")
    if f"v{version}" in tags:
        fail(f"Tag v{version} already exists")
    return version


def release_notes(message):
    lines = message.strip().splitlines()
    # A merged PR's first line is "Merge pull request #.."; the PR title follows.
    if lines and lines[0].lower().startswith("merge pull request"):
        lines = lines[1:]
    text = "\n".join(lines)
    text = re.sub(r"\[release\]", "", text, flags=re.IGNORECASE)
    text = re.sub(r"[ \t]+\n", "\n", text).strip()
    text = re.sub(r"^[\s:\-–—]+", "", text)
    return (text or "Bug fixes and improvements.")[:4000]


# ---------------------------------------------------------- App Store Connect

def token():
    import jwt  # PyJWT
    now = int(time.time())
    return jwt.encode(
        {"iss": os.environ["ASC_ISSUER_ID"], "iat": now, "exp": now + 1200,
         "aud": "appstoreconnect-v1"},
        os.environ["ASC_PRIVATE_KEY"], algorithm="ES256",
        headers={"kid": os.environ["ASC_KEY_ID"], "typ": "JWT"})


def asc(method, path, body=None, params=None):
    url = API + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {token()}",
        "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        fail(f"App Store Connect {method} {path} failed ({e.code}): {detail}")


def find_app(bundle_id):
    apps = asc("GET", "/v1/apps", params={"filter[bundleId]": bundle_id})["data"]
    if not apps:
        fail(f"No App Store Connect app with bundle ID {bundle_id}")
    return apps[0]["id"]


def state_of(v):
    a = v["attributes"]
    return a.get("appVersionState") or a.get("appStoreState")


def set_whats_new(version_id, notes):
    locs = asc("GET", f"/v1/appStoreVersions/{version_id}/appStoreVersionLocalizations")["data"]
    for loc in locs:
        try:
            asc("PATCH", f"/v1/appStoreVersionLocalizations/{loc['id']}", {
                "data": {"type": "appStoreVersionLocalizations", "id": loc["id"],
                         "attributes": {"whatsNew": notes}}})
            print(f"Set What's New for {loc['attributes']['locale']}")
        except SystemExit:
            # The first ever version of an app can't have What's New text.
            print(f"::warning::Could not set What's New for {loc['attributes']['locale']}")


def prepare(app_id, version, platform, notes, check_only=False):
    versions = asc("GET", f"/v1/apps/{app_id}/appStoreVersions",
                   params={"filter[platform]": platform, "limit": 200})["data"]

    editable = None
    for v in versions:
        s, vs = state_of(v), v["attributes"]["versionString"]
        if s in BLOCKING:
            fail(f"Version {vs} is {s}. Finish or cancel it in App Store Connect first.")
        if s in EDITABLE:
            editable = v
            continue
        # Apple compares number by number, so "202611" beats "2027.1.1".
        existing = tuple(int(x) for x in re.findall(r"\d+", vs))
        if existing and existing >= parse(version):
            fail(f"{version} is not higher than existing App Store version {vs} ({s}).")

    if check_only:
        return None
    if editable:
        vid = editable["id"]
        old = editable["attributes"]["versionString"]
        if old != version:
            asc("PATCH", f"/v1/appStoreVersions/{vid}", {
                "data": {"type": "appStoreVersions", "id": vid,
                         "attributes": {"versionString": version}}})
        print(f"Updated editable App Store version {old} -> {version}")
    else:
        vid = asc("POST", "/v1/appStoreVersions", {
            "data": {"type": "appStoreVersions",
                     "attributes": {"platform": platform, "versionString": version},
                     "relationships": {"app": {"data": {"type": "apps", "id": app_id}}}}})["data"]["id"]
        print(f"Created App Store version {version}")

    set_whats_new(vid, notes)
    return vid


def attach(app_id, version_id, version, platform, notes, minutes):
    deadline = time.time() + minutes * 60
    build = None
    while time.time() < deadline:
        builds = asc("GET", "/v1/builds", params={
            "filter[app]": app_id,
            "filter[preReleaseVersion.version]": version,
            "filter[preReleaseVersion.platform]": platform,
            "sort": "-uploadedDate", "limit": 1})["data"]
        if builds:
            state = builds[0]["attributes"]["processingState"]
            print(f"Build {builds[0]['attributes']['version']}: {state}")
            if state == "VALID":
                build = builds[0]
                break
            if state in ("FAILED", "INVALID"):
                fail(f"Build processing {state}")
        else:
            print(f"Waiting for Xcode Cloud to upload {version}…")
        time.sleep(60)
    if not build:
        fail(f"No processed build for {version} after {minutes} minutes. Check Xcode Cloud.")

    asc("PATCH", f"/v1/appStoreVersions/{version_id}/relationships/build",
        {"data": {"type": "builds", "id": build["id"]}})
    print(f"Attached build {build['attributes']['version']} to {version}")

    for loc in asc("GET", f"/v1/builds/{build['id']}/betaBuildLocalizations")["data"]:
        asc("PATCH", f"/v1/betaBuildLocalizations/{loc['id']}", {
            "data": {"type": "betaBuildLocalizations", "id": loc["id"],
                     "attributes": {"whatsNew": notes}}})
        print(f"Set TestFlight What to Test for {loc['attributes']['locale']}")


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("next-version"); n.add_argument("--floor", required=True)
    sub.add_parser("notes")
    pr = sub.add_parser("prepare")
    at = sub.add_parser("attach")
    for s in (pr, at):
        s.add_argument("--version", required=True)
        s.add_argument("--platforms", default="IOS", help="Space separated, e.g. 'IOS MAC_OS'")
        s.add_argument("--notes-file", required=True)
    pr.add_argument("--bundle-id", required=True)
    at.add_argument("--app-id", required=True)
    at.add_argument("--version-ids", required=True, help="PLATFORM=id pairs from prepare")
    at.add_argument("--minutes", type=int, default=90)
    a = p.parse_args()

    if a.cmd == "next-version":
        output("version", next_version(a.floor))
    elif a.cmd == "notes":
        print(release_notes(os.environ.get("COMMIT_MESSAGE", "")))
    else:
        notes = open(a.notes_file).read().strip()
        platforms = a.platforms.split()
        if a.cmd == "prepare":
            app_id = find_app(a.bundle_id)
            # Check every platform before changing any, so a bad version fails fast.
            for p in platforms:
                prepare(app_id, a.version, p, notes, check_only=True)
            ids = [f"{p}={prepare(app_id, a.version, p, notes)}" for p in platforms]
            output("app_id", app_id)
            output("version_ids", " ".join(ids))
        else:
            for pair in a.version_ids.split():
                p, vid = pair.split("=")
                attach(a.app_id, vid, a.version, p, notes, a.minutes)


if __name__ == "__main__":
    main()
