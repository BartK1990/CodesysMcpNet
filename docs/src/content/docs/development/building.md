---
title: Building from source
description: Build and run the server, and work on this documentation.
---

## Server

Requires the [.NET 10 SDK](https://dotnet.microsoft.com/download/dotnet/10.0).

```bash
dotnet run --project CodesysMcpServer.Web --launch-profile CodesysMcpServer
```

Publish the same packages the release workflow builds:

```bash
# x64 (framework-dependent)
dotnet publish CodesysMcpServer.Web -c Release -r win-x64 --self-contained false -o publish/x64

# portable (self-contained single file)
dotnet publish CodesysMcpServer.Web -c Release -r win-x64 --self-contained true \
  -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true \
  -p:EnableCompressionInSingleFile=true -o publish/portable
```

The Structured Text parser can be tested without CODESYS:

```bash
python CodesysMcpServer.Web/Scripts/selftest.py
```

## Documentation

This site is built with [Starlight](https://starlight.astro.build/) from the `docs/` folder and
published to GitHub Pages by `.github/workflows/docs.yml` on every push to `master` that
touches `docs/` (or manually from the Actions tab).

```bash
cd docs
npm ci
npm run dev        # http://localhost:4321/CodesysMcpNet/
npm run build
```

### Screenshots

The screenshots in `docs/src/assets/screenshots/` are generated with Playwright from the real
web UI, with sample project data so they don't depend on a CODESYS installation:

```bash
# terminal 1
dotnet run --project CodesysMcpServer.Web --launch-profile CodesysMcpServer
# terminal 2
cd docs
npx playwright install chromium   # once
npm run screenshots
```

Re-run it after changing the web UI and commit the updated images.
