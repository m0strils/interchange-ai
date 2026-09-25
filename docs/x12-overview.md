# X12 / EDI — quick reference

Public-knowledge seed reference for the ANSI ASC X12 EDI standard.

## What X12 is
ANSI ASC X12 is the dominant EDI standard for B2B document exchange in North
America. A message ("transaction set") is identified by a 3-digit number and is
organized into segments (e.g., ISA/GS envelopes, ST/SE transaction boundaries),
each made of data elements.

## Common transaction sets
- **997 — Functional Acknowledgment:** confirms a received functional group was
  syntactically received (envelope-level ack).
- **824 — Application Advice:** reports application-level acceptance, rejection,
  or errors on a previously received transaction. Used to tell a trading partner
  "we processed your document; here is what passed/failed and why."
- **214 — Transportation Carrier Shipment Status Message:** carrier-to-shipper
  shipment status updates.

## Envelopes (structure)
- **ISA/IEA** — interchange envelope (partner-to-partner).
- **GS/GE** — functional group envelope (groups like transactions).
- **ST/SE** — transaction set envelope (one business document).

## Versions
X12 versions look like `008010`, `008050`, etc. Trading partners must agree on
the version and the implementation guide for each transaction set.
