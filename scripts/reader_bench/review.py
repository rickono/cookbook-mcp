"""Pure review transforms for saved text and labels; no models, images or source reads."""

import copy

import assemble


class ReviewError(ValueError):
    """A saved label cannot be reused without inventing ownership."""


def remap_labels(record, old_origins, new_origins):
    """Keep label ownership of surviving occurrences, refusing new occurrences.

    Origins come from pipeline.patch_origins on the same saved page and votes.
    Removed synthetic additions lose their labels; authored repetitions keep their
    separate origins. Replacements retain their source occurrence but still require
    review of the inherited part classification before candidate acceptance.
    """
    if len(set(old_origins)) != len(old_origins) or len(set(new_origins)) != len(
        new_origins
    ):
        raise ReviewError("line origins must identify distinct occurrences")
    if not set(new_origins) <= set(old_origins):
        raise ReviewError("review adds an occurrence without a cached label")
    result = copy.deepcopy(record)
    label = result.get("label")
    if label is None:
        return result  # existing failed labels remain failed, with their evidence
    assemble.check(label, len(old_origins))
    positions = {origin: i for i, origin in enumerate(new_origins, 1)}
    blocks = []
    for block in label["blocks"]:
        surviving = [
            positions[origin]
            for origin in old_origins[int(block["from"]) - 1 : int(block["to"])]
            if origin in positions
        ]
        if not surviving:
            continue
        if surviving != list(range(surviving[0], surviving[-1] + 1)):
            raise ReviewError("review moves occurrences across a cached label block")
        blocks.append({**block, "from": surviving[0], "to": surviving[-1]})
    references = []
    for reference in label.get("references", []):
        line = reference["line"]
        if (
            not isinstance(line, int)
            or isinstance(line, bool)
            or not 1 <= line <= len(old_origins)
        ):
            raise ReviewError("reference does not name a cached line")
        origin = old_origins[line - 1]
        if origin in positions:
            references.append({**reference, "line": positions[origin]})
    label.update(blocks=blocks, references=references)
    assemble.check(label, len(new_origins))
    return result
