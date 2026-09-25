# Rail EDI — quick reference

Public-knowledge seed reference for the X12/EDI + rail domain.

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

## Platform design notes
A cloud event-driven EDI platform of this kind is typically assembled from
managed containers behind an event bus, with queues for asynchronous
processing, object storage for payloads, and a relational store for state. A
JVM service stack (Java / Spring Boot) does the parsing and validation, and a
validation → Application Advice (824) feedback loop reports processing results
back to the sending trading partner. Rounding out the design: partner
onboarding rules, a version matrix (for example, two X12 releases in flight at
once), error-handling and supersede logic, and per-partner SLAs.
