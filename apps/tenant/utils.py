def parse_origin_options(value):
    if not value:
        return []

    return [
        opt.strip()
        for opt in value.split(",")
        if opt.strip()
    ]