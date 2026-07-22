"""Loss reporting helpers."""


def make_loss(path, source_format, target_format, reason, value):
    return {
        "path": path,
        "source_format": source_format,
        "target_format": target_format,
        "reason": reason,
        "value": value,
    }


def report(losses):
    """Return a human-readable summary of losses."""
    if not losses:
        return "no loss"
    lines = [f"loss report: {len(losses)} field(s) could not be represented"]
    for loss in losses:
        lines.append(f"  - {loss['path']}: {loss['reason']}")
    return "\n".join(lines)
