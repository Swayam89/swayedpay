# SwayedPay Settlement

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

Worker agent for SwayedPay. It receives the group members and who paid what from the SwayedPay orchestrator, splits the total equally in whole rupees, and returns the smallest set of payments that settles everyone.

No real money is moved. The result is a list the group can act on.

Message models: `SettleRequest` in, `SettleResponse` out.
