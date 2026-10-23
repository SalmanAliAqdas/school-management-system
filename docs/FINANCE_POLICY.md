# Finance operating policy

Phase 5 is a single-school, single-base-currency financial prototype. It records
manual transactions and internal approvals. It does not verify banks, integrate
payment providers, collect card credentials, implement payroll, certify accounting
standards, or claim tax compliance. Financial decisions require school acceptance
and independent professional review before use with real money.

## Setup and daily operation

1. Apply migrations and run `python manage.py sync_roles`.
2. Open `/finance/` as System Administrator or Principal and initialize finance.
   Initialization creates control accounts without economic balances.
3. Configure financial years and non-overlapping periods, manual collection methods,
   fee categories, dated class/section structures and structure charges.
4. Add billing cycles with explicit issue/due dates. Optional holiday adjustment moves
   the entered due date to the next school working date, within 31 days.
5. Preview selected students or an enrolled class at `/finance/billing/`. Confirm the
   exact preview. Repeating a cycle skips existing originals. Generate at most 200
   students per batch; generation reports generated, skipped and failed records.
6. Obtain independent invoice approval where configured, then explicitly issue.
7. Record manual collections at `/finance/collect/`. Choose up to two invoice
   allocations in the collection form. The service accepts additional allocations;
   existing advance credit can be allocated separately. Retain source references.
8. Request corrections/refunds, review the independent decision queue, and inspect
   the journal and financial reports. Reconcile actual statements before closing.

Scheduled operations can use `python manage.py finance_cycle --actor USERNAME
--cycle UUID` to preview, then add `--confirm` to generate drafts in bounded batches.
An operator-controlled scheduler may invoke this command; the application does not
install a background scheduler. Add `--reminders` with `--confirm` for internal
reminder evaluation. Generated invoices are never automatically approved or issued.

## Money, numbering and currency

All monetary calculations use Decimal, with configurable zero to three currency
places and ROUND_HALF_UP rounding. Input rejects floats, non-finite values, excess
precision, negatives where inappropriate and amounts above the numeric limit.
Journal storage uses PostgreSQL numeric(18,3). No foreign exchange is supported.
Currency and precision freeze after financial pricing begins. School-profile currency
cannot diverge from initialized finance. Receipt and invoice formats accept literal
prefixes, one `{year}` and one padded `{seq:06d}` field; annual counters serialize
under the finance lock and unique numbers cannot be reused.

The school currency supplies the initial currency; the fictional demonstration uses
PKR. No balances or bank credentials are embedded in source code.

## Dated enrollment and fee eligibility

A billing cycle covers inclusive calendar dates inside an open academic year.
Available policies are enrollment at cycle start, any overlap charged in full, or
calendar-day proration. Proration uses the cycle's calendar-day denominator, rather
than school working days. Dated transfers split class/section charges at the actual
enrollment boundary. Withdrawn students stop prospective eligible days; graduation,
promotion and later-year enrollment do not rewrite earlier issued documents.

Student assignments override section structures, which override class structures.
A category must resolve to one structure family at a given priority and date;
ambiguous unrelated structures fail validation. A future revision keeps the family,
class, section, year, frequency and assignment scope, and starts later than its
predecessor. Used definitions are protected. Individual assignments may override a
single category amount. Assignment-only structures require a matching student link.

Recurring categories follow their configured cycle frequency. One-time structures
are considered with each cycle but consume a unique student/category/year or
lifetime charge only on issue. Replacement after independently approved voiding is
explicit; it does not create a second original charge for the cycle.

Invoice identity, lines, dates, currency, calculation, class/section, approval and
branding snapshots remain preserved. Current balances, adjustments, allocation
history and reversal status are displayed separately. Later enrollment edits do not
retroactively recompute issued bills.

## Concessions and late fees

School-defined concession types represent merit, need-based, staff-child, sibling,
full-waiver or custom policies. Eligibility is independently verified using brief,
non-sensitive notes. Sibling policy checks shared guardian links and dated enrolled
children. Awards apply only while effective at the invoice issue date.

Overlapping concessions fail unless both the school and every applicable type allow
stacking. Fixed amounts apply before percentages; priority and stable identifiers
break ties. Each percentage applies to the remaining category amount. Per-charge
caps, school ceilings, remaining charge and one-time consumption limit discounts.
New approval does not silently rewrite an existing draft or issued bill.

Late fees are disabled by default. Authorized staff explicitly apply fixed or
percentage policies after the grace period. The percentage uses unpaid eligible
original fee lines, excluding deposits, opening balances and prior penalties. It
never compounds fines. Event buckets prevent duplicate one-time/recurring charges;
the gross fine cap cannot be renewed by a waiver. Dated, independently approved
student exemptions block new penalties. Waivers retain the original fine and add
an independently approved compensating credit.

## Balanced journal and recognition

The permanent journal is the source of financial balances. Every nonzero finalized
event has a unique source key and at least two lines with equal debits and credits.
No mutable student balance column exists. Database triggers protect posted entries,
lines, documents, decisions, source definitions and compensating history. Deferred
commit validation rejects incomplete or unbalanced journal headers.

| Event | Debit | Credit |
| --- | --- | --- |
| Earned fee invoice | Receivable (net), concession contra income | Fee income (gross) |
| Deferred fee invoice | Receivable | Deferred fee liability |
| Unpaid refundable deposit invoice | Receivable | Uncollected deposit liability |
| Opening receivable invoice | Receivable | Opening equity |
| Manual collection | Cash/bank | Student advance liability |
| Allocation | Student advance liability | Student receivable |
| Funding a deposit allocation, additional pair | Uncollected deposit liability | Funded deposit liability |
| Approved advance refund | Student advance liability | Cash/bank |
| Approved funded deposit return | Funded deposit liability | Cash/bank |
| Expense approval | Expense | Expense payable |
| Approved expense disbursement | Expense payable | Cash/bank |
| Cash/bank transfer | Destination cash/bank | Source cash/bank |
| Approved deferred recognition | Deferred liability | Fee income |

Earned categories recognize gross fees on issue and display concession contra income
separately. Deferred categories require explicit independently approved recognition;
collection alone does not recognize income. A later credit first reduces unearned
liability, then reverses recognized income if necessary. Write-offs of deferred or
deposit liabilities are rejected; use a properly authorized credit cancellation.
Ordinary earned receivable write-offs debit the adjustment expense account.

The recognition principle is informed by the [IFRS Foundation's IFRS 15 overview](https://www.ifrs.org/issued-standards/list-of-standards/ifrs-15-revenue-from-contracts-with-customers/),
but the prototype's categories and school policies are not a certification of IFRS
compliance. Database commit checks use PostgreSQL [deferred constraint triggers](https://www.postgresql.org/docs/17/sql-createtrigger.html).

## Allocations, advances, deposits and corrections

One school-wide settings row serializes money mutations. This intentionally favors
prototype correctness over high write throughput. All source documents and balances
are checked again while locked. Unique invoice cycle keys, collection references,
request decisions, receipt numbers and posting source keys provide idempotency.
Replaying a payment token with changed details fails. Allocation targets belong to
the same student, cannot exceed their outstanding amount and cannot spend reserved
or already-used credit. Excess money remains advance credit, rather than invoice
negative debt. No cross-student credit transfer is exposed.

Advance, receivable, funded deposit and uncollected deposit balances remain distinct.
A deposit becomes refundable only when funded. Return of a deposit reduces held
liability and cash, while retaining the paid original invoice.

Corrections require an explicit reason and a different authorized reviewer. Material
amounts, high percentage concessions, exceptional backdates and reopening require
senior approval. Request proposals and completed decisions cannot be overwritten.
Pending credit/deposit/paid-fee refunds reserve the actual funding. Rejection releases
reservations without posting money. Approval revalidates and executes atomically.

A paid ordinary fee refund must be category-refundable. It releases the selected
original allocation, credits the original fee and returns the restored advance,
retaining links to the original payment. Paid invoice credit notes release only
excess allocations as advance. Unpaid, unadjusted invoices may be voided by approval;
paid invoices require explicit credits/refunds instead.

Payment reversal releases active allocations and posts the original collection's
opposite entry. The original payment and receipt remain immutable, with a visible
REVERSED overlay and reason. Payments with refunded funding cannot be reversed;
such cases require separate professional resolution. Compensating journal entries
are dated when corrected and never erase the original event.

## Expenses, reconciliation and closing

Expenses record payee, category, date, value, description and an optional private
PNG/JPEG scan. Uploads are decoded, bounded to 2 MB/16 million pixels, resized and
rewritten without metadata; executable PDFs are not accepted as evidence. A separate
approved expense accrual precedes one manual payment. Attachments require finance
expense permission and are never served through a public media route.

Manual reconciliation selects unreconciled cash/bank journal lines against an actual
statement opening and closing. The opening follows the previous approved statement;
selected net movements must explain the closing exactly. Pending reviews reserve
lines, independent approval preserves the evidence, and rejection retires reservations
without deleting history. Outstanding earlier transactions may clear later. Statements
are sequential; no bank connection or verification is implied.

Closing requires an elapsed period, no unresolved dated requests, and approved
reconciliation of every cash/bank movement. A financial year closes only after all
its periods. New postings into closed dates fail. Senior independently approved
reopening preserves a closing/reopening snapshot and reason. Reopen a closed year
before its periods. Academic-year closure is separate from financial closing.

## Reporting, family access and internal reminders

Reports distinguish issued amounts, collections, receivables, gross recognized income,
concession contra income, expenses, advances and deposits. They provide date/year/class
and overdue filters, aging, monthly collection/billing trends, class outstanding,
category/event revenue, expenses, daily/method/cashier collection summaries and trial
balance/financial position. Invoice/receipt/expense/collection/trial registers export
CSV/PDF. CSV cells are neutralized against spreadsheet formula interpretation.

Invoice filters choose billed cohorts; ledger, credit, deposit, income and expense
metrics remain school-wide for the selected dates. Collections exclude receipts
reversed by the report end date. Cash/bank books retain the actual dated collection,
refund and reversal flows. As-of statements reproduce permanent postings. Reports
are bounded to 5,000 documents/postings and should be narrowed for larger cohorts.

Students and currently linked guardians see permitted issued invoices, receipts,
statements and branded PDFs. Multiple children remain selectable. Portal policy,
role changes and guardian unlinking take effect on every request and notification
read. Financial staff can inspect all student accounts; personal accounts never
receive school-wide journal, expense or report access. Internal notices cover issue,
upcoming/overdue dates, payment/receipt and approved adjustments. Event keys prevent
repeat delivery. No external messaging is sent. Unpaid fees never suspend a student,
block attendance/examinations or withhold results.

## Operational limits

This prototype requires independent financial, security, privacy and operational
validation before real-money use. The database owner is trusted; application roles
are not PostgreSQL users. Coarse locking limits posting throughput. Negative school
cash/bank balances are visible book balances rather than a banking overdraft service;
operators must verify actual funds before disbursement. Refunds after an original
payment has already been partly refunded cannot use the payment-reversal workflow.
One-to-one replacement chains are deliberate and may require a different cycle for
subsequent rebilling. No automated currency conversion, tax engine, bank matching,
chargebacks, external delivery, digital signatures, payroll or production deployment
is included. Physical printing, multilingual PDF fonts, load/concurrency capacity,
backup/restore and retention require operational acceptance. Phase 6 has not begun.
