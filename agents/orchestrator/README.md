# SwayedPay: group trip planner and bill settler

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

SwayedPay plans a group trip that fits your budget and then settles who owes whom, all in one chat.

Tell it the trip in one line. It understands the request with ASI1, asks a Planner agent for budget-checked options, lets you pick one, then asks a Settlement agent to split the cost into the fewest payments.

## Try it

- `5 of us, Delhi to Jaipur this Saturday, ₹4,000 each max`
- `4 friends from Mumbai to Goa for 2 nights, budget 9000 per person`
- After picking a plan: `Aman, Rahul, Dev, Isha, Kabir. Aman paid 9000, Rahul paid 4250.`

## What it returns

- 2 to 3 plans (transport + stay) with a per-person cost breakdown, and the steps it took to fit your budget
- A short day-by-day itinerary suggestion
- A settlement list: who pays whom, and how much

## Honest scope

Prices are sample estimates for the demo, not live fares. No real money is moved.

## Built with

uAgents, Agentverse, Agent Chat Protocol, ASI:One / ASI1. Part of Fetch-A-Thon 3.0.
