{% load i18n %}

::: {{evaluated_box}}
**# {{cspn_eval.stage.cspn_id}} - {{cspn_eval.stage.name|safe}}** ({% language "fr" %}{% translate cspn_eval.status%}{% endlanguage %})  (@sec:{{cspn_eval.get_id_for_section|safe}})
:::
