#ifndef MICROPIXEL_RUNTIME_BUNDLE_BUNDLE_READER_H
#define MICROPIXEL_RUNTIME_BUNDLE_BUNDLE_READER_H

#include <stdbool.h>
#include <stdint.h>

#include "runtime/bundle/app_requirements.h"
#include "runtime/bundle/bundle_format.h"
#include "runtime/bundle/bundle_source.h"

#ifdef __cplusplus
extern "C" {
#endif

/*
 * An opened App Bundle. `payload` is a Host-owned PSRAM copy of the AOT
 * section handed to WAMR. `sections` is a Host-owned copy of the validated
 * TOC. `bundle_mapping` holds a whole-Bundle lease for the package lifetime.
 * When that mapping is unavailable, addressable sections use on-demand PSRAM
 * copies; sequential consumers may use BundleSectionReader instead. The whole
 * Bundle is never copied into RAM.
 * Copies of this struct are shallow views; only the original passed to
 * `micropixel_close_aot_package` owns the payload, TOC and whole-Bundle lease.
 */
typedef struct {
    const uint8_t* payload;
    uint32_t payload_size;
    micropixel_bundle_source_t source;
    micropixel_bundle_mapping_t bundle_mapping;
    const micropixel_bundle_section_t* sections;
    uint32_t section_count;
    uint32_t launch_asset_id;
    uint32_t aot_flags;
    uint8_t app_id[MICROPIXEL_BUNDLE_APP_ID_MAX_LENGTH + 1U];
} micropixel_aot_package_t;

typedef struct {
    uint32_t bundle_size;
    uint32_t metadata_schema_version;
    micropixel_app_requirements_t requirements;
    uint32_t package_type;
    uint32_t display_profile;
    uint32_t component_type;
    uint32_t language_count;
    uint32_t font_format;
    uint32_t font_asset_ids[MICROPIXEL_BUNDLE_FONT_ROLE_COUNT];
    /* TTF faces in the fallback chain; font_asset_ids[0] is the primary face. Zero for CBIN roles. */
    uint32_t font_face_count;
    uint8_t app_id[MICROPIXEL_BUNDLE_APP_ID_MAX_LENGTH + 1U];
    uint8_t display_name[MICROPIXEL_BUNDLE_DISPLAY_NAME_MAX_LENGTH + 1U];
    uint8_t package_version[MICROPIXEL_BUNDLE_PACKAGE_VERSION_MAX_LENGTH + 1U];
    uint8_t languages[MICROPIXEL_BUNDLE_METADATA_MAX_LOCALES][MICROPIXEL_BUNDLE_LOCALE_MAX_LENGTH + 1U];
} micropixel_bundle_metadata_t;

typedef struct {
    const uint8_t* data;
    uint32_t size;
    uint32_t format;
    uint32_t width;
    uint32_t height;
    uint32_t stride;
    uint32_t content_hash;
} micropixel_bundle_asset_view_t;

typedef struct {
    const uint8_t* data;
    uint32_t size;
    uint32_t content_hash;
} micropixel_bundle_font_view_t;

/*
 * One section kept addressable on its own; `asset.data` / `font.data` point
 * into `mapping`: a zero-copy Flash mapping when the source can map, else a
 * Host-owned PSRAM copy. Close the mapping as soon as the bytes have been consumed
 * (decoded, copied); keep it only while a consumer still reads the bytes
 * (an audio clip being streamed, a font in use).
 */
typedef struct {
    micropixel_bundle_asset_view_t asset;
    micropixel_bundle_mapping_t mapping;
} micropixel_bundle_asset_mapping_t;

typedef struct {
    micropixel_bundle_font_view_t font;
    micropixel_bundle_mapping_t mapping;
} micropixel_bundle_font_mapping_t;

/* One validated TTF face inside its Component Bundle. */
typedef struct {
    char name[MICROPIXEL_BUNDLE_APP_ID_MAX_LENGTH];
    uint32_t id;
    uint32_t offset;
    uint32_t size;
    uint32_t content_hash;
} micropixel_bundle_font_face_t;

/*
 * Runtime acceptance of an AOT payload copy, e.g. WAMR refusing XIP images.
 * Install it once at startup, before any App Bundle is validated or opened.
 * Until a check is installed every AOT payload is refused.
 */
typedef bool (*micropixel_bundle_aot_check_t)(const uint8_t* payload, uint32_t size);
void micropixel_bundle_set_aot_check(micropixel_bundle_aot_check_t check);

/* Section id of a named asset, font face or font role. */
uint32_t micropixel_bundle_asset_id(const char* name);

/*
 * Every entry point below reads through the Bundle source contract and never
 * makes the complete Bundle addressable. Metadata and TOC are read in small
 * pieces. Hashes are checked only when a Bundle is written: the validate
 * functions stream every section. Stored Bundles are immutable, so reading,
 * opening and launching trust the committed bytes and hash nothing.
 */
bool micropixel_read_bundle_metadata(const micropixel_bundle_source_t* source,
                                     micropixel_bundle_metadata_t* metadata_out);
bool micropixel_read_bundle_metadata_for_locale(const micropixel_bundle_source_t* source, const char* effective_locale,
                                                micropixel_bundle_metadata_t* metadata_out);
/* Header and metadata, hash-checked, for installers that must decide before writing the rest. */
bool micropixel_validate_bundle_metadata(const micropixel_bundle_source_t* source,
                                         micropixel_bundle_metadata_t* metadata_out);
/* Full structural and content validation of an App Bundle before it is committed to a store. */
bool micropixel_validate_app_package(const micropixel_bundle_source_t* source,
                                     micropixel_bundle_metadata_t* metadata_out);
bool micropixel_validate_component_package(const micropixel_bundle_source_t* source,
                                           micropixel_bundle_metadata_t* metadata_out);
bool micropixel_open_launch_asset(const micropixel_bundle_source_t* source,
                                  micropixel_bundle_asset_mapping_t* mapping_out);
void micropixel_close_asset_mapping(micropixel_bundle_asset_mapping_t* mapping);
/*
 * Opens an installed App Bundle for execution: checks header, metadata and TOC
 * structure, copies the AOT section into PSRAM for the runtime check and keeps
 * the TOC.
 */
bool micropixel_open_aot_package(const micropixel_bundle_source_t* source, micropixel_aot_package_t* package_out);
void micropixel_close_aot_package(micropixel_aot_package_t* package);
/* Borrows validated TOC metadata without reading section payload.
 * The package must outlive the returned pointer. */
const micropixel_bundle_section_t* micropixel_bundle_find_asset(const micropixel_aot_package_t* package,
                                                                uint32_t asset_id);
bool micropixel_bundle_open_asset(const micropixel_aot_package_t* package, uint32_t asset_id,
                                  micropixel_bundle_asset_mapping_t* mapping_out);
bool micropixel_bundle_open_font(const micropixel_aot_package_t* package, uint32_t resource_id,
                                 micropixel_bundle_font_mapping_t* mapping_out);
/* Static system TTF only: maps the primary face of an installed Component.
 * Checks the header, metadata and TOC placement only; face bytes are verified
 * by micropixel_validate_component_package() when the Component is written.
 * Refuses a non-mappable source or mapping allocation failure. The caller keeps
 * the mapping alive until all font instances are released. */
bool micropixel_bundle_open_component_font(const micropixel_bundle_source_t* source,
                                           micropixel_bundle_metadata_t* metadata_out,
                                           micropixel_bundle_font_mapping_t* mapping_out);
/* Face table of a static or variable TTF font Component in declared fallback
 * order. Checks the header, metadata and TOC placement only; face bytes are
 * not read, so validate the Component with
 * micropixel_validate_component_package() when it is written. `capacity` must
 * hold metadata.font_face_count entries (read the metadata first). Nothing is
 * retained; callers map the Bundle themselves. */
bool micropixel_read_component_font_faces(const micropixel_bundle_source_t* source,
                                          micropixel_bundle_metadata_t* metadata_out,
                                          micropixel_bundle_font_face_t* faces_out, uint32_t capacity);
void micropixel_close_font_mapping(micropixel_bundle_font_mapping_t* mapping);

#ifdef __cplusplus
}
#endif

#endif
