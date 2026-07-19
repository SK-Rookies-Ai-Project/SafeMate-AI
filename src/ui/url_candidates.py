"""URL candidate normalization helpers shared by analysis clients."""

from __future__ import annotations


SOURCE_PRIORITY = {"text": 0, "href": 1, "image_src": 2}


def deduplicate_and_prioritize(candidates: list[dict]) -> list[dict]:
    """Merge duplicate URLs, then order by source priority and first appearance."""
    grouped: dict[str, dict] = {}
    for position, candidate in enumerate(candidates):
        url = candidate.get("url")
        source_type = candidate.get("source_type")
        input_index = candidate.get("input_index")
        if not isinstance(url, str) or not url.strip():
            continue
        if source_type not in SOURCE_PRIORITY or not isinstance(input_index, int):
            continue

        normalized_url = url.strip()
        group = grouped.setdefault(
            normalized_url,
            {
                "url": normalized_url,
                "input_indexes": [],
                "source_types": [],
                "first_position": position,
                "priority": SOURCE_PRIORITY[source_type],
                "signals": [],
                "displayed_url": candidate.get("displayed_url"),
                "displayed_domain": candidate.get("displayed_domain"),
                "destination_domain": candidate.get("destination_domain"),
                "display_href_mismatch": bool(
                    candidate.get("display_href_mismatch", False)
                ),
            },
        )
        group["input_indexes"].append(input_index)
        if source_type not in group["source_types"]:
            group["source_types"].append(source_type)
        group["priority"] = min(group["priority"], SOURCE_PRIORITY[source_type])
        for signal in candidate.get("signals", []):
            if signal not in group["signals"]:
                group["signals"].append(signal)
        if candidate.get("display_href_mismatch"):
            group["display_href_mismatch"] = True
            for field in ("displayed_url", "displayed_domain", "destination_domain"):
                if candidate.get(field):
                    group[field] = candidate[field]

    ordered = sorted(
        grouped.values(),
        key=lambda item: (item["priority"], item["first_position"]),
    )
    for item in ordered:
        item["input_indexes"].sort()
        item["source_types"].sort(key=SOURCE_PRIORITY.__getitem__)
        item["occurrence_count"] = len(item["input_indexes"])
        item.pop("first_position")
        item.pop("priority")
    return ordered
