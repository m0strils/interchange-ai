# Rail EDI — quick reference (SAMPLE SEED — replace with your own notes)

> Illustrative seed content. Swap in your your EDI platform design notes,
> trading-partner rules, and transaction-set implementation guides.

## Rail industry EDI
North American freight/passenger rail exchanges standardized EDI, historically
coordinated through AAR (Association of American Railroads) conventions layered
on ANSI X12. Interchange happens between railroads ("Class I" carriers) and
trading partners.

## Transaction sets often seen in rail
- **161 — Train Sheet:** train consist / movement information exchanged between
  railroads.
- **404 — Rail Carrier Shipment Information:** shipment/waybill data to a rail
  carrier.
- **417 — Rail Carrier Waybill Interchange:** waybill exchange between carriers.
- **990 — Response to a Load Tender:** accept/decline a tendered load.
- **824 — Application Advice:** report processing results/errors back to the
  sending partner (widely used to signal validation failures).

## Platform design notes (fill in your specifics)
- Trading partners: Class I railroads + additional partners.
- Transaction sets in scope: e.g., 161 and 824.
- Reliability target and architecture: event-driven on AWS (ECS, EventBridge,
  SQS, S3, Aurora); Java 17 / Spring Boot / Kafka; validation → Application
  Advice (824) feedback loop.
- Add: partner onboarding rules, version matrix (e.g., 008010 / 008050),
  error-handling and supersede logic, SLAs.
