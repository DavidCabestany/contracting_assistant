"""Prompt templates used for risk related queries"""

RISK_MATRIX_ALL_RISKS_PROMPT2 = """Kindly provide details related to the clauses mentioned below in the format below -
If nothing is present for particular clause provide "NA" in details.Do not infer or invent details based on the context or description—these are provided only to help you understand what to look for.
```json
{{
  "Termination Clause"(It addresses the conditions and procedures under which a contract may be ended before its agreed expiration. It outlines who can terminate, on what grounds (such as convenience or breach), the notice periods required, and what happens after termination, including handover, transition, and settlement of outstanding obligations. This ensures both parties understand their rights and responsibilities if the contract ends early.)                                                                                                                                                                                                                                                                                                                  : "Provide the details in contract"
  "Liability Clause"(It addresses the extent to which each party is responsible for losses, damages, or claims arising from the contract. It sets any financial limits (caps) on liability, details any exceptions (such as for personal injury or breaches of confidentiality), and outlines what types of losses are included or excluded. The clause clarifies the parties’ obligations in the event of a problem and helps allocate risks and responsibilities clearly under the contract.)                                                                                                                                                                                                                                                                                      : "Provide the details in contract"
  "Compliance Requirements"(It addresses adherence to relevant laws, regulations, and industry standards as set out in the contract. It covers subjects such as liability for breaches (including data protection, intellectual property, and cybersecurity); requirements for sustainability commitments; obligations regarding audit rights and flow-down clauses; and compliance with anti-bribery, anti-corruption, modern slavery, data protection, and diversity-related obligations.)                                                                                                                                                                                                                                                                                         : "Provide the details in contract"
  "Sustainability Terms"(It relates to environmental, social, and governance (ESG) considerations. It covers requirements such as alignment with sustainability frameworks (e.g., CDP, SBTi), commitments to reduce environmental impact, verified greenhouse gas reduction targets, renewable energy sourcing, compliance with AstraZeneca’s Supplier Expectations or Code of Ethics, provision of ESG data, diversity measures, and acceptance of audits and traceability.)                                                                                                                                                                                                                                                                                                        : "Provide the details in contract"
  "Payment Terms"(The Payment Terms clause governs the methods, timing, and conditions for payments between the parties. It specifies AstraZeneca’s standard payment periods—75 days from receipt of a correct and undisputed invoice for most regions, 60 days within the United Kingdom and the European Union, and 45 days within France and for recurring invoices. The clause also addresses requirements such as payments being linked to receipt (not just the invoice date), adherence to the “No PO, No Pay” rule, proper documentation and approval of any deviations, controls over pass-through costs, and compliance with electronic transaction platforms. This ensures clear expectations and compliance with both AZ policies and regional regulations.)             : "Provide the details in contract"
  "Performance Metrics"(It defines how the contract’s success will be measured and assessed. It sets out specific metrics, such as service levels, operational efficiency indicators, or compliance targets, and describes the consequences for meeting or missing those metrics. These may include informational or developmental measures, moderate metrics affecting efficiency and satisfaction, or strict, auditable metrics with remedies or penalties for non-compliance—especially when performance impacts regulatory, financial, or reputational matters for AstraZeneca. The clause ensures clear expectations for performance and accountability under the contract.)                                                                                                    : "Provide the details in contract"
  "Confidentiality Clause"(It protects sensitive information shared during the contract. It defines the obligations of each party to safeguard confidential data—such as clinical, patient, or proprietary research data—against unauthorized disclosure or use. The clause sets out restrictions on sharing information with subcontractors or third parties, specifies how breaches are handled, and may include conditions on liability, enforcement, and the duration of confidentiality commitments. This ensures confidential information is handled appropriately and in line with agreed contract terms.)                                                                                                                                                                    : "Provide the details in contract"
  "Dispute Resolution"(It outlines the procedures for resolving disagreements or conflicts arising under the contract. It defines the steps parties must follow, which may include structured escalation, good faith negotiation, optional mediation, and—if needed—arbitration or litigation. The clause may specify preferred jurisdictions, require ongoing contract performance during disputes, and ensure the process is fair, balanced, and clearly defined for both parties)                                                                                                                                                                                                                                                                                                 : "Provide the details in contract"
  "Force Majeure Clause"(The Force Majeure Clause excuses parties from their contractual obligations when unforeseen events beyond their control occur. Key aspects may include requirements to notify and mitigate, clear definitions of qualifying events, exclusion of relief for events caused by a party’s own fault or foreseeable issues, continuation of unaffected services, no price increases due to force majeure, and the ability for parties to terminate or engage alternatives after prolonged disruption. Well-defined clauses ensure fairness and protect against misuse or supplier exploitation.)                                                                                                                                                                : "Provide the details in contract"
  "Renewal Terms"(It defines the conditions and procedures for extending a contract. It typically covers whether renewal is automatic or requires explicit written agreement, specifies notification periods for renewal, and ensures renewal terms are transparent and subject to review. Well-drafted clauses prevent unintended or perpetual renewals, prohibit automatic renewals without the right to opt out, require all renewals to be documented, and ensure no additional obligations or costs are imposed without clear approval. This promotes clarity, compliance, and control over contract continuations)                                                                                                                                                             : "Provide the details in contract"
}} ```
Document Content:
{Contract}
"""

RISK_MATRIX_CATEGORY = """Kindly fill in the risk_score in the json and return it, depending upon the risk_rules.scenario_description as per below scale
category : risk_score
High : 8-10
Medium : 5-7
Low : 1-4
identified_clauses : {identified_clauses}
risk_rules :{risk_rules}
Output Json :
```json
{{
  "Termination Clause" {{"details": "details in contract", "risk_score": "risk_score_value","reason":"reason why you chose this score"}},
  // ... more clauses
}}```
"""


RISKS_SUMMARY = """Based on the detailed risk assessment provided below, please generate a concise overall summary of the key risks present in the contract.
This summary should be a short narrative (2-4 sentences) highlighting the most critical areas of concern and providing a general sentiment about the contract's risk profile.
Do not list all the risks again; provide a high-level synthesis.

Detailed Risk Assessment Findings:
{contract_clauses}
{additional_clauses}


Concise Overall Risk Summary:
"""



ADDITIONAL_RISKS = """
Given the contract content below, and a list of already identified standard clause-based risks,
please identify any other potential risks or concerns that are not explicitly covered by the standard clauses.
Focus on ambiguities, omissions, or terms that could pose a business, legal, or operational risk.

Already Identified Clauses:
{clauses}

Contract:
{contract}

If no additional risks are found, return an empty list []

```json
[
{{
  "title: "title_name"
  "description": "Provide the details of that additional clauses in contract", 
   // ... more additional clauses if any.
}}
]
```
"""


USER_QUERY_RISKS = """
You are a clause identifier assistant. Provide me a list of clauses that are explicitly asked by a user from the defined clauses list. 
User Query:
{Query}
Clauses:
{Clauses}

*Instructions:*
Ensure each clause is actually present in the supplied "Clauses" list. Do not invent new clauses.

Output:
```json
[
{{
"clause_name":xxx,
"clause_name":yyyy,
.....
}}
]
```
"""

RISK_MITIGATION_PROMPT = """
You are a helpful and precise assistant specializing in analyzing document content and leveraging conversation history to provide mitiagtion to the above risks.
Content:
{content}

User Query:
{Query}
"""