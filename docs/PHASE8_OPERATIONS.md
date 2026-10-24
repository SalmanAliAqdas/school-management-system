# Phase 8 school operations

Phase 8 adds six PostgreSQL-backed applications without replacing existing people, attendance,
leave, finance, enrollment, portal, or notification records.

## HR policy

`hr.Employee` links exactly one existing staff or teacher identity. Effective-dated employment
records preserve department, designation, manager, contract, probation, departure, and rejoining
history. Leave balances use existing attendance leave requests; missing attendance is never an
absence. HR documents are validated, stored privately, and served only by an authorized endpoint.
Performance, notes, and documents remain confidential.

## Payroll and finance

Effective-dated salary revisions use `Decimal`; generation snapshots component and period policy.
Runs progress through draft, submission, independent approval, finalization, payment, and optional
authorized reversal. Finalization posts balanced expense/deduction/payable lines through the Phase
5 ledger, payment clears the payable, and reversal creates a linked inverse journal. Existing
closed-period controls apply. Employees see only released payslips. PKR is demo-only; there is no
statutory-tax or legal-compliance claim.

## Library and transport

Library titles and accessioned copies are separate. Existing student/staff memberships use
configurable limits, durations, renewals, grace periods, fines, transaction-safe issue/return, and
FIFO reservations. Fines do not automatically become invoices.

Transport records vehicles, ordered stops, effective trips, eligible drivers/attendants, student
assignments, maintenance, inspections, notices, and incidents. Services reject conflicts, invalid
stops, inactive resources, and over-capacity assignments. Guardians see linked children only. No
GPS, live tracking, or emergency-response promise is made.

## Inventory and assets

Stock derives from finalized movements, never an editable balance. Item locking prevents concurrent
over-issue. Corrections are compensating entries. Durable assets retain custody, location,
condition, warranty, maintenance, transfer, and independently approved disposal events. Values are
operational purchase references, not audited valuation or depreciation.

## Certificates

Requests require subject authorization, review, independent approval, and issuance. Issued records
snapshot wording, identity, and signatory and use a random URL-safe verification token. Revocation
preserves history. Public verification returns only school, document type, issue date, and status;
it never returns the full PDF or private identity/guardian data.

## Security and limitations

Mutations are CSRF-protected and permission checked; family, employee, borrower, and custodian
views are object scoped. Sensitive bytes/PDFs use protected endpoints and material changes are
audited. This is a development prototype pending local employment, payroll, tax, accounting,
safety, retention, privacy, and accessibility review. It has no banking, payment-gateway, GPS,
government identity, paid messaging, or statutory tax integration.
