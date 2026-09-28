# E10 evidence and submission checklist

These are internal technical notes. The team must write its own final report.
The Assignment 2 brief's GenAI restriction does not permit submitting this
generated handoff as that report.

The checklist follows team document 04 sections 5–8 and the assignment brief.
Document 04's English copy has SHA-256
`68756bb92676c7bd0f0f3d4ed81861cc6c2196178019fab0f60711b7221ab9fc`;
`32113_Assignment_2_2026.pdf` has SHA-256
`571ca7fd5a6e814c0bdd0e97206bfebb35fca0a9348591fecdb5ab0e49057091`.
These identify the reviewed local documents; they are not teacher approvals.

| Item | Existing technical evidence / next owner action |
| --- | --- |
| NSW source model and executable queries | A's [A08 model and evidence](https://github.com/A3939/advance-database-assignment-uts/blob/c1ded1163dbd54b25178a376a059dc75f95f5557/docs/sources/nsw-source-model-and-query-evidence.md). JJ checks the final presentation and explanation. |
| VIC source model and queries | C's [C11 model and evidence](https://github.com/A3939/advance-database-assignment-uts/blob/93158311db8561f3b86fd92c260265aaf04ec5ff/docs/role-c/c11-vic-source-model-and-query-evidence.md). C checks the final revision and preserves restricted-use statements. |
| QLD source model and queries | D's [D10 model and receipts][d10] in the pinned B runtime. D checks the final revision. |
| Integrated warehouse and SQL | A migrations 001–011; B's [frozen inventory][inventory]; C/D/E callbacks and installed SQL. Record their exact submission commit and comments. Each owner explains their part. |
| Three synthetic reports | D's [trend][trend], [severity][severity] and [map][map] reports. D links the accepted E07 batch/result evidence when finalising. |
| Two required technologies and Lab/Fabric demonstration | E and the team confirm the exact course wording and demonstrations with the teacher. PostgreSQL execution alone is not a decision about Fabric. |
| Independent cold start | E arranges a real replay by a member uninvolved in environment setup and records their name, environment and outputs. B-assisted automation remains separately labelled. |
| Final report and demo recording | Team-authored report and actual recording remain pending. Include each member's explanation, dataset limits and the demonstrated revision. |
| Meetings and signatures | At least three actual teacher-signed meeting minutes remain to be supplied. Do not generate attendance, approval or signatures. |
| Individual contributions | Keep original commits, repair PRs, reviews and evidence. B's [Peixian contribution index][contributions] covers one member. Each member supplies their own record. |
| Final submission package | E checks required filenames, templates, links, report/video/SQL/evidence completeness and the agreed tool-use disclosure. Final team/teacher checks remain pending. |

E01 still needs the four real decisions listed in
[`docs/e/e01-course-decisions.md`](../e/e01-course-decisions.md): source
presentation, Lab/Fabric wording, submission package and tool-use disclosure.
Record the date, participants and source of each decision. Until then, retain
the open items rather than filling them with assumed approvals.

Before submission, each member should be able to explain their own module and
one upstream/downstream interaction. Passing automated tests cannot replace
the required meeting records, contributions or demonstration.

[d10]: https://github.com/A3939/advance-database-assignment-uts/blob/1765269507d7cf0b9cb76eef7b9ccf97de7f1cc5/docs/d10-qld-source-model.md
[inventory]: https://github.com/A3939/advance-database-assignment-uts/blob/1765269507d7cf0b9cb76eef7b9ccf97de7f1cc5/config/build-inventory.json
[trend]: https://github.com/A3939/advance-database-assignment-uts/blob/1765269507d7cf0b9cb76eef7b9ccf97de7f1cc5/docs/reports/d11-trend-report.md
[severity]: https://github.com/A3939/advance-database-assignment-uts/blob/1765269507d7cf0b9cb76eef7b9ccf97de7f1cc5/docs/reports/d11-severity-report.md
[map]: https://github.com/A3939/advance-database-assignment-uts/blob/1765269507d7cf0b9cb76eef7b9ccf97de7f1cc5/docs/reports/d11-map-report.md
[contributions]: https://github.com/A3939/advance-database-assignment-uts/blob/1765269507d7cf0b9cb76eef7b9ccf97de7f1cc5/docs/contributions/peixian.md
