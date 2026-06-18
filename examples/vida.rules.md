# Intake routing rules - Vida Solutions, Inc.

Drop this file at the repo root as `intake.rules.md` to give the agent Vida's
domain specifics on top of the live folder structure.

## Where things go
- Vendor receipts/invoices -> `admin/Finance/02_Expenses/Vendors/<Vendor>/`
- Client invoices Vida sent -> `admin/Finance/01_Revenue/`
- Bank / credit-card statements -> `admin/Finance/03_Banking/<Account>/`
  (Chase Checking, Chase Ink, Chase Sapphire, BitPay, etc.)
- Payroll docs -> `admin/Finance/04_Payroll/`
- Tax filings, IRS, FL DoR -> `admin/Finance/05_Tax/`
- LLC formation, articles, EIN -> `admin/Legal/01_Formation/`
- Compliance filings, annual reports -> `admin/Legal/03_Compliance/`
- Insurance policies -> `admin/Legal/05_Insurance/`
- Active sales pipeline (proposals, RFPs) -> `sales/opportunities/active/<deal>/`
- Closed deals -> `sales/opportunities/closed/<deal>/`
- Event tickets, conference receipts -> `admin/Finance/02_Expenses/Events/`

## Client aliases
- `intandem`, `skaled`, `intandem-skaled` -> `clients/intandem-skaled/`
- `openwacca` -> `clients/openwacca/`
- `equashield` -> `clients/equashield/`

## Naming conventions
- Match the dominant sibling pattern in the destination folder, e.g.
  `YYYY_Vendor_Invoice-<num>.pdf` or `YYYY-MM-DD_vendor_doctype.pdf`.

## Hard rules
- Never route to `offerings/` - that is product code, not documents.
- Never route source code, scripts, or config files.
