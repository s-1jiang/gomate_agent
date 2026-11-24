import math
import re


def air_distance(first, second):
    lat1, lat2 = math.radians(first.latitude), math.radians(second.latitude)
    delta_lat = lat2 - lat1
    delta_lon = math.radians(second.longitude - first.longitude)
    value = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    return 6371000 * 2 * math.asin(min(1, math.sqrt(value)))


def normalized_name(value):
    return re.sub(r"[\s()（）·—-]", "", value)


def match_origin(name, candidates, city):
    """Resolve known city prefixes and campus selections, without selecting annexes."""
    query = normalized_name(name)
    matches = []
    for place in candidates:
        city_name = place.city or city
        prefixes = {city_name}
        if city_name.endswith("市"):
            prefixes.add(city_name[:-1])
        names = {place.name, *(prefix + place.name for prefix in prefixes if prefix)}
        if query in {normalized_name(item) for item in names}:
            matches.append(place)
    if matches:
        return matches[0] if len(matches) == 1 else None
    if query.endswith("校区"):
        # A selected campus may be abbreviated; a building/centre is not the campus.
        matches = [place for place in candidates if normalized_name(place.name).endswith(query)]
        return matches[0] if len(matches) == 1 else None
    return candidates[0] if len(candidates) == 1 else None


def recommendation_areas(name, candidates, city):
    query = normalized_name(name)
    chosen = match_origin(name, candidates, city)
    campuses = [place for place in candidates if normalized_name(place.name).endswith("校区")]
    if "校区" in query:
        return [chosen] if chosen else []
    # An institution with several observed campuses can be answered by campus.
    related = [place for place in campuses if query in normalized_name(place.name)]
    if len(related) > 1:
        return related[:2]
    if chosen:
        return [chosen]
    if related:
        return related[:2]
    related = [place for place in candidates if query in normalized_name(place.name)]
    return related[:2]
