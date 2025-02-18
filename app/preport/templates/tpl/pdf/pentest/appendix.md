## {{appendix.title|safe}}

### Details
{{appendix.description|safe}}

{% if findings|length > 0 %}
### Findings
{% for finding in findings %}
Finding Reference: {{finding.display_id|safe}}{{finding.title|safe}} (@sec:{{finding.get_id_for_section|safe}}) 
{% endfor %}
{% endif %}


