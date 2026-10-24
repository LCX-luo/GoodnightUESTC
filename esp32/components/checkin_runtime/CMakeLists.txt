idf_component_register(SRCS "protocol.cpp" "checkin_service.cpp"
    INCLUDE_DIRS "include" REQUIRES esp_wifi esp_http_client esp-tls mbedtls json nvs_flash lwip esp_timer)
target_compile_options(${COMPONENT_LIB} PRIVATE -std=gnu++17)
