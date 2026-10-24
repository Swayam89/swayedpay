# SwayedPay Planner

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

Worker agent for SwayedPay. It receives a structured trip request (origin, destination, group size, budget per person, nights) from the SwayedPay orchestrator and returns 2 to 3 plans.

- Starts from the most comfortable transport and stay, then swaps one component at a time until the plan fits the per-person budget, logging each swap.
- Adds a short itinerary written by ASI1.
- Prices are sample estimates for the demo, not live fares.

Message models: `PlanRequest` in, `PlanResponse` out.
