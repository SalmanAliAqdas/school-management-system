# User acceptance tests

Record tester, date, environment, scenario and pass/fail evidence. Use fictional data only.

| Role | Prerequisite and action | Expected result / boundary |
| --- | --- | --- |
| Administrator | Seed disposable demo; admit/link a student | New history is saved; unrelated credentials remain unchanged |
| Principal | Filter executive analytics by year/date | KPIs match source records; no individual salary appears |
| Academic coordinator | Review attendance and published results | Missing registers are not absences; draft marks are excluded |
| Teacher | Open assigned student progress; release feedback | Assigned roster only; unreleased feedback remains private |
| Student | Open progress, homework and certificate | Self only; published/released records only |
| Guardian | Switch two linked children, then tamper with another ID | Linked children work; unrelated student returns not found |
| Accountant | Compare finance report, trial balance and analytics | collections/revenue/deposits remain distinct and journals balance |
| HR officer | Review staff attendance/expiry findings | Confidential documents/reviews remain restricted |
| Payroll officer | Generate and submit payroll | Decimal snapshot is created; officer cannot self-approve |
| Librarian | Issue/return a copy and export circulation | One active borrower per copy; export is scoped/audited |
| Transport coordinator | Assign a route near capacity | Valid assignment succeeds; over-capacity/conflict is rejected |
| Inventory manager | Issue stock and review low stock/assets | Balance derives from movements; negative issue is rejected |

Cross-module acceptance also covers protected PDFs, keyboard navigation, 320/390px layouts, explicit
empty states, direct URL authorization and CSV formula safety.
