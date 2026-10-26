idf_component_register(SRCS "main.c" "secure_channel.c"
    "../phone-companion/transport/management_channel.c"
    INCLUDE_DIRS "." "../phone-companion/transport"
    REQUIRES checkin_runtime esp_wifi esp_event esp_netif nvs_flash mqtt mbedtls json)
