"""SwayedPay monetisation via the Fetch.ai Agent Payment Protocol (seller role).

Model: planning is free; settling the bill (the who-pays-whom split) costs a small
convenience fee, paid in FET on the Dorado testnet. Testnet FET has no real value.

PAYMENT_MODE in .env:
  off         settlement is free (default; safest for demos)
  settle_fee  the orchestrator sends RequestPayment before settling, verifies the
              CommitPayment transaction on-chain, then settles
"""

from __future__ import annotations

import asyncio
import os

from dotenv import find_dotenv, load_dotenv
from uagents import Protocol
from uagents_core.contrib.protocols.payment import Funds, RequestPayment, payment_protocol_spec

load_dotenv(find_dotenv())

PAYMENT_MODE = os.getenv("PAYMENT_MODE", "off").strip().lower()
SETTLE_FEE_FET = os.getenv("SETTLE_FEE_FET", "0.1").strip()
FET_DECIMALS = 18
TESTNET_DENOM = "atestfet"

payment_proto = Protocol(spec=payment_protocol_spec, role="seller")


def fee_enabled() -> bool:
    return PAYMENT_MODE == "settle_fee"


def build_request(wallet_address: str, reference: str) -> RequestPayment:
    description = (
        f"SwayedPay settlement fee: {SETTLE_FEE_FET} testnet FET to split the bill and "
        "get the who-pays-whom list. Testnet tokens only, no real money."
    )
    return RequestPayment(
        accepted_funds=[Funds(currency="FET", amount=SETTLE_FEE_FET, payment_method="fet_direct")],
        recipient=wallet_address,
        deadline_seconds=300,
        reference=reference,
        description=description,
        metadata={
            "provider_agent_wallet": wallet_address,
            "fet_network": "stable-testnet",
            "mainnet": "false",
            "content": description,
        },
    )


def _verify_sync(transaction_id: str, expected_fet: str, buyer_wallet: str, recipient_wallet: str) -> tuple[bool, str]:
    from cosmpy.aerial.client import LedgerClient, NetworkConfig

    try:
        ledger = LedgerClient(NetworkConfig.fetchai_stable_testnet())
        tx = ledger.query_tx(transaction_id)
    except Exception as exc:
        return False, f"could not look up the transaction ({type(exc).__name__})"
    if not tx.is_successful():
        return False, "the transaction failed on-chain"

    expected = int(float(expected_fet) * 10**FET_DECIMALS)
    for event_type, attrs in tx.events.items():
        if event_type != "transfer" or attrs.get("recipient") != recipient_wallet:
            continue
        if buyer_wallet and attrs.get("sender") != buyer_wallet:
            continue
        amount = attrs.get("amount", "")
        if amount.endswith(TESTNET_DENOM):
            try:
                if int(amount[: -len(TESTNET_DENOM)]) >= expected:
                    return True, "verified"
            except ValueError:
                pass
    return False, "no matching transfer to SwayedPay's wallet was found"


async def verify_payment(transaction_id: str, expected_fet: str, buyer_wallet: str, recipient_wallet: str) -> tuple[bool, str]:
    """On-chain check on the Dorado testnet; runs the blocking client in a thread."""
    return await asyncio.to_thread(_verify_sync, transaction_id, expected_fet, buyer_wallet, recipient_wallet)
