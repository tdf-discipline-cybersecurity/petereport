def build_report_file_name(
    template_name: str,
    type_name: str,
    report_name: str,
    report_date: str,
    report_extension: str,
) -> str:
    report_n = "".join(
        e if e.isalnum() or e.isspace() or e == "-" else "_" for e in report_name
    )
    type_n = "".join(
        e if e.isalnum() or e.isspace() or e == "-" else "_" for e in type_name
    )
    name_file = f"{template_name}_{type_n}_{report_n}_{report_date}.{report_extension}"

    return name_file


def format_finding_display_id(display_id: str) -> str:
    # Format display_id
    if display_id is not None and display_id != "":
        return f" #{display_id} "
    return ""