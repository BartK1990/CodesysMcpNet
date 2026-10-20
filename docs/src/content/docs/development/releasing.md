---
title: Releasing
description: How to publish a new version.
---

Releases are built by the manual **Release** workflow
(`.github/workflows/release.yml`).

## Version number

The version lives in exactly one place, `CodesysMcpServer.Web/CodesysMcpServer.Web.csproj`:

```xml
<Version>1.0.0</Version>
```

It is compiled into the executable and shown in the web UI (badge next to the title),
`GET /version`, `GET /health`, the Swagger UI and the startup log line. The release workflow
reads it to name the tag (`v1.0.0`) and the packages.

## Steps

1. Bump `<Version>` in the `.csproj` (e.g. `1.0.0` → `1.1.0`), commit and push to `master`.
2. On GitHub, open **Actions → Release → Run workflow**, choose the branch, optionally tick
   *pre-release* or *draft*, and run it.
3. The workflow, on `windows-latest`:
   - reads the version and fails if tag `v<version>` already exists (so a forgotten bump can't
     overwrite a release),
   - publishes the **x64** (framework-dependent) and **portable** (self-contained,
     single-file) builds,
   - zips them with `README.md` and `LICENSE.txt`, writes `SHA256SUMS.txt`,
   - creates the GitHub release `v<version>` with the zips attached and generated release
     notes.

The packages are also attached to the workflow run as an artifact.
