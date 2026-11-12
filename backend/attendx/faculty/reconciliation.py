"""Draft presence and headcount guidance, without guessing who an extra person is."""


def submission_text(row, *, approved=False):
    if row.get("submission"):
        return "MATCH · QR complete · faculty approved" if approved else "MATCH · QR complete · awaiting approval"
    decision = row.get("verification", {}).get("decision")
    if decision == "MATCH":
        return "MATCH · second QR still needed"
    if decision in ("NON_MATCH", "NONMATCH"):
        return "NON-MATCH · faculty review"
    if decision == "ABSTAIN":
        return "Uncertain face check · review"
    if row.get("review"):
        return "Face check needs review"
    return "Not submitted"


def headcount_report(session, headcount):
    if type(headcount) is not int or not 0 <= headcount <= 10000:
        raise ValueError("invalid physical headcount")
    rows = session["roster"]
    present = sum(r["status"] == "PRESENT" for r in rows)
    difference = headcount - present
    candidates = []
    for row in rows:
        review = row.get("review")
        reason = None
        if review and not review["resolved"]:
            reason = review["reason"]
        elif row["status"] == "UNMARKED":
            reason = (
                "Second QR is missing"
                if row.get("verification", {}).get("decision") == "MATCH"
                else "No completed submission; cross-check in person"
            )
        elif difference < 0 and row["status"] == "PRESENT":
            reason = "Cross-check this Present mark: physical headcount is lower"
        elif difference > 0 and row["status"] == "ABSENT":
            reason = "Cross-check this absence: physical headcount is higher"
        if reason:
            candidates.append(
                {
                    "student_id": row["student_id"],
                    "roll_number": row["roll_number"],
                    "name": row["name"],
                    "status": row["status"],
                    "check_reason": reason,
                    "verification": submission_text(row),
                }
            )
    return {
        "headcount": headcount,
        "present": present,
        "difference": difference,
        "candidates": candidates,
        "unmarked": sum(r["status"] == "UNMARKED" for r in rows),
        "matched": sum(bool(r.get("submission")) for r in rows),
        "can_approve": session["state"] == "REVIEW"
        and not any(r["status"] == "UNMARKED" or (r.get("review") and not r["review"]["resolved"]) for r in rows),
    }
