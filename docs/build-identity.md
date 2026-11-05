# Identify the running UDB build

`udb --version` remains the plain semantic version for compatibility with
installers and existing scripts. Use `udb version --json` for the build identity,
or inspect `build` in `udb status --json`, `udb doctor --json` and `bridge_status`.
The native GUI title and version tooltip show the same build ID.

A frozen build records the exact source Git SHA, whether the build checkout was
dirty, and its packaging layout. For example, `0.11.0+abcdef123456` identifies
a different artifact from another build reporting the same `0.11.0` version.
The complete SHA is available in JSON. A `.dirty` suffix marks a modified
checkout; CI acceptance requires a clean checkout and the expected full SHA.

Source checkouts show `.source`: Git HEAD is read without launching Git, hooks,
project code or a runtime worker. This is the checkout HEAD, **not** a statement
that its working tree is clean or that an installed executable matches it.
`udb build-info` provides the heavier source inventory and build-time Git state.

A frozen build made from a source ZIP without Git metadata cannot prove a
source revision. When the embedded frozen-build markers are well-formed,
`udb version --json` reports the `onefile`/`onedir` layout with
`identity_source: embedded-layout-only`, but keeps `source_revision` and
`source_dirty` as `null` and the build ID as `unidentified`. That layout is
informational, **not** a verified source identity or publisher signature.

Missing, oversized, linked or invalid embedded metadata reports an unidentified
build instead of inventing provenance. Runtime reports do not execute Git or
open a GUI. Build-time source inspection may execute the installed Git binary.

Build metadata is an identifier, not publisher authentication. `publisher_verified`
remains false; checksums, exact-revision CI checks and future signing are separate
verification steps. No identity check changes grants, starts a connection,
updates an installation or sends data to a service.
