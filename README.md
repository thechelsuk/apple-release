# apple-release

Shared App Store release pipeline for my iOS apps.

Push to `main` with `[Release]` in the commit message:

```
[Release] Bug fixes and improvements
```

1. GitHub Actions works out the next version (`YYYYMM.N`, e.g. `202701.1`, `202701.2`, `202702.1`).
2. It checks the version against App Store Connect and creates the App Store version. What's New is the commit message without `[Release]`.
3. It writes `MARKETING_VERSION`, commits, tags `vYYYYMM.N` and creates a GitHub release.
4. The tag starts Xcode Cloud: Test → Archive → TestFlight.
5. Actions waits for the build, attaches it to the App Store version and sets the TestFlight "What to Test" text.
6. If the repo has a `DEVNULL_SSH_KEY` secret, it announces the release on [dev-null.sh](https://dev-null.sh) with the version and App Store link.
7. You press **Submit for Review**.

## Adding an app

1. Copy `templates/app-store-release.yml` to `.github/workflows/` and set `bundle-id` and `project` (and `platforms: IOS MAC_OS` for Mac apps).
2. Copy `templates/ci_scripts/` next to the `.xcodeproj` (keep it executable).
3. Add the `ASC_KEY_ID`, `ASC_ISSUER_ID` and `ASC_PRIVATE_KEY` repo secrets, and optionally `DEVNULL_SSH_KEY` (see below).
4. In Xcode, create an Xcode Cloud workflow: Start Condition **Tag Changes** `v*`, Test + Archive (App Store Connect), Post-Action TestFlight Internal Testing.

## Announcing on dev-null.sh

Once the build is attached, the `announce` job posts a signed commit to dev-null.sh:

```
New version 202701.2 of Mltply coming soon. https://apps.apple.com/app/id1234567890
```

To turn it on, make a CI-only signing key, add `devnull-ci.pub` to GitHub as a **signing key** (https://github.com/settings/ssh/new), save `devnull-ci` as the `DEVNULL_SSH_KEY` repo secret, then delete both files:

```
ssh-keygen -t ed25519 -N '' -C devnull-ci -f devnull-ci
```

Without the secret the job is skipped.
