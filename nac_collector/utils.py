def merge_dict_list(source, destination):
    for key, value in source.items():
        if isinstance(value, dict):
            # get node or create one
            node = destination.setdefault(key, {})
            merge_dict_list(value, node)
        elif isinstance(value, list):
            if key not in destination:
                destination[key] = []
            if isinstance(destination[key], list):
                destination[key].extend(value)
        else:
            destination[key] = value
    return destination