idf_component_register(SRCS
    "src/runtime/bundlefs/bundlefs.cpp"
    "src/runtime/bundlefs/bundle_store_source.cpp"
    "src/runtime/bundle/bundle_reader.c"
    "src/runtime/bundle/memory_bundle_source.c"
    "src/platform/storage/partition_block_storage.cpp"
    "src/platform/storage/flash_page_mapping_cache.cpp"
    INCLUDE_DIRS "src"
    REQUIRES esp_partition spi_flash mbedtls
    PRIV_REQUIRES cjson)
target_compile_features(${COMPONENT_LIB} PUBLIC cxx_std_23)
target_compile_options(${COMPONENT_LIB} PRIVATE
    -Werror=frame-larger-than=1536 -Werror=vla -Werror=alloca -fstack-usage)
