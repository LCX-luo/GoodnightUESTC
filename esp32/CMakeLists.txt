cmake_minimum_required(VERSION 3.16)
set(EXTRA_COMPONENT_DIRS
    "${CMAKE_CURRENT_LIST_DIR}/../private-data/esp32-ac/main"
    "${CMAKE_CURRENT_LIST_DIR}/components/checkin_runtime")
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(ac_checkin)
