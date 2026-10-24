# SwayedPay: plan the trip, split the bill, settle up. All in one ASI:One chat.

**Built for Fetch-A-Thon 3.0 | ASI:One Agent Challenge: From Intent to Action**
Builder: Swayam Jain | Team: fetchathon3.0-6852

## The problem
Group plans in India die in WhatsApp. For a weekend trip, a college fest or a team offsite, one person ends up as the unpaid project manager. They compare options across five apps, keep a budget in their head, chase 6 friends for money and still end up out of pocket.

Existing AI assistants stop at *"here are some suggestions"*. Nobody actually plans, costs and settles it.

## The solution
**SwayedPay** is a team of AI agents you talk to inside ASI:One, with no app and no custom frontend. You say one sentence:

> "5 of us, Delhi to Jaipur this Saturday, ₹3,000 each max."

Then the agents take over:

1. **Planner Agent** understands the intent and builds a multi-step plan: transport, stay, food and a day itinerary.
2. **Budget Agent** checks the plan against the group's limits and swaps options until it fits.
3. **Settlement Agent** splits costs per person, using the Fetch.ai Payment Protocol (test mode) to raise payment requests and track who has paid.
4. The user reviews and approves the plan on an **ASI Interactive Card**. One tap confirms it.

**Intent in. Executable, paid-for plan out.**

## Target users
College students, young professionals and friend groups in India who travel or organise events together, plus anyone who has ever been the one who "paid for everyone".

## Outcome
A confirmed itinerary within budget, per-person amounts calculated, and payment requests sent. The organiser stops being the bank.

## Why it fits the challenge
| Requirement | How SwayedPay meets it |
|---|---|
| Registered on Agentverse | Planner, Budget and Settlement agents |
| Agent Chat Protocol | Every agent speaks ACP |
| Discoverable and usable in ASI:One | Whole flow runs inside one chat |
| Multi-agent orchestration | Three specialised agents hand work to each other |
| Payment Protocol (bonus) | Settlement Agent raises and tracks payments |
| Interactive Cards (bonus) | Plan review and approval screen |
| Real-world usefulness | A problem every friend group has |

## Scope note (honest)
Payments will run in test mode for the demo. Live pricing depends on the data and APIs available during the 8 hours, with a fallback to mock data if one fails.
