# BundleFS

ESP-IDF component for BundleFS v3 and the Bundle v1 package format. BundleFS stores
immutable files with streaming copy-on-write replacement, checksummed catalogs, power-loss
recovery and mapped-reader leases. The Bundle reader validates and opens the packages stored
in those files. No background tasks. Component version `0.2.0` is independent of on-disk
format version `3` and Bundle format version `1`.

## Scope

- `src/runtime/bundlefs`: filesystem, format definitions and `MakeBundleSource()`, which
  exposes one committed or staged store file as a Bundle source.
- `src/runtime/bundle`: Bundle v1 format, source contract, memory source and reader
  (header, TOC, metadata, App and font Component validation, section views).
- `src/device`: media contract and the CBIN font section envelope.
- `src/platform/storage`: ESP partition and MMU mapping adapters.
- `src/platform/memory/psram_buffer.hpp`: fallible PSRAM buffer.
- `tools/font_component.py`: builds and verifies multi-face TTF font Components.

Requires ESP-IDF 6.x, C++23, cJSON and PSRAM. Catalog and file work buffers do not fall back
to internal SRAM. The temporary page list passed to the ESP-IDF MMU API uses internal RAM, as
required by that API. Compilation rejects stack frames above 1536 bytes, VLAs and `alloca`.
Applications own filesystem instances, storage lifetimes, update policy, UI and the Guest
runtime. Replacement requires enough free space for both old and new file data while readers
hold the old version.

The reader has no WAMR dependency. AOT payloads are refused until the application installs
its runtime check once at startup with `micropixel_bundle_set_aot_check()`; MicroPixel installs
a WAMR check that rejects XIP images. Font Components need no check.

Extracted from MicroPixel commit `c2bc418e6237a8da4b4e9c6b75349c8dd0851ffc`, with
Pocket Sage's PSRAM and stack improvements. Existing `micropixel::*` namespaces and header
paths are retained for source compatibility. SPI NAND adapters, AppStore and AOT loading
remain in the consuming projects.

## Font Components

A font Component (`package_type: component`, `component_type: font`) is one Bundle file, and
therefore one BundleFS Catalog entry, however many faces it carries. Its metadata declares
either one face or an ordered fallback chain. The face count is bounded only by the Bundle
format (128 sections, 4 KiB metadata):

```json
"font": {"asset": "regular", "format": "ttf"}
"font": {"faces": ["latin", "emoji", "sc"], "format": "ttf-variable"}
```

Each face is a FONT section whose id is the FNV-1a hash of its name
(`micropixel_bundle_asset_id()`). `ttf` sections (format 11) must be static glyf TrueType;
`ttf-variable` sections (format 12) may carry OpenType variations and are meant for FreeType
consumers. `micropixel_validate_component_package()` hashes and checks every face; run it when the
Component is written. At load time `micropixel_read_component_font_faces()` checks only the
header, metadata and TOC placement and fills a caller-sized face table (names, ids, offsets)
in fallback order, so callers can map the file once and hand each face to the font engine.
Size the table from `font_face_count` in the metadata.
`micropixel_bundle_open_component_font()` maps only the primary face of a static Component,
with the same structure-only checks.
Keep the metadata section first so streaming installers can check it before writing.

```sh
python3 -c 'import sys; sys.path.insert(0, "tools"); import font_component; help(font_component)'
```

## Local development

Keep the three repositories beside each other. Track relative symlinks in the consumers:

```sh
# From pocket-sage/
ln -s ../../bundlefs components/bundlefs
# From micropixel/
ln -s ../../../../bundlefs firmware/espressif/components/bundlefs
```

Add `bundlefs` to the consumer's `idf_component_register(REQUIRES ...)`. Use public headers
such as `runtime/bundlefs/bundlefs.hpp`, `runtime/bundle/bundle_reader.h` and
`platform/storage/partition_block_storage.hpp`.
`CONFIG_BUNDLEFS_BLOCK_MAP_BUDGET_KIB` controls geometry planning for newly formatted stores;
existing catalogs retain their geometry. Legacy MicroPixel configuration is migrated by
`sdkconfig.rename`.

Run the consumer regressions through `bash tools/tests/test_firmware_host.sh` in MicroPixel
(storage, App Store, reader and multi-face Components) and the CMake/CTest harness in
`pocket-sage/scripts/tests/bundlefs` (real SHA-256, OTA recovery, delete-first font
replacement and generated factory images under ASan/UBSan).

## Versioned distribution

This directory is the source of truth and should be committed to its own repository.
Before enabling consumer CI, configure `BUNDLEFS_REPOSITORY` (owner/repository) and
`BUNDLEFS_REF` (fixed commit or release tag) in both GitHub repositories. Their firmware
workflows check out that revision beside the consumer. A symlink alone does not download code.

`idf_component.yml`, this README and `LICENSE` form the Registry package. Validate locally
with `compote component pack --name bundlefs`; packing does not publish. Once a namespace
and release repository exist, publish explicitly, replace local symlinks in release consumers
with a versioned manifest dependency, and commit their dependency locks according to project policy.
Do not ship local build outputs or consumer-specific assets in the component archive.
