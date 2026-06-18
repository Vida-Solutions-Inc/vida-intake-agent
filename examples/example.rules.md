# Example intake routing rules

Drop a file like this at your repo root as `intake.rules.md` (or wherever your
config's `rules_file` points) to give the agent domain rules on top of its
general judgement and the live folder structure. Everything here is illustrative
- replace it with your own.

## Where things go
- Vendor receipts / invoices -> `admin/Finance/Expenses/Vendors/<Vendor>/`
- Invoices you sent to clients -> `admin/Finance/Revenue/`
- Bank / credit-card statements -> `admin/Finance/Banking/<Account>/`
  (e.g. Checking, Business Card)
- Payroll documents -> `admin/Finance/Payroll/`
- Tax filings -> `admin/Finance/Tax/`
- Company formation, articles, EIN -> `admin/Legal/Formation/`
- Insurance policies -> `admin/Legal/Insurance/`
- Client deliverables and meeting notes -> `clients/<client>/`
- Active sales proposals / RFPs -> `sales/opportunities/active/<deal>/`
- Closed deals -> `sales/opportunities/closed/<deal>/`
- Event tickets, conference receipts -> `admin/Finance/Expenses/Events/`

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
