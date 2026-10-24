# Analytics dictionary

All dashboard values are calculated at request time from authoritative PostgreSQL records. Filters
are inclusive, clipped to the selected academic year, and limited to two years. Empty source data
is displayed as unavailable rather than zero when a denominator would be misleading.

| KPI | Meaning and source | Numerator / denominator | Exclusions and permission |
| --- | --- | --- | --- |
| Active students | Distinct students in `people.Enrollment` overlapping the window | Distinct student IDs / not applicable | Placements outside the year/window; `core.view_executive_analytics` |
| Admissions | `Student.admission_date` in the window | Records / not applicable | Records outside the window |
| Withdrawals | Placements ending with explicit `withdraw` reason | Records / not applicable | Transfers, promotions and graduations |
| Student attendance | Phase 3 finalized attendance entries | Present credit plus configured late credit / eligible entries | Blank entries; policy-excluded excused entries; missing registers are not absences |
| Staff attendance | Phase 3 finalized staff entries | Present/duty/late credit plus half-day credit / eligible entries | Leave, closure and blank entries |
| Published performance | Immutable `PublishedResult` snapshots | Published snapshots / not applicable | Draft marks, unpublished sessions, withheld source marks |
| Issued invoices | Issued invoice document totals | Sum of issued totals | Draft/approved-only and voided invoices; requires finance-report permission |
| Collections | Posted manual payment documents | Posted amount less effective reversals | Pending/rejected/reversed receipts; never labeled revenue |
| Approved expenses | Approved expense documents | Approved amount | Pending/rejected requests; separate from disbursement |
| Payroll obligation | Released/paid payslip snapshots | Net pay | Draft, held and reversed slips; hidden without aggregate payroll permission |
| Library overdue | Issued loans past their recorded due timestamp | Count | Returned/lost/damaged closed loans |
| Transport allocation | Effective student trip assignments | Count | Assignments outside the selected window |

Finance revenue, advances, deposits, receivables, collections and expenses retain the separate Phase
5 definitions. Operational purchase cost is not asset valuation. Metrics refresh on each request;
there is no background cache or data warehouse. Definition changes require tests and documentation.
