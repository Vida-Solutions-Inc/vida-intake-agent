# Example intake routing rules

Drop a file like this at your repo root as `intake.rules.md` (or wherever your
config's `rules_file` points) to give the agent domain rules on top of its
general judgement and the live folder structure. Everything here is illustrative
- replace it with your own.

## Where things go
- Vendor receipts / invoices -> `finance/Expenses/Vendors/<Vendor>/`
- Invoices you sent to clients -> `finance/Revenue/` <!-- ref: historical -->
- Bank / credit-card statements -> `finance/Banking/<Account>/`
  (e.g. Checking, Business Card)
- Payroll documents -> `finance/Payroll/` <!-- ref: historical -->
- Tax filings -> `finance/Tax/` <!-- ref: historical -->
- Company formation, articles, EIN -> `legal/Formation/` <!-- ref: historical -->
- Insurance policies -> `legal/Insurance/` <!-- ref: historical -->
- Client deliverables and meeting notes -> `clients/<client>/`
- Active sales proposals / RFPs -> `sales/opportunities/active/<deal>/`
- Closed deals -> `sales/opportunities/closed/<deal>/`
- Event tickets, conference receipts -> `finance/Expenses/Events/` <!-- ref: historical -->

## Aliases
Map the messy names that show up on documents to your canonical folder names:
- `acme`, `acme corp`, `acme inc` -> `clients/acme/` <!-- ref: historical -->
- `globex` -> `clients/globex/` <!-- ref: historical -->

## Naming conventions
- Match the dominant sibling pattern in the destination folder, e.g.
  `YYYY-MM-DD_<vendor>_<doctype>.pdf` or `YYYY_<Vendor>_Invoice-<num>.pdf`.

## Hard rules
- Never route source code, scripts, or config files.
- Never route into `<some/product/code/path>/` (adjust to your repo).
