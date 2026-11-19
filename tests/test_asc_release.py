"""Tests for scripts/asc_release.py's prepare step. Run from the repo root: python3 -m unittest"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import asc_release  # noqa: E402


def version(vid, string, state):
    return {"id": vid, "attributes": {"versionString": string, "appVersionState": state}}


class FakeASC:
    """Answers the App Store Connect calls prepare makes, and records every change."""

    def __init__(self, versions, builds=None):
        self.versions = versions
        self.builds = builds or {}   # version id -> attached build number
        self.changes = []

    def __call__(self, method, path, body=None, params=None, quiet=False):
        if method == "GET" and path.endswith("/appStoreVersions"):
            return {"data": self.versions}
        if method == "GET" and path.endswith("/build"):
            vid = path.split("/")[3]
            n = self.builds.get(vid)
            return {"data": {"id": f"b{n}", "attributes": {"version": str(n)}} if n else None}
        if method == "GET" and path.endswith("/appStoreVersionLocalizations"):
            return {"data": []}
        self.changes.append((method, path))
        return {"data": {"id": "new"}}


class PrepareTests(unittest.TestCase):
    def run_prepare(self, fake, check_only=False):
        old = asc_release.asc
        asc_release.asc = fake
        try:
            return asc_release.prepare("app", "202701.5", "IOS", "notes", check_only=check_only)
        finally:
            asc_release.asc = old

    def test_stops_when_the_waiting_version_already_has_a_build(self):
        fake = FakeASC([version("v4", "202701.4", "PREPARE_FOR_SUBMISSION"),
                        version("v3", "202701.3", "READY_FOR_SALE")], builds={"v4": 17})
        with self.assertRaises(SystemExit):
            self.run_prepare(fake, check_only=True)
        self.assertEqual(fake.changes, [])

    def test_a_rejected_version_with_a_build_takes_the_new_release(self):
        fake = FakeASC([version("v4", "202701.4", "REJECTED"),
                        version("v3", "202701.3", "READY_FOR_SALE")], builds={"v4": 17})
        self.assertEqual(self.run_prepare(fake), "v4")

    def test_reuses_a_waiting_version_with_no_build(self):
        fake = FakeASC([version("v4", "202701.4", "PREPARE_FOR_SUBMISSION"),
                        version("v3", "202701.3", "READY_FOR_SALE")])
        self.assertEqual(self.run_prepare(fake), "v4")
        self.assertIn(("PATCH", "/v1/appStoreVersions/v4"), fake.changes)

    def test_creates_a_version_when_none_is_waiting(self):
        fake = FakeASC([version("v3", "202701.3", "READY_FOR_SALE")])
        self.assertEqual(self.run_prepare(fake), "new")
        self.assertIn(("POST", "/v1/appStoreVersions"), fake.changes)

    def test_still_stops_while_a_version_is_in_review(self):
        fake = FakeASC([version("v4", "202701.4", "WAITING_FOR_REVIEW")])
        with self.assertRaises(SystemExit):
            self.run_prepare(fake, check_only=True)


if __name__ == "__main__":
    unittest.main()
