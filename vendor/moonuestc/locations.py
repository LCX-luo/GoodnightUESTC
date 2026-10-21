"""Named presets and custom named locations; no network calls or live positioning."""
import copy
from .coordinates import finite_number, normalize_coordinate_system, to_gcj02
from .errors import ToolError

# AMap coordinates supplied for the 2026-10-19 common-location list are GCJ-02.
# Earlier group-three IDs resolve to the current AMap point.
DEFAULT_PRESET_ID = "xuezhi_group3_amap"
AMAP_POINTS = (
    (1, 103.932037, 30.754670),
    (2, 103.932328, 30.753780),
    (3, 103.933849, 30.754874),
    (4, 103.934154, 30.753768),
    (5, 103.935437, 30.753607),
    (6, 103.931652, 30.755699),
    (7, 103.932501, 30.756534),
    (8, 103.932875, 30.755637),
)
GROUP_NAMES = ("一", "二", "三", "四", "五", "六", "七", "八")
PRESETS = {
    f"xuezhi_group{group}_amap": {
        "name": "学知" + GROUP_NAMES[group - 1] + "组团",
        "longitude": longitude, "latitude": latitude,
        "coordinate_system": "gcj02", "reverse_geocode": "",
    }
    for group, longitude, latitude in AMAP_POINTS
}
PRESET_ALIASES = {"xuezhi_group3": DEFAULT_PRESET_ID, "学知三组团": DEFAULT_PRESET_ID}
OLD_GROUP3_ADDRESS = "中国四川省成都市郫都区合作街道银杏大道"


def upgrade_group3_location(raw, *, migrate_named=False):
    """Copy and normalize prior group-three references without touching credentials."""
    result = copy.deepcopy(raw)
    if not isinstance(result, dict):
        return result
    preset = result.get("mode") == "preset" and result.get("preset") in PRESET_ALIASES
    named = migrate_named and result.get("mode") == "fixed" and result.get("name") in ("学知三组团", "学知三组团（旧版位置）")
    if preset:
        result["preset"] = DEFAULT_PRESET_ID
    elif named:
        point = PRESETS[DEFAULT_PRESET_ID]
        result.update(name="学知三组团", latitude=point["latitude"], longitude=point["longitude"], coordinate_system="gcj02")
    if (preset or named) and result.get("reverse_geocode") == OLD_GROUP3_ADDRESS:
        result.pop("reverse_geocode")
    return result


FIXED_LOCATION_KEYS = {"mode", "name", "latitude", "longitude", "reverse_geocode",
                       "coordinate_system", "request_metadata"}
PRESET_LOCATION_KEYS = {"mode", "preset", "reverse_geocode", "request_metadata"}


def _name(value):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 80:
        raise ToolError("invalid_location_name", "location")
    return value.strip()


def get_preset(value):
    if not isinstance(value, str):
        raise ToolError("unknown_location_preset", "location")
    value = PRESET_ALIASES.get(value, value)
    for key, preset in PRESETS.items():
        if value in (key, preset["name"]):
            return key, copy.deepcopy(preset)
    raise ToolError("unknown_location_preset", "location")


def resolve_location(account):
    raw, legacy = account.get("location"), account.get("checkin_payload")
    if raw is None:
        return None
    if legacy is not None:
        raise ToolError("ambiguous_location_configuration", "location")
    if not isinstance(raw, dict):
        raise ToolError("invalid_fixed_location_configuration", "location")
    raw = upgrade_group3_location(raw)
    mode = raw.get("mode")
    if mode == "fixed":
        if not set(raw) <= FIXED_LOCATION_KEYS:
            raise ToolError("invalid_fixed_location_configuration", "location")
        result = copy.deepcopy(raw)
        result["name"] = _name(raw.get("name", "自定义位置"))
        return result
    if mode == "preset":
        if not set(raw) <= PRESET_LOCATION_KEYS:
            raise ToolError("invalid_preset_location_configuration", "location")
        preset_id, result = get_preset(raw.get("preset"))
        result.update(mode="fixed", _preset_id=preset_id)
        if "reverse_geocode" in raw:
            result["reverse_geocode"] = raw["reverse_geocode"]
        metadata = raw.get("request_metadata", {})
        if not isinstance(metadata, dict):
            raise ToolError("invalid_request_metadata", "location")
        result["request_metadata"] = {**result.get("request_metadata", {}), **metadata}
        return result
    raise ToolError("unsupported_location_mode", "location")


def location_details(account):
    location = resolve_location(account)
    if location is None:
        legacy = account.get("checkin_payload")
        return {"locationName": "旧版固定坐标" if legacy is not None else None,
                "inputCoordinateSystem": "gcj02" if legacy is not None else None,
                "outputCoordinateSystem": "gcj02", "coordinateConversion": "none"}
    system = normalize_coordinate_system(location.get("coordinate_system", "gcj02"))
    details = {"locationName": location["name"], "inputCoordinateSystem": system,
               "outputCoordinateSystem": "gcj02",
               "coordinateConversion": "wgs84_to_gcj02_approx" if system == "wgs84" else "none"}
    if all(finite_number(location.get(key)) for key in ("latitude", "longitude")):
        try:
            _, _, details["coordinateConversion"] = to_gcj02(location["latitude"], location["longitude"], system)
        except ToolError:
            pass
    if "_preset_id" in location:
        details["presetId"] = location["_preset_id"]
    return details


def list_presets():
    items = []
    for preset_id, value in PRESETS.items():
        value = copy.deepcopy(value)
        latitude, longitude, method = to_gcj02(value["latitude"], value["longitude"], value["coordinate_system"])
        items.append({"id": preset_id, "name": value["name"],
                      "source": {"latitude": value["latitude"], "longitude": value["longitude"],
                                 "coordinateSystem": value["coordinate_system"]},
                      "submittedCoordinates": {"latitude": latitude, "longitude": longitude, "coordinateSystem": "gcj02"},
                      "coordinateConversion": method, "address": value["reverse_geocode"],
                      "config": {"mode": "preset", "preset": preset_id}})
    return items
