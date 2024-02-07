from typing import Sequence, Mapping, Any

KEYWORDS = ["title", "hint", "options"]


def parse(data: Any, names: Sequence[str] = []):
    if not isinstance(data, Mapping):
        return []

    if "sections" in data and isinstance(data["sections"], Mapping):
        return [
            (0, None, v, [f"Section Name for: {k}"])
            for k, v in data["sections"].items()
        ]

    out = []
    fun_name = ".".join(names)
    comment = f"Setting: '{fun_name}'"
    messages = []
    if "title" in data:
        comment = f"Setting: {data['title']}"
        messages.append(("Field: title", data["title"]))
    if "hint" in data:
        messages.append(("Field: hint", data["hint"]))

    if "options" in data and isinstance(data["options"], Mapping):
        messages.extend([(f"Option: {k}", v) for k, v in data["options"].items()])

    for field, msg in messages:
        out.append((0, None, msg, [comment, field]))

    for k, v in data.items():
        out.extend(parse(v, [*names, k] if k not in ("modes", "children") else names))

    return out


def extract_hhd_yaml(
    fileobj,
    keywords: Sequence[str] = [],
    comment_tags: Sequence[str] = [],
    options: Mapping[str, Any] = {},
):
    """Extract messages from XXX files.

    :param fileobj: the file-like object the messages should be extracted
                    from
    :param keywords: a list of keywords (i.e. function names) that should
                     be recognized as translation functions
    :param comment_tags: a list of translator tags to search for and
                         include in the results
    :param options: a dictionary of additional options (optional)
    :return: an iterator over ``(lineno, funcname, message, comments)``
             tuples
    :rtype: ``iterator``
    """
    import yaml

    return parse(yaml.safe_load(fileobj))
