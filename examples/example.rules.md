# Example intake routing rules

Drop a file like this at your repo root as `intake.rules.md` (or wherever your
config's `rules_file` points) to give the agent domain rules on top of its
general judgement and the live folder structure. Everything here is illustrative
- replace it with your own.

## Where things go
- Vendor receipts / invoices -> `finance/Expenses/Vendors/<Vendor>/`
- Invoices you sent to clients -> `finance/Revenue/`
- Bank / credit-card statements -> `finance/Banking/<Account>/`
  (e.g. Checking, Business Card)
- Payroll documents -> `finance/Payroll/`
- Tax filings -> `finance/Tax/`
- Company formation, articles, EIN -> `legal/Formation/`
- Insurance policies -> `legal/Insurance/`
- Client deliverables and meeting notes -> `clients/<client>/`
- Active sales proposals / RFPs -> `sales/opportunities/active/<deal>/`
- Closed deals -> `sales/opportunities/closed/<deal>/`
- Event tickets, conference receipts -> `finance/Expenses/Events/`

## Aliases
Map the messy names that show up on documents to your canonical folder names:
- `acme`, `acme corp`, `acme inc` -> `clients/acme/`
- `globex` -> `clients/globex/`

## Naming conventions
- Match the dominant sibling pattern in the destination folder, e.g.
  `YYYY-MM-DD_<vendor>_<doctype>.pdf` or `YYYY_<Vendor>_Invoice-<num>.pdf`.

## Hard rules
- Never route source code, scripts, or config files.
- Never route into `<some/product/code/path>/` (adjust to your repo).
