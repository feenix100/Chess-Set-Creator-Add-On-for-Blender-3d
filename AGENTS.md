# AGENTS.md

This file gives coding agents repository-specific instructions. Follow it for all changes unless the maintainer explicitly asks for something different.

## Repository purpose

This repository maintains the **Chess Set Creator Add-On for Blender 3D**, currently packaged as the **Fantasy Chess Set Generator** Blender extension.

The extension can generate **15,552 different chess-set combinations** from its supported piece styles, materials, colors, and board appearances. The Google Colab notebook is a companion rendering utility, not the primary product.

## Repository layout

- `fantasy_chess_generator-0.4.69/` — authoritative Blender extension source.
  - `__init__.py` — main add-on implementation.
  - `blender_manifest.toml` — Blender extension metadata, minimum Blender version, permissions, license declaration, and packaging rules.
  - `README.md` — extension-specific usage notes.
- `blender_colab_renderer.ipynb` — optional Google Colab/Cycles GPU rendering workflow for finished `.blend` files.
- `README.md` — repository-level overview and user instructions.
- `LICENSE` — repository-level license file.

Do not assume older ZIP uploads are the source of truth. Work from the checked-in extension directory.

## Supported Blender versions

The manifest currently declares:

- Extension ID: `fantasy_chess_generator`
- Extension version: `0.4.69`
- Minimum Blender version: `4.2.0`

Changes must remain compatible with Blender 4.2+ unless the maintainer explicitly changes the supported range.

Do not use APIs introduced after Blender 4.2 without either:
1. providing a compatible fallback, or
2. updating the minimum supported Blender version with maintainer approval.

## Before making changes

1. Read the current repository state first. Do not rely on an earlier clone, cached file listing, or prior conversation.
2. Read `fantasy_chess_generator-0.4.69/blender_manifest.toml`.
3. Inspect the specific area of `__init__.py` you need to change before editing.
4. Preserve unrelated user changes.
5. Keep the scope narrow. Do not perform opportunistic rewrites, mass formatting, or large structural refactors unless requested.

The main add-on file is large and intentionally self-contained. A task that only needs a local fix should remain a local fix.

## Blender coding rules

### Preserve Blender state

Many operations use `bpy.ops`, which is context-sensitive. When temporarily changing any of the following, restore the previous state whenever practical:

- active object
- selected objects
- active collection
- scene camera
- mode
- frame
- render settings
- viewport/context overrides

Use `try/finally` around temporary context or selection mutations.

### Prefer direct data API where practical

Prefer `bpy.data`, object/collection APIs, mesh data APIs, and explicit property assignment over `bpy.ops` when an operator is not required.

When an operator is required, make its context assumptions explicit and avoid depending on whatever the user happened to have selected.

### Respect generated collection boundaries

The extension uses named collections such as:

- `CHESS_SET`
- `CHESS_BOARD`
- `PIECE_SETS`
- `WHITE`
- `BLACK`
- `Render Scene`
- `Render Sequence`
- `Individual Piece Showcase`

Do not delete or modify unrelated scene objects. Cleanup operators should stay inside the extension's own generated collections whenever possible.

### Keep object generation deterministic

For the same settings, generated geometry, materials, names, hierarchy, transforms, and board placement should be predictable.

Avoid hidden dependence on:
- current selection
- active object
- viewport orientation
- current mode
- arbitrary object ordering
- global scene objects outside the extension's collections

### Materials and render behavior

Material changes should not silently alter unrelated user materials.

Render-scene/showcase helpers should:
- use clearly named generated cameras/lights/collections,
- avoid overwriting unrelated scene assets,
- preserve prior settings when temporary changes are sufficient,
- keep Cycles/Eevee assumptions explicit.

### Export behavior

The extension declares Blender's `files` permission because export and rendered-media workflows write user-requested files.

Do not add network, clipboard, subprocess, or other permissions without a concrete feature need and maintainer approval.

Keep exports limited to user-requested operations and predictable destinations.

## UI and operator changes

The add-on is exposed through the 3D Viewport sidebar under the **Fantasy Chess** workflow.

When adding or modifying UI:

- keep controls grouped by workflow rather than by implementation detail,
- use clear labels suitable for Blender users,
- disable controls when an operation is not currently valid instead of letting it fail later,
- report actionable errors with `self.report(...)`,
- avoid blocking UI operations for expensive work when a safer approach exists.

When adding an operator:

- give it a stable `bl_idname`,
- give it a useful `bl_label`,
- validate preconditions,
- avoid destructive changes outside generated extension data,
- ensure it is included in registration/unregistration.

## Registration

Any new Blender classes, properties, handlers, menus, or callbacks must be registered and unregistered symmetrically.

Before finishing a change involving registration:

- verify every registered class is unregistered,
- remove custom properties/handlers that were added,
- avoid duplicate registration on extension reload,
- test disable/re-enable behavior in Blender.

## Versioning and release metadata

Do not bump the extension version unless the task is explicitly a release/version change.

For a release/version change:

1. update `version` in `blender_manifest.toml`,
2. keep repository documentation consistent,
3. if the versioned source-directory convention is retained, rename `fantasy_chess_generator-<version>/` to match the manifest version,
4. validate the manifest,
5. build the installable ZIP,
6. verify the built package installs.

Do not hand-edit generated ZIP contents as the primary development workflow.

## Validation and build commands

Run these from the repository root when Blender is available.

### Fast Python syntax check

```bash
python -m py_compile fantasy_chess_generator-0.4.69/__init__.py
```

### Validate Blender extension metadata

```bash
blender --command extension validate fantasy_chess_generator-0.4.69
```

### Build the extension package

Prefer an output directory outside the source tree:

```bash
mkdir -p dist
blender --command extension build \
  --source-dir fantasy_chess_generator-0.4.69 \
  --output-dir dist
```

The package name is derived from the manifest extension ID and version unless an output filepath is explicitly supplied.

Do not commit build artifacts unless the maintainer asks for release artifacts to be checked in.

## Manual Blender smoke test

For behavior changes, syntax and manifest validation are not sufficient. When Blender is available, install the built ZIP and smoke-test the affected workflow.

At minimum, for core generator changes verify:

1. the extension installs and enables,
2. the **Fantasy Chess** sidebar panel appears,
3. a board can be created,
4. White and Black piece sets can be created,
5. materials can be applied,
6. generated objects are placed under the expected extension collections,
7. cleanup removes only generated extension data,
8. disabling and re-enabling the extension does not produce registration errors.

For render/showcase changes, also verify camera/light creation and at least one still/showcase setup.

For export changes, verify the requested format and output path without overwriting unrelated files.

## Colab notebook rules

`blender_colab_renderer.ipynb` is a companion utility. Do not modify it for ordinary add-on changes.

When a task specifically changes the notebook:

- keep it valid `nbformat` JSON,
- preserve Colab usability,
- keep configuration near the top,
- avoid hard-coding private paths, tokens, credentials, or account-specific IDs,
- keep GPU detection and error messages actionable,
- keep output behavior resumable where possible,
- prefer PNG frame sequences for interruption-tolerant long animation renders,
- test notebook JSON parsing even if Colab execution is unavailable.

The notebook currently targets Blender 5.2.0 for remote rendering. That does not change the add-on's Blender 4.2+ minimum compatibility target.

## Documentation rules

Update documentation when user-visible behavior, installation, supported versions, styles, materials, export formats, or workflows change.

Keep these files consistent when relevant:

- root `README.md`
- extension `README.md`
- `blender_manifest.toml`

Do not claim a combination count, feature, format, or Blender version that the code does not actually support.

## Licensing

There is currently a licensing inconsistency in the repository:

- root `LICENSE` is MIT,
- `blender_manifest.toml` declares `GPL-3.0-or-later`,
- `__init__.py` carries an SPDX GPL-3.0-or-later header.

Do **not** silently reconcile, remove, or change these license declarations as part of unrelated work. Flag the inconsistency to the maintainer if a task touches licensing, packaging, distribution, or third-party code.

Do not add third-party code unless its license is compatible with the intended project licensing and the required attribution is preserved.

## Security and privacy

Never commit:

- API keys
- access tokens
- passwords
- private URLs
- personal Google Drive paths
- private user data
- machine-specific credentials

Do not add telemetry, network access, external downloads, or remote execution to the add-on unless explicitly requested.

Treat Blender files and exported media as user data. Do not upload them anywhere automatically.

## Change quality

Before finishing a task:

1. inspect the diff,
2. remove debug prints and temporary code unless intentionally useful,
3. run the narrowest relevant validation,
4. run the broader Blender smoke test when behavior changed and Blender is available,
5. update docs only where behavior actually changed,
6. state what was tested and what could not be tested.

Do not report a test as passed unless it was actually run.

## Commit discipline

Use focused commits with messages that describe the user-visible or technical change.

Avoid mixing:
- formatting-only churn,
- unrelated refactors,
- generated artifacts,
- notebook changes,
- add-on behavior changes

in a single commit unless they are inseparable parts of the same task.

## Agent priority

When tradeoffs are necessary, prefer in this order:

1. preserving user Blender scenes and data,
2. correctness of generated chess sets,
3. Blender 4.2+ compatibility,
4. predictable install/register/unregister behavior,
5. maintainability,
6. performance,
7. cosmetic cleanup.
