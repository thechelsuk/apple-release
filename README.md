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
6. You press **Submit for Review**.

## Adding an app

1. Copy `templates/app-store-release.yml` to `.github/workflows/` and set `bundle-id` and `project` (and `platforms: IOS MAC_OS` for Mac apps).
2. Copy `templates/ci_scripts/` next to the `.xcodeproj` (keep it executable).
3. Add the `ASC_KEY_ID`, `ASC_ISSUER_ID` and `ASC_PRIVATE_KEY` repo secrets.
4. In Xcode, create an Xcode Cloud workflow: Start Condition **Tag Changes** `v*`, Test + Archive (App Store Connect), Post-Action TestFlight Internal Testing.
