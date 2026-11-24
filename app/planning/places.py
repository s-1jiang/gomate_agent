def match_origin(name, candidates, city):
    """Accept exact names with an optional known city prefix, not fuzzy POI guesses."""
    matches = []
    for place in candidates:
        city_name = place.city or city
        prefixes = {city_name}
        if city_name.endswith("市"):
            prefixes.add(city_name[:-1])
        names = {place.name, *(prefix + place.name for prefix in prefixes if prefix)}
        if name in names:
            matches.append(place)
    if matches:
        return matches[0] if len(matches) == 1 else None
    return candidates[0] if len(candidates) == 1 else None
