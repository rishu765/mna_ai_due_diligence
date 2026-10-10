# Synthetic VDR fixture

`ma_due_diligence.vdr_fixtures.create_fixture_vdr()` reproducibly creates the small fictitious
Northstar Components data room used by tests, evaluation, and the offline demo. PDF and XLSX files
are generated locally so the repository does not store opaque binaries.

The fixture includes audited statements, monthly management accounts, customer sales, customer and
supplier contracts, a debt schedule, a budget/forecast, two management-presentation versions, a
board memo, an exact duplicate supplier contract, and one unsupported binary file.

Built-in unresolved differences include FY2025 revenue of GBP 92 million in audited statements,
GBP 95 million in management accounts and customer sales, and GBP 100 million in the management
presentation. The sales report shows 42% customer concentration while management materials state
that no concentration issue exists. M1/2 retrieves these contexts but does not resolve them.
