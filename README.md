<h1 align="center">shotarochiba.id</h1>

Markdown source articles for Shotaro Chiba's personal technical blog.
The blog uses [shiori.rs](https://github.com/craftguild/shiori.rs), a filesystem Markdown CMS from CraftGuild with a read-only GraphQL API.

## Quick start

With Git, Make, [shiori](https://github.com/craftguild/shiori.rs#quick-start), and [shiori-frontend](https://github.com/craftguild/shiori-frontend#quick-start) installed, run:

```sh
git clone https://github.com/vaachii/shotarochiba.id.git
cd shotarochiba.id
make draft
```

Open the [local blog](http://127.0.0.1:3000/) to preview articles.
Save your Markdown changes to update the article view automatically.
The command enables CMS change notifications with `shiori serve --watch` and starts the installed production frontend with `shiori-frontend draft`.
Press Ctrl-C to stop both services; if either service exits, the other is also stopped.
Both commands must be available on `PATH`; missing commands cause a startup error.

The CMS also exposes [GraphiQL](http://127.0.0.1:4000/graphiql), where you can run this query to list the articles:

```graphql
{
  posts {
    nodes {
      id
      title
    }
  }
}
```

## System requirements

Editing articles requires only a text editor that supports UTF-8 Markdown.
Local preview requires Make, shiori v0.2.0 or later, and shiori-frontend v0.2.0 or later; see the [CMS requirements](https://github.com/craftguild/shiori.rs#system-requirements) and [frontend requirements](https://github.com/craftguild/shiori-frontend#system-requirements).
This repository contains content and has no build step.
Committing images requires Python 3 and [ExifTool](https://exiftool.org/) on `PATH`; the hook is tested with Python 3.9.6 and ExifTool 13.63.

## Usage

Override ports or executable paths when needed:

```sh
make draft BACKEND_PORT=4100 FRONTEND_PORT=3100
make draft SHIORI=/path/to/shiori SHIORI_FRONTEND=/path/to/shiori-frontend
```

Preview services bind to `127.0.0.1`; `draft` is a local preview command, and every valid article in `articles/` is visible in that preview.

Create an article from the repository root:

```sh
shiori --root . generate --title 'A new article'
```

The command prints the new `articles/<epoch-milliseconds>.md` path and creates a matching `assets/<epoch-milliseconds>/` directory.
Edit the generated file's YAML front matter and Markdown body:

```markdown
---
title: A new article
author: Shotaro Chiba
description: A short summary.
tags: [Rust]
---

Article text goes here.
```

Store images under `assets/` and reference them with `/assets/<path>` URLs.
Keep article paths stable: shiori uses them as article keys.
See the [shiori operations guide](https://github.com/craftguild/shiori.rs/blob/main/docs/operations.md) for the full content format and CMS behavior.

### Image metadata hook

After installing Python 3 and ExifTool, enable the hook in each clone:

```sh
make setup
```

Setup checks the required tools and sets this repository's `core.hooksPath` to `.githooks`; it does not install dependencies.
Every commit sanitizes all tracked images under `assets/`, including newly staged images and images unchanged by the current commit.
JPEG, PNG, WebP, GIF, AVIF, HEIC, and HEIF are supported, with the actual format detected from the file contents.
Untracked files and staged deletions are excluded.

The hook removes metadata with ExifTool while preserving orientation, ICC profiles, and color space information needed for display.
It does not recompress image data; dimensions and other structural information remain.
Location, dates, camera details, comments, and other removable metadata are deleted.
Sanitized images are automatically staged and included in the commit.
If an image has unstaged edits, stage or stash them before retrying; the hook stops before changing any images.
When cleanup is needed, use `git add` followed by `git commit` without path arguments or `--only`; commits using an alternate index stop before changing images.
Unsupported images, invalid image or metadata structures reported by ExifTool, symlinks in `assets/`, missing tools, and metadata removal failures also stop the commit.
Image files are updated only after every image passes processing and verification.

Run the isolated hook tests with:

```sh
make test
```

## Known limitations

- This repository does not include the blog frontend or CMS source code.
- shiori exposes every valid article under `articles/`, including future-dated articles; it has no private drafts or scheduled publication.
- The image hook must be enabled in each clone and can be bypassed with `git commit --no-verify` or Git configuration changes; there is no CI enforcement.
- Metadata removal applies to new commits and does not rewrite existing Git history or remove information visible in the image itself.

## Community

Report article errors or suggest corrections through [GitHub Issues](https://github.com/vaachii/shotarochiba.id/issues) or a pull request.

## License

Copyright (c) 2026 Shotaro Chiba.

Unless otherwise noted, original articles, documentation, code examples, and assets in this repository are licensed under either the [MIT License](LICENSE-MIT) or the [Apache License, Version 2.0](LICENSE-APACHE), at your option (`MIT OR Apache-2.0`).
Third-party material, including linked or embedded media, remains subject to its respective copyright and license terms.
