# SwayedPay

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

**Plan it. Split it. Settle it.** SwayedPay is a team of AI agents inside ASI:One that turns one chat message into a budget-checked group trip plan and a settled bill.

Built for **Fetch-A-Thon 3.0** (ASI:One Agent Challenge: From Intent to Action) by Swayam Jain, team `fetchathon3.0-6852`.

## The problem

Group trips fall apart in WhatsApp. One person compares options across several apps, keeps the budget in their head, and then chases friends for money. Planning and settling live in different places, so the organiser ends up as the unpaid project manager and the bank.

## What SwayedPay does

1. You type the trip in one line in ASI:One: *5 of us, Delhi to Jaipur this Saturday, ₹4,000 each max.*
2. The **Orchestrator** uses ASI1 to extract the intent and asks follow-up questions if something is missing.
3. The **Planner** agent builds 2 to 3 plans. Its budget check starts from the most comfortable option and swaps transport or stay until the plan fits, explaining every swap.
4. You pick a plan by replying or tapping it on an Interactive Card.
5. You say who's in the group and who paid what. The **Settlement** agent splits the total and returns the fewest payments that settle everyone.

The whole workflow runs inside an ASI:One conversation. There is no custom frontend.

## Agents

| Agent | Role | Address |
|---|---|---|
| SwayedPay (orchestrator) | Talks to users in ASI:One over the Agent Chat Protocol; uses ASI1 for intent | `agent1q2s8r5839dwshsem7sttwpkxmy59xvde0hjpms75fnc49hdwlwm0vw43ann` |
| SwayedPay Planner | Budget-checked plans + ASI1 itinerary | `agent1qgfzn38keun49x07dupxwjav4mwv2ql70lrk4rw34tf6tctm282yg95yz28` |
| SwayedPay Settlement | Equal split + minimum transfers | `agent1qw8gejcq8qce9h0qmvdlt423tu6es94utz8wxyuw7dzezmzheku0yzee3r7` |

Agentverse profiles: [add links after registration]

```
User (ASI:One) ⇄ Orchestrator ──PlanRequest──▶ Planner
                     │        ◀─PlanResponse──
                     │        ──SettleRequest─▶ Settlement
                     │        ◀─SettleResponse─
```

**Error recovery:** if a worker agent doesn't answer within 30 seconds, the orchestrator computes the result itself with the same code and tells the user. If ASI1 is unavailable, rule-based parsers take over.

## Run it

Requires Python 3.10+ (built and tested with 3.12).

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in three random seed phrases and your ASI:One API key
make test
```

Start each agent in its own terminal:

```bash
make orchestrator
make planner
make settlement
```

Then connect each one to Agentverse: open the **Agent Inspector** link printed in each terminal (signed in at agentverse.ai), click **Connect**, choose **Mailbox**, and finish. On the orchestrator's Agentverse profile, use **Chat with Agent** to talk to it in ASI:One.

`make addresses` prints the agent addresses for your seeds.

## Try these messages

- `5 of us, Delhi to Jaipur this Saturday, ₹4,000 each max`
- `A` (or tap a plan)
- `Aman, Rahul, Dev, Isha, Kabir. Aman paid 9000, Rahul paid 4250.`
- `new trip` to start over

Sample routes: Delhi ↔ Jaipur, Agra, Rishikesh, Manali; Mumbai ↔ Goa, Lonavala; Bangalore ↔ Coorg, Mysore. Gurugram, Noida and New Delhi count as Delhi. Other routes use labelled generic estimates.

## Tests

`make test` runs unit tests for parsing, the budget check and the settlement maths, plus end-to-end conversation tests with an in-process fake transport (no network needed).

## Honest scope

- Prices are **sample estimates** for the demo, not live fares or hotel rates. Every reply says so.
- **No real money moves.** Settlement produces a list of who pays whom.
- Itineraries from ASI1 are suggestions, not bookings.

## Built with

[uAgents](https://github.com/fetchai/uAgents), Agentverse, the Agent Chat Protocol, ASI:One / ASI1 and ASI:One Interactive Cards, starting from Fetch.ai's [innovation-lab-examples](https://github.com/fetchai/innovation-lab-examples) quickstarter.
