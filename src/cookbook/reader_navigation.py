"""Bounded source-order neighbors, independent of the displayed contents page."""

from .book_model import connection


def native_neighbors(model, book_id, target_id):
    with connection(model.path) as db:
        occurrence = db.execute(
            "select ordinal from occurrences where edition_id=? and id=?",
            (book_id, target_id),
        ).fetchone()
        if occurrence:
            result = []
            for direction, operator, order in (
                ("Previous", "<", "desc"),
                ("Next", ">", "asc"),
            ):
                row = db.execute(
                    f"select id,ordinal from occurrences where edition_id=? and ordinal{operator}? order by ordinal {order} limit 1",
                    (book_id, occurrence["ordinal"]),
                ).fetchone()
                if row:
                    result.append(
                        {
                            "label": direction + " section",
                            "title": "Source document " + str(row["ordinal"] + 1),
                            "target_id": row["id"],
                            "contents_offset": db.execute(
                                "select count(*) from occurrences where edition_id=? and ordinal<?",
                                (book_id, row["ordinal"]),
                            ).fetchone()[0]
                            // 30
                            * 30,
                        }
                    )
            return result
        current = db.execute(
            "select n.document_id,n.preorder,o.ordinal from navigation v "
            "join nodes n on n.id=v.target_node "
            "join occurrences o on o.document_id=n.document_id and o.edition_id=v.edition_id "
            "where v.edition_id=? and v.id=? and json_extract(v.payload,'$.target.state')='resolved_node' limit 2",
            (book_id, target_id),
        ).fetchall()
        if len(current) != 1:
            return []  # Repeated source documents do not establish a unique chapter.
        current = current[0]
        result = []
        for direction, operator, order in (
            ("Previous", "<", "desc"),
            ("Next", ">", "asc"),
        ):
            row = db.execute(
                "select v.id,v.label,v.ordinal as navigation_ordinal,n.document_id from navigation v "
                "join nodes n on n.id=v.target_node "
                "join occurrences o on o.document_id=n.document_id and o.edition_id=v.edition_id "
                f"where v.edition_id=? and (o.ordinal{operator}? or (o.ordinal=? and n.preorder{operator}?)) "
                "and json_extract(v.payload,'$.target.state')='resolved_node' "
                f"order by o.ordinal {order},n.preorder {order},v.ordinal {order} limit 1",
                (book_id, current["ordinal"], current["ordinal"], current["preorder"]),
            ).fetchone()
            if (
                row
                and db.execute(
                    "select count(*) from occurrences where edition_id=? and document_id=?",
                    (book_id, row["document_id"]),
                ).fetchone()[0]
                == 1
            ):
                result.append(
                    {
                        "label": direction + " section",
                        "title": row["label"],
                        "target_id": row["id"],
                        "contents_offset": db.execute(
                            "select count(*) from navigation where edition_id=? and ordinal<?",
                            (book_id, row["navigation_ordinal"]),
                        ).fetchone()[0]
                        // 30
                        * 30,
                    }
                )
        return result
