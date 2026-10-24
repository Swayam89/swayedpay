"""Equal split and the minimum set of transfers to settle a group.

Works in whole rupees. When the total doesn't divide evenly, the leftover rupees
go to the first members alphabetically, so shares always add up to the total.
"""

from __future__ import annotations


def settle(members: list[str], payments: dict[str, float]) -> dict:
    names: list[str] = []
    for name in list(members) + list(payments):
        clean = str(name).strip()
        if clean and clean not in names:
            names.append(clean)
    if not names:
        raise ValueError("Need at least one person in the group.")

    paid = {n: int(round(float(payments.get(n, 0) or 0))) for n in names}
    if any(v < 0 for v in paid.values()):
        raise ValueError("Payments can't be negative.")
    total = sum(paid.values())
    if total == 0:
        raise ValueError("Nobody has paid anything yet, so there is nothing to settle.")

    base, remainder = divmod(total, len(names))
    shares = {n: base + (1 if i < remainder else 0) for i, n in enumerate(sorted(names))}
    balances = {n: paid[n] - shares[n] for n in names}

    creditors = {n: b for n, b in balances.items() if b > 0}
    debtors = {n: -b for n, b in balances.items() if b < 0}
    transfers = []
    while creditors and debtors:
        # Largest balances first; ties go alphabetically.
        to = max(sorted(creditors), key=lambda n: creditors[n])
        frm = max(sorted(debtors), key=lambda n: debtors[n])
        amount = min(creditors[to], debtors[frm])
        transfers.append({"from": frm, "to": to, "amount": amount})
        creditors[to] -= amount
        debtors[frm] -= amount
        if creditors[to] == 0:
            del creditors[to]
        if debtors[frm] == 0:
            del debtors[frm]

    return {
        "members": names,
        "total": total,
        "share": total / len(names),
        "shares": shares,
        "paid": paid,
        "balances": balances,
        "transfers": transfers,
    }
