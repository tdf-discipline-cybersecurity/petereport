{% load i18n %}

## {{finding.display_id|safe}}{{finding.title|safe}} {#sec:{{finding.get_id_for_section|safe}}}

::: {{icon_finding}}
**{% translate "Severity" %}** \textcolor{{"{"|add:severity_color|add:"}{"|add:finding.severity|add:"}"}} 



{% if finding.cvss_base_score != "0" %}
**{% translate "CVSS Score" %}** [{{finding.cvss_base_score|safe}}](https://www.first.org/cvss/calculator/{{finding.report.cvss_version|safe}}#{{finding.get_cvss_score_anchor|safe}})
{% endif %}

**{% translate "Status" %}** {{finding.status}}
:::

**{% translate "OWASP" %}** [OWASP-{{finding.owasp.owasp_full_id}} - {{finding.owasp.owasp_name|safe}}]({{finding.owasp.owasp_url}})

{% if finding.description %}
**{% translate "Description" %}**

{{finding.description|safe}}
{% endif %}

{% if finding.poc %}
**{% translate "Proof of Concept" %}**

{{finding.poc|safe}}
{% endif %}

{% if finding.location %}
**{% translate "Location" %}**

{{finding.location|safe}}
{% endif %}

{% if finding.impact %}
**{% translate "Impact" %}**

{{finding.impact|safe}}
{% endif %}

{% if finding.recommendation %}
**{% translate "Recommendation" %}**

{{finding.recommendation|safe}}
{% endif %}

{% if finding.ref %}
**{% translate "References" %}**

{{finding.ref|safe}}
{% endif %}

{% if template_custom_fields %}
{{template_custom_fields | safe}}
{% endif %}
