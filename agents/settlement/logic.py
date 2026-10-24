"""Splitting a group's expenses and the minimum set of transfers to settle them.

Each expense has a payer, an amount and the people who share it (everyone by
default, or everyone except some people, or only some people). Works in whole
rupees: when an expense doesn't divide evenly, the leftover rupees go to the first
sharers alphabetically, so every expense's shares add up to exactly its amount.
"""

from __future__ import annotations


def _unique(names) -> list[str]:
    out: list[str] = []
    for name in names:
        clean = str(name).strip()
        if clean and clean not in out:
            out.append(clean)
    return out


def participants(expense: dict, members: list[str]) -> list[str]:
    only = [n for n in expense.get("only") or [] if n in members]
    if only:
        return only
    excluded = set(expense.get("excluded") or [])
    return [m for m in members if m not in excluded]


def settle_expenses(members: list[str], expenses: list[dict]) -> dict:
    names = _unique(list(members) + [e.get("payer", "") for e in expenses])
    if not names:
        raise ValueError("Need at least one person in the group.")

    paid = {n: 0 for n in names}
    owes = {n: 0 for n in names}
    normalised = []
    for e in expenses:
        amount = int(round(float(e.get("amount") or 0)))
        payer = str(e.get("payer", "")).strip()
        if amount < 0:
            raise ValueError("Payments can't be negative.")
        if amount == 0 or not payer:
            continue
        sharers = participants(e, names)
        if not sharers:
            raise ValueError(f"Nobody is left to share {payer}'s {e.get('label') or 'payment'}.")
        paid[payer] += amount
        base, remainder = divmod(amount, len(sharers))
        for i, n in enumerate(sorted(sharers)):
            owes[n] += base + (1 if i < remainder else 0)
        normalised.append({
            "payer": payer, "amount": amount, "label": e.get("label") or "",
            "sharers": sharers, "everyone": len(sharers) == len(names),
        })

    total = sum(paid.values())
    if total == 0:
        raise ValueError("Nobody has paid anything yet, so there is nothing to settle.")

    balances = {n: paid[n] - owes[n] for n in names}
    creditors = {n: b for n, b in balances.items() if b > 0}
    debtors = {n: -b for n, b in balances.items() if b < 0}
    transfers = []
    while creditors and debtors:
        # Largest balances first; ties go alphabetically.
        to = max(sorted(creditors), key=lambda n: creditors[n])
        frm = max(sorted(debtors), key=lambda n: debtors[n])
        amount = min(creditors[to], debtors[frm])
        transfers.append({"from": frm, "to": to, "amount": amount, "repaid": 0})
        creditors[to] -= amount
        debtors[frm] -= amount
        if creditors[to] == 0:
            del creditors[to]
        if debtors[frm] == 0:
            del debtors[frm]

    equal = all(e["everyone"] for e in normalised)
    return {
        "members": names,
        "total": total,
        "share": total / len(names),
        "equal": equal,
        "shares": owes,
        "paid": paid,
        "balances": balances,
        "expenses": normalised,
        "transfers": transfers,
    }


def settle(members: list[str], payments: dict[str, float]) -> dict:
    """Equal split of simple payments (everyone shares everything)."""
    return settle_expenses(members, [{"payer": n, "amount": a} for n, a in payments.items()])
