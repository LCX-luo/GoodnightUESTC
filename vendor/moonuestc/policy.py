"""Configured coordinates, no report fallback, and current-day checks."""
import datetime as dt
import math
import re
from .errors import ToolError
from .coordinates import to_gcj02
from .locations import resolve_location

SHANGHAI = dt.timezone(dt.timedelta(hours=8), "Asia/Shanghai")
TERMINAL = {"CHECKED_IN", "STUDENT_REPORTED", "INSTRUCTOR_REPORTED", "EXEMPT"}
PAYLOAD_KEYS = {"latitude", "longitude", "reverseGeocode", "coordinateSystemCode",
                "accuracy", "locationDurationMs", "networkTypeCode", "locationEnabled",
                "locationAuthorized", "locationAccuracy", "errorMessage"}


# Static request-field defaults from MoonCheck's buildCheckinPayload().
# These are compatibility values, never measurements from the NAS/VPS.
FIXED_METADATA_DEFAULTS = {
    "accuracy": 86, "locationDurationMs": 1189, "networkTypeCode": "4g",
    "locationEnabled": False, "locationAuthorized": "", "locationAccuracy": "", "errorMessage": "",
}
def location_source(account):
    location = resolve_location(account)
    if location is not None:
        return account["location"]["mode"]
    return "fixed_legacy_payload" if account.get("checkin_payload") is not None else "unconfigured"


def location_configured(account):
    source = location_source(account)
    value = resolve_location(account) if source in ("fixed", "preset") else account.get("checkin_payload")
    if not isinstance(value, dict):
        return False
    lat, lng = value.get("latitude"), value.get("longitude")
    if not (number(lat) and number(lng) and -90 <= lat <= 90 and -180 <= lng <= 180):
        return False
    if source in ("fixed", "preset"):
        try:
            to_gcj02(lat, lng, value.get("coordinate_system", "gcj02"))
        except ToolError:
            return False
    elif value.get("coordinateSystemCode") != "gcj02":
        return False
    return True


def now():
    return dt.datetime.now(SHANGHAI)


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def clock_minutes(text):
    if not isinstance(text, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", text):
        raise ToolError("invalid_run_time", "config")
    hour, minute = map(int, text.split(":"))
    return hour * 60 + minute


def validate_config(config):
    if not isinstance(config, dict) or type(config.get("version")) is not int or config.get("version") != 1:
        raise ToolError("invalid_config_version", "config")
    if type(config.get("automation_enabled", False)) is not bool:
        raise ToolError("invalid_automation_flag", "config")
    clock_minutes(config.get("run_at", "22:00"))
    gap = config.get("account_gap_seconds", 20)
    if not number(gap) or not 20 <= gap <= 600:
        raise ToolError("invalid_account_gap", "config")
    accounts = config.get("accounts")
    if not isinstance(accounts, list) or not 1 <= len(accounts) <= 20:
        raise ToolError("invalid_account_count", "config")
    ids, students = set(), set()
    for account in accounts:
        if not isinstance(account, dict):
            raise ToolError("invalid_account", "config")
        aid, student = account.get("id"), account.get("student_id")
        if not isinstance(aid, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,32}", aid):
            raise ToolError("invalid_account_id", "config")
        if type(account.get("enabled", True)) is not bool:
            raise ToolError("invalid_account_flag", "config")
        if aid in ids:
            raise ToolError("duplicate_account_id", "config")
        ids.add(aid)
        if not account.get("enabled", True):
            continue
        if not isinstance(student, str) or not re.fullmatch(r"\d{8,20}", student):
            raise ToolError("student_id_missing", "config")
        if student in students:
            raise ToolError("duplicate_student_id", "config")
        students.add(student)
        password = account.get("password")
        if not isinstance(password, str) or not password or password.startswith("PUT_"):
            raise ToolError("password_missing", "config")
        fingerprint = account.get("browser_fingerprint")
        if not isinstance(fingerprint, str) or not re.fullmatch(r"[A-Fa-f0-9]{32}", fingerprint):
            raise ToolError("trusted_fingerprint_missing", "config")
        ua = account.get("user_agent")
        if not isinstance(ua, str) or ua.startswith("PUT_") or not 15 <= len(ua) <= 1024 or "\r" in ua or "\n" in ua:
            raise ToolError("user_agent_missing", "config")
        location_source(account)
    return config


def valid_today(data, instant):
    if not isinstance(data, dict) or data.get("businessDate") != instant.date().isoformat():
        raise ToolError("business_date_mismatch", "today")
    status = data.get("recordStatusCode")
    if status not in TERMINAL | {"PENDING"}:
        raise ToolError("unknown_record_status", "today")
    if data.get("abnormalFlag") not in (False, None) or type(data.get("abnormalFlag")) not in (bool, type(None)):
        raise ToolError("abnormal_record", "today")
    return status


def verified(data, instant):
    return (valid_today(data, instant) == "CHECKED_IN"
            and isinstance(data.get("checkinTime"), str) and bool(data["checkinTime"])
            and data.get("abnormalFlag") is False)


def window(data, instant):
    if not isinstance(data, dict) or data.get("effective") is not True:
        raise ToolError("invalid_schedule", "schedule")
    start, end = data.get("studentCheckinStartOffsetMinute"), data.get("studentCheckinEndOffsetMinute")
    if not all(number(x) and x == int(x) for x in (start, end)) or not 0 <= start < end <= 1440:
        raise ToolError("unsupported_schedule", "schedule")
    minute = instant.hour * 60 + instant.minute + instant.second / 60
    return {"start": "%02d:%02d" % divmod(int(start), 60),
            "end": "%02d:%02d" % divmod(int(end), 60),
            "open": start <= minute < end - 2}


def build_payload(account, instant):
    source = location_source(account)
    if source in ("fixed", "preset"):
        location = resolve_location(account)
        overrides = location.get("request_metadata", {})
        if not isinstance(overrides, dict) or not set(overrides) <= set(FIXED_METADATA_DEFAULTS):
            raise ToolError("invalid_request_metadata", "location")
        payload = {
            **FIXED_METADATA_DEFAULTS, **overrides,
            "latitude": location.get("latitude"), "longitude": location.get("longitude"),
            "reverseGeocode": location.get("reverse_geocode", ""),
            "coordinateSystemCode": location.get("coordinate_system", "gcj02"),
        }
    else:
        legacy = account.get("checkin_payload")
        if not isinstance(legacy, dict) or set(legacy) != PAYLOAD_KEYS:
            raise ToolError("configured_payload_required", "location")
        payload = dict(legacy)
    lat, lng = payload["latitude"], payload["longitude"]
    if lat is None or lng is None:
        raise ToolError("fixed_coordinates_required", "location")
    if (not all(number(x) for x in (lat, lng)) or not -90 <= lat <= 90 or not -180 <= lng <= 180):
        raise ToolError("invalid_configured_coordinates", "location")
    if source in ("fixed", "preset"):
        payload["latitude"], payload["longitude"], _ = to_gcj02(lat, lng, payload["coordinateSystemCode"])
        payload["coordinateSystemCode"] = "gcj02"
    if payload["coordinateSystemCode"] != "gcj02":
        raise ToolError("coordinate_system_mismatch", "location")
    accuracy, duration = payload["accuracy"], payload["locationDurationMs"]
    if not number(accuracy) or accuracy < 0:
        raise ToolError("invalid_request_metadata", "location")
    if not number(duration) or duration < 0 or duration != int(duration):
        raise ToolError("invalid_request_metadata", "location")
    for key in ("reverseGeocode", "networkTypeCode", "locationAuthorized", "locationAccuracy", "errorMessage"):
        if not isinstance(payload[key], str) or len(payload[key]) > 1000:
            raise ToolError("invalid_request_metadata", "location")
    if not payload["networkTypeCode"] or payload["errorMessage"]:
        raise ToolError("invalid_request_metadata", "location")
    if type(payload["locationEnabled"]) is not bool:
        raise ToolError("invalid_request_metadata", "location")
    payload.update(clientTime=instant.strftime("%Y-%m-%d %H:%M:%S"), userAgent=account["user_agent"])
    return payload


def check_fence(payload, locations):
    if not isinstance(locations, list) or not locations:
        raise ToolError("locations_unavailable", "location")
    inside = False
    for fence in locations:
        if not isinstance(fence, dict):
            raise ToolError("invalid_location_fence", "location")
        lat, lng, radius = (fence.get(key) for key in ("latitude", "longitude", "radiusMeter"))
        if (not all(number(x) for x in (lat, lng, radius)) or not -90 <= lat <= 90
                or not -180 <= lng <= 180 or radius <= 0):
            raise ToolError("invalid_location_fence", "location")
        dlat, dlng = math.radians(lat - payload["latitude"]), math.radians(lng - payload["longitude"])
        hav = (math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat))
               * math.cos(math.radians(payload["latitude"])) * math.sin(dlng / 2) ** 2)
        distance = 6378137 * 2 * math.asin(math.sqrt(min(1, max(0, hav))))
        inside = inside or distance <= radius
    if not inside:
        raise ToolError("outside_allowed_location", "location")
