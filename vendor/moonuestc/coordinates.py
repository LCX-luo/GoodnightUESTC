"""Offline approximate WGS-84 -> GCJ-02 conversion; never a location sensor.

Forward-transform formula ported from wandergis/coordtransform (MIT).
This is not an official map-provider calibration or a school validation.
See third_party/coordtransform.LICENSE and COORDINATE-SOURCE.json.
"""
import math
from .errors import ToolError

_A = 6378245.0
_EE = 0.00669342162296594323


def finite_number(value):
    return type(value) in (int, float) and math.isfinite(value)


def normalize_coordinate_system(value):
    if not isinstance(value, str):
        raise ToolError("coordinate_system_mismatch", "location")
    value = value.strip().lower().replace("-", "").replace("_", "")
    if value not in {"wgs84", "gcj02"}:
        raise ToolError("coordinate_system_mismatch", "location")
    return value


def _latitude_delta(x, y):
    result = -100 + 2*x + 3*y + 0.2*y*y + 0.1*x*y + 0.2*math.sqrt(abs(x))
    result += (20*math.sin(6*x*math.pi) + 20*math.sin(2*x*math.pi))*2/3
    result += (20*math.sin(y*math.pi) + 40*math.sin(y/3*math.pi))*2/3
    result += (160*math.sin(y/12*math.pi) + 320*math.sin(y*math.pi/30))*2/3
    return result


def _longitude_delta(x, y):
    result = 300 + x + 2*y + 0.1*x*x + 0.1*x*y + 0.1*math.sqrt(abs(x))
    result += (20*math.sin(6*x*math.pi) + 20*math.sin(2*x*math.pi))*2/3
    result += (20*math.sin(x*math.pi) + 40*math.sin(x/3*math.pi))*2/3
    result += (150*math.sin(x/12*math.pi) + 300*math.sin(x/30*math.pi))*2/3
    return result


def to_gcj02(latitude, longitude, coordinate_system):
    """Return (latitude, longitude, conversion_method), with explicit axis order."""
    if (not all(finite_number(v) for v in (latitude, longitude))
            or not -90 <= latitude <= 90 or not -180 <= longitude <= 180):
        raise ToolError("invalid_configured_coordinates", "location")
    system = normalize_coordinate_system(coordinate_system)
    if system == "gcj02":
        return latitude, longitude, "none"
    # The reference algorithm uses this bounding rectangle, not a political boundary.
    if not (73.66 < longitude < 135.05 and 3.86 < latitude < 53.55):
        return latitude, longitude, "outside_transform_area_identity"
    dlat = _latitude_delta(longitude - 105, latitude - 35)
    dlng = _longitude_delta(longitude - 105, latitude - 35)
    radlat = math.radians(latitude)
    magic = 1 - _EE*math.sin(radlat)**2
    root = math.sqrt(magic)
    dlat = dlat*180 / ((_A*(1-_EE))/(magic*root)*math.pi)
    dlng = dlng*180 / (_A/root*math.cos(radlat)*math.pi)
    return latitude + dlat, longitude + dlng, "wgs84_to_gcj02_approx"
