{% load i18n %}

---

title: "{{DB_report_query.title}}"
customer: "{{DB_report_query.product.customer.name}}"
product: "{{DB_report_query.product.name}}"
author: ["{{md_author}}", "Report ID: {{DB_report_query.report_id}}"]
date: "{{report_date}}"
subject: "{{md_subject}}"
subtitle: "{{DB_report_query.report_id}}"
website: {{md_website}}

---

# {% translate "Pentest Overview" %}

{% if DB_report_query.product.description %}
## {% translate "Product Description" %}

{{DB_report_query.product.description | safe}}
{% endif %}

{% if DB_report_query.audit_objectives %}
## {% translate "Audit Objectives" %}

{{DB_report_query.audit_objectives | safe}}
{% endif %}

{% if DB_report_query.methodology %}
## {% translate "Methodology" %}

{{DB_report_query.methodology | safe}}
{% endif %}

{% if DB_report_query.scope or DB_report_query.outofscope %}
## {% translate "Scope" %}

{% if DB_report_query.scope %}
### {% translate "In Scope" %}

{{DB_report_query.scope | safe}}
{% endif %}

{% if DB_report_query.outofscope %}
### {% translate "Out of Scope" %}

{{DB_report_query.outofscope | safe}}
{% endif %}
{% endif %}

# {% translate "Executive Summary" %}

{% if DB_report_query.executive_summary %}
## {% translate "Review" %}
{{DB_report_query.executive_summary | safe}}
{% endif %}

{% if DB_report_query.recommendation %}
## {% translate "Recommendations" %}

{{DB_report_query.recommendation | safe}}
{% endif %}


{% if counter_finding > 0 %}
## {% translate "Summary of Findings Identified" %}

There were a number of findings during the assessment including the following:

{{finding_summary | safe}}

![Executive Summary]({{report_executive_summary_image}})

![Breakdown by OWASP Categories]({{report_owasp_categories_image}})
{% endif %}

{% if counter_finding > 0 %}
# {% translate "Findings Details" %}
The following are the list of findings with technical details and proof of concept.
{{template_findings | safe}}
{% endif %}

{% if counter_appendix > 0 %}
# Additional Notes
{{template_appendix | safe}}
{% endif %}

{% if counter_attackflow > 0 %}
# Attack Flows
{{template_attackflows | safe}}
{% endif %}
