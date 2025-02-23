# -*- coding: utf-8 -*-
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User, Group
from django.http import (
    HttpResponse,
    HttpResponseNotFound,
    HttpResponseServerError,
    Http404,
)
from django import forms

from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.template import TemplateDoesNotExist
from django.template.loader import render_to_string
from django.utils.safestring import mark_safe
from django.core.files.storage import FileSystemStorage
from django.utils.translation import gettext_lazy as _
from django.utils.functional import Promise
from django.utils.encoding import force_str
from django.core.serializers.json import DjangoJSONEncoder
from django_sendfile import sendfile
from dal import autocomplete
from taggit.models import Tag
import uuid
import time
import re

import preport.utils.fts as ufts
import preport.utils.urls as uurls
import preport.utils.sharing as ushare
import preport.utils.utils as uutils

import django.db

# Forms
from .forms import (
    CustomDeliverableReportForm,
    NewSettingsForm,
    NewCustomerForm,
    NewProductForm,
    NewReportForm,
    NewShareForm,
    NewFindingForm,
    NewAppendixForm,
    NewFindingTemplateForm,
    AddUserForm,
    NewAttackFlowForm,
    NewCWEForm,
    NewOWASPForm,
    NewFieldForm,
    NewFTSForm,
    NewCSPNEvaluationForm,
    ReportToCloneForm,
)


# Model
from .models import (
    DB_Deliverable,
    DB_Bookmark,
    DB_Report,
    DB_ShareConnection,
    DB_Settings,
    DB_CSPN_Evaluation,
    DB_Finding,
    DB_Customer,
    DB_Product,
    DB_Finding_Template,
    DB_Appendix,
    DB_CWE,
    DB_OWASP,
    DB_Custom_field,
    DB_AttackFlow,
    DB_FTSModel,
)


# Decorators
from .decorators import allowed_users

# Libraries
import datetime
import textwrap
import requests
import base64
import bleach
import json
import csv
import io
import os
import pathlib
from collections import Counter
import pypandoc

from timeit import default_timer as timer

# Martor
from petereport.settings import (
    BASE_DIR,
    DEBUG_PANDOC_ON_ERROR,
    MAX_IMAGE_UPLOAD_SIZE,
    UPLOAD_DIRECTORY,
    MARTOR_UPLOAD_PATH,
    MARTOR_MEDIA_URL,
    MEDIA_ROOT,
    TEMPLATES_ROOT,
    REPORTS_MEDIA_ROOT,
    TEMPLATES_DIRECTORIES,
)

# PeTeReport config
from config.petereport_config import (
    PETEREPORT_MARKDOWN,
    PETEREPORT_CONFIG,
    PETEREPORT_TEMPLATES,
    DEFECTDOJO_CONFIG,
)

import logging

logger = logging.getLogger(__name__)


clean_html_tag_regexp = re.compile("<.*?>")


# Not all Django output can be passed unmodified to json. In particular, lazy
# translation objects need a special encoder written for them.
# https://docs.djangoproject.com/en/1.8/topics/serialization/#serialization-formats-json
class LazyEncoder(DjangoJSONEncoder):
    def default(self, obj):
        if isinstance(obj, Promise):
            return force_str(obj)
        return super(LazyEncoder, self).default(obj)


class TagAutoComplete(autocomplete.Select2QuerySetView):
    def get_queryset(self):
        if not self.request.user.is_authenticated:
            return Tag.objects.none()
        qs = Tag.objects.all()
        if self.q:
            qs = qs.filter(name__contains=self.q)
        return qs


# ----------------------------------------------------------------------
# https://github.com/agusmakmun/django-markdown-editor/wiki
# ----------------------------------------------------------------------
@login_required
def media_uploads_sendfile(request, upload_path):
    return sendfile(request, upload_path)
    # sendfile(request, upload_path, attachment=False, attachment_filename=None, mimetype=None, encoding=None)


@login_required
def markdown_uploader(request):
    """
    Makdown image upload for locale storage
    and represent as json to markdown editor.
    """
    if (
        request.method == "POST"
        and request.headers.get("X-Requested-With") == "XMLHttpRequest"
    ):
        if "markdown-image-upload" in request.FILES:
            image = request.FILES["markdown-image-upload"]
            image_types = [
                "image/png",
                "image/jpg",
                "image/jpeg",
                "image/pjpeg",
                "image/gif",
            ]
            if image.content_type not in image_types:
                data = json.dumps(
                    {"status": 405, "error": _("Bad image format.")}, cls=LazyEncoder
                )
                return HttpResponse(data, content_type="application/json", status=405)

            # DJANGO 1.11: if image._size > settings.MAX_IMAGE_UPLOAD_SIZE:
            # DJANGO 2.0
            if image.size > MAX_IMAGE_UPLOAD_SIZE:
                to_MB = MAX_IMAGE_UPLOAD_SIZE / (1024 * 1024)
                data = json.dumps(
                    {
                        "status": 405,
                        "error": _("Maximum image file is %(size) MB.")
                        % {"size": to_MB},
                    },
                    cls=LazyEncoder,
                )
                return HttpResponse(data, content_type="application/json", status=405)

            if PETEREPORT_MARKDOWN["martor_upload_method"] == "BASE64":
                image_content_base64 = base64.b64encode(image.read()).decode("utf-8")
                image_content_base64_final = (
                    "data:" + image.content_type + ";base64," + image_content_base64
                )

                data = json.dumps(
                    {
                        "status": 200,
                        "link": image_content_base64_final,
                        "name": image.name,
                    }
                )

            elif PETEREPORT_MARKDOWN["martor_upload_method"] == "MEDIA":
                img_uuid = "{0}-{1}".format(
                    uuid.uuid4().hex[:32], image.name.replace(" ", "-")
                )
                tmp_file = os.path.join(
                    UPLOAD_DIRECTORY,
                    "{}".format(time.strftime("%Y/%m/%d/")),
                    img_uuid,
                )
                def_path = default_storage.save(tmp_file, ContentFile(image.read()))
                # Modified to include server host and port
                img_url_complete = os.path.join(MARTOR_MEDIA_URL, def_path)
                data = json.dumps(
                    {"status": 200, "link": img_url_complete, "name": image.name}
                )

            return HttpResponse(data, content_type="application/json")
        return HttpResponse(_("Invalid request!"))
    return HttpResponse(_("Invalid request!"))


# ----------------------------------------------------------------------
#                           header & footer
# ----------------------------------------------------------------------


def header_footer_data(request):
    application_license = PETEREPORT_CONFIG["application_license"]
    application_name = PETEREPORT_CONFIG["application_name"]
    company_name = DB_Settings.objects.get().company_name
    company_picture = DB_Settings.objects.get().company_picture
    company_website = DB_Settings.objects.get().company_website
    enable_cspn = PETEREPORT_CONFIG["enable_cspn"]
    bookmarks = build_bookmark_list(request)

    return {
        "application_name": application_name,
        "application_license": application_license,
        "company_name": company_name,
        "company_picture": company_picture,
        "company_website": company_website,
        "enable_cspn": enable_cspn,
        "bookmarks": bookmarks,
    }


# ----------------------------------------------------------------------
#                           index
# ----------------------------------------------------------------------


@login_required
def index(request):
    DB_customer_query = DB_Customer.objects.order_by("name")
    DB_product_query = DB_Product.objects.order_by("name")

    report_number = {}
    product_findings = {}
    total_reports = 0
    total_products = DB_product_query.count()
    total_customers = DB_customer_query.count()
    count_product_findings_total = 0
    count_product_findings_critical_high = 0
    count_product_findings_medium = 0

    for p in DB_product_query:
        DB_Report_query = DB_Report.objects.filter(product=p.id)
        count_product_report = DB_Report_query.count()
        report_number[p.id] = count_product_report
        total_reports += count_product_report

        for report in DB_Report_query:
            DB_finding_query = (
                DB_Finding.objects.filter(report=report.id)
                .order_by("cvss_score", "status")
                .reverse()
            )
            count_product_findings = DB_finding_query.count()
            product_findings[report.id] = count_product_findings
            count_product_findings_total += count_product_findings
            for finding in DB_finding_query:
                if finding.severity == "High" or finding.severity == "Critical":
                    count_product_findings_critical_high += 1
                elif finding.severity == "Medium":
                    count_product_findings_medium += 1

    DB_finding_query = DB_Finding.objects.order_by("cvss_score", "status").reverse()

    # CWE - OWASP
    cwe_rows = []
    owasp_rows = []

    for finding in DB_finding_query:
        finding_cwe = f"CWE-{finding.cwe.cwe_id} - {finding.cwe.cwe_name}"
        cwe_rows.append(finding_cwe)

        finding_owasp = (
            f"OWASP-{finding.owasp.owasp_full_id} - {finding.owasp.owasp_name}"
        )
        owasp_rows.append(finding_owasp)

    cwe_cat = Counter(cwe_rows)
    cwe_categories = []

    for key_cwe, value_cwe in cwe_cat.items():
        fixed_key_cwe = "\n".join(
            key_cwe[i : i + 60] for i in range(0, len(key_cwe), 60)
        )
        dict_cwe = {"value": value_cwe, "name": fixed_key_cwe}

        cwe_categories.append(dict_cwe)

    owasp_cat = Counter(owasp_rows)
    owasp_categories = []

    for key_owasp, value_owasp in owasp_cat.items():
        fixed_key_owasp = "\n".join(
            key_owasp[i : i + 60] for i in range(0, len(key_owasp), 60)
        )
        dict_owasp = {"value": value_owasp, "name": fixed_key_owasp}

        owasp_categories.append(dict_owasp)

    # TOP 10 findings
    DB_finding_query = DB_finding_query[:10]

    return render(
        request,
        "home/index.html",
        {
            "total_customers": total_customers,
            "total_products": total_products,
            "total_reports": total_reports,
            "count_product_findings_total": count_product_findings_total,
            "count_product_findings_critical_high": count_product_findings_critical_high,
            "count_product_findings_medium": count_product_findings_medium,
            "DB_finding_query": DB_finding_query,
            "cwe_categories": cwe_categories,
            "owasp_categories": owasp_categories,
        },
    )


# ----------------------------------------------------------------------
#                           Configuration
# ----------------------------------------------------------------------


@login_required
@allowed_users(allowed_roles=["administrator"])
def user_list(request):
    userList = User.objects.values()
    group_list = Group.objects.all()

    return render(
        request,
        "configuration/user_list.html",
        {"userList": userList, "group_list": group_list},
    )


@login_required
@allowed_users(allowed_roles=["administrator"])
def user_add(request):
    if request.method == "POST":
        form = AddUserForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)

            username = form.cleaned_data.get("username")
            raw_password = form.cleaned_data.get("password1")
            user_group = form.cleaned_data.get("group")
            superadmin = form.cleaned_data.get("superadmin")
            user.is_staff = superadmin
            user.is_superuser = superadmin
            user.save()

            user.groups.add(user_group)

            return redirect("user_list")
    else:
        form = AddUserForm()

    return render(request, "configuration/user_add.html", {"form": form})


@login_required
@allowed_users(allowed_roles=["administrator"])
def user_edit(request, pk):
    DB_user_query = get_object_or_404(User, pk=pk)

    if request.method == "POST":
        form = AddUserForm(request.POST, instance=DB_user_query)
        if form.is_valid():
            user = form.save(commit=False)

            username = form.cleaned_data.get("username")
            raw_password = form.cleaned_data.get("password1")
            user_group = form.cleaned_data.get("group")
            superadmin = form.cleaned_data.get("superadmin")
            user.is_staff = superadmin
            user.is_superuser = superadmin
            user.save()

            user.groups.add(user_group)

            return redirect("user_list")
    else:
        form = AddUserForm(instance=DB_user_query)

    return render(request, "configuration/user_add.html", {"form": form})


@login_required
@allowed_users(allowed_roles=["administrator"])
def user_delete(request):
    if request.method == "POST":
        delete_id = request.POST["delete_id"]
        User.objects.filter(pk=delete_id).delete()

        return HttpResponse('{"status":"success"}', content_type="application/json")
    else:
        return HttpResponseServerError(
            '{"status":"fail"}', content_type="application/json"
        )


# ----------------------------------------------------------------------
#                           Settings
# ----------------------------------------------------------------------


@login_required
@allowed_users(allowed_roles=["administrator"])
def settings(request):
    DB_settings_query = DB_Settings.objects.get_or_create()[0]

    if request.method == "POST":
        form = NewSettingsForm(request.POST, request.FILES, instance=DB_settings_query)
        # import ipdb; ipdb.set_trace()
        if form.is_valid():
            prod = form.save(commit=False)
            prod.save()
            return redirect("settings")
    else:
        form = NewSettingsForm(instance=DB_settings_query)

    return render(
        request,
        "settings/settings.html",
        {
            "form": form,
        },
    )


# ----------------------------------------------------------------------
#                           Customers
# ----------------------------------------------------------------------


@login_required
def customer_list(request):
    DB_customer_query = DB_Customer.objects.order_by("name").all()

    ## Apparently useless
    # report_number = {}
    #
    # for customer_in_db in DB_customer_query:
    #     count_product_report = DB_Report.objects.filter(customer=customer_in_db.id).count()
    #     report_number[customer_in_db.id] = count_customer_report

    return render(
        request,
        "customers/customer_list.html",
        {"DB_customer_query": DB_customer_query},
    )


@login_required
@allowed_users(allowed_roles=["administrator"])
def customer_add(request):
    # DB_product_query = DB_product.objects.filter(customer_id = request.POST.)
    if request.method == "POST":
        form = NewCustomerForm(request.POST)

        if form.is_valid():
            prod = form.save(commit=False)
            prod.save()
            form.save_m2m()  # Save tags
            return redirect("customer_list")
    else:
        form = NewCustomerForm()
        form.fields["description"].initial = ""  # PETEREPORT_TEMPLATES['initial_text']
        form.fields["contact_list"].initial = ""

    return render(request, "customers/customer_add.html", {"form": form})


@login_required
@allowed_users(allowed_roles=["administrator"])
def customer_edit(request, pk):
    DB_customer_query = get_object_or_404(DB_Customer, pk=pk)

    if request.method == "POST":
        form = NewCustomerForm(request.POST, instance=DB_customer_query)

        if form.is_valid():
            prod = form.save(commit=False)
            prod.save()
            form.save_m2m()  # Save tags
            return redirect("customer_list")
    else:
        DB_customer_query.contact_list = "\n".join(DB_customer_query.contact_list)
        form = NewCustomerForm(instance=DB_customer_query)

        form.fields["contact_list"].inital = ""

    return render(request, "customers/customer_add.html", {"form": form})


@login_required
@allowed_users(allowed_roles=["administrator"])
def customer_delete(request):
    if request.method == "POST":
        delete_id = request.POST["delete_id"]
        DB_Customer.objects.filter(pk=delete_id).delete()

        return HttpResponse('{"status":"success"}', content_type="application/json")
    else:
        return HttpResponseServerError(
            '{"status":"fail"}', content_type="application/json"
        )


@login_required
def customer_view(request, pk):
    DB_customer_query = get_object_or_404(DB_Customer, pk=pk)
    DB_product_query = DB_Product.objects.filter(customer=DB_customer_query)
    DB_report_query = DB_Report.objects.filter(product__in=DB_product_query)
    bookmark_exists = DB_customer_query.bookmarks.filter(user=request.user).count() == 1
    count_customer_product = DB_product_query.count()
    count_customer_report = DB_report_query.count()
    customer_tags = ", ".join(o.name for o in DB_customer_query.tags.all())
    customer_findings = {}
    count_customer_findings_total = 0
    count_customer_findings_critical_high = 0

    for report in DB_report_query:
        DB_finding_query = DB_Finding.objects.filter(report=report.id)
        count_product_findings = DB_finding_query.count()
        customer_findings[report.id] = count_product_findings
        count_customer_findings_total += count_product_findings

        for finding in DB_finding_query:
            if finding.severity == "High" or finding.severity == "Critical":
                count_customer_findings_critical_high += 1

    return render(
        request,
        "customers/customer_view.html",
        {
            "pk": pk,
            "DB_customer_query": DB_customer_query,
            "DB_product_query": DB_product_query,
            "DB_report_query": DB_report_query,
            "bookmark_exists": bookmark_exists,
            "count_customer_product": count_customer_product,
            "count_customer_report": count_customer_report,
            "customer_findings": customer_findings,
            "count_customer_findings_total": count_customer_findings_total,
            "count_customer_findings_critical_high": count_customer_findings_critical_high,
            "customer_tags": customer_tags,
        },
    )


# ----------------------------------------------------------------------
#                           Products
# ----------------------------------------------------------------------


@login_required
def product_list(request):
    DB_product_query = DB_Product.objects.order_by("name").all()
    report_number = {}

    for product_in_db in DB_product_query:
        count_product_report = DB_Report.objects.filter(
            product=product_in_db.id
        ).count()
        report_number[product_in_db.id] = count_product_report

    return render(
        request,
        "products/product_list.html",
        {
            "DB_product_query": DB_product_query,
            "report_number": report_number,
            "enable_cspn": PETEREPORT_CONFIG["enable_cspn"],
        },
    )


@login_required
@allowed_users(allowed_roles=["administrator"])
def product_add(request):
    if request.method == "POST":
        form = NewProductForm(request.POST)
        if form.is_valid():
            prod = form.save(commit=False)
            prod.save()
            form.save_m2m()  # Save tags
            return redirect("product_list")
    else:
        form = NewProductForm()
        form.fields["description"].initial = ""  # PETEREPORT_TEMPLATES['initial_text']

    return render(request, "products/product_add.html", {"form": form})


@login_required
@allowed_users(allowed_roles=["administrator"])
def product_edit(request, pk):
    DB_product_query = get_object_or_404(DB_Product, pk=pk)

    if request.method == "POST":
        form = NewProductForm(request.POST, instance=DB_product_query)
        if form.is_valid():
            prod = form.save(commit=False)
            prod.save()
            form.save_m2m()  # Save tags
            return redirect("product_list")
    else:
        form = NewProductForm(instance=DB_product_query)

    return render(request, "products/product_add.html", {"form": form})


@login_required
@allowed_users(allowed_roles=["administrator"])
def product_delete(request):
    if request.method == "POST":
        delete_id = request.POST["delete_id"]
        DB_Product.objects.filter(pk=delete_id).delete()

        return HttpResponse('{"status":"success"}', content_type="application/json")
    else:
        return HttpResponseServerError(
            '{"status":"fail"}', content_type="application/json"
        )


@login_required
def product_view(request, pk):
    DB_product_query = get_object_or_404(DB_Product, pk=pk)
    DB_report_query = (
        DB_Report.objects.filter(product=DB_product_query)
        .order_by("creation_date")
        .reverse()
    )
    count_product_report = DB_report_query.count()
    bookmark_exists = DB_product_query.bookmarks.filter(user=request.user).count() == 1
    product_tags = ", ".join(o.name for o in DB_product_query.tags.all())
    product_findings = {}
    count_product_findings_total = 0
    count_product_findings_critical_high = 0
    count_product_findings_medium = 0

    for report in DB_report_query:
        DB_finding_query = DB_Finding.objects.filter(report=report.id)
        count_product_findings = DB_finding_query.count()
        product_findings[report.id] = count_product_findings
        count_product_findings_total += count_product_findings
        for finding in DB_finding_query:
            if finding.severity == "High" or finding.severity == "Critical":
                count_product_findings_critical_high += 1
            elif finding.severity == "Medium":
                count_product_findings_medium += 1

    return render(
        request,
        "products/product_view.html",
        {
            "pk": pk,
            "DB_product_query": DB_product_query,
            "DB_report_query": DB_report_query,
            "bookmark_exists": bookmark_exists,
            "count_product_report": count_product_report,
            "product_findings": count_product_findings_total,
            "count_product_findings_critical_high": count_product_findings_critical_high,
            "count_product_findings_medium": count_product_findings_medium,
            "product_tags": product_tags,
            "enable_cspn": PETEREPORT_CONFIG["enable_cspn"],
        },
    )


# ----------------------------------------------------------------------
#                           Reports
# ----------------------------------------------------------------------


@login_required
def report_list(request):
    DB_report_query = DB_Report.objects.order_by("title").all()

    return render(
        request,
        "reports/report_list.html",
        {
            "DB_report_query": DB_report_query,
            "enable_cspn": PETEREPORT_CONFIG["enable_cspn"],
        },
    )


@login_required
@allowed_users(allowed_roles=["administrator"])
def report_add(request):
    today = datetime.date.today().strftime("%Y-%m-%d")
    report_id_format = str(today) + "_" + uuid.uuid4().hex[:10]
    if request.method == "POST":
        form = NewReportForm(request.POST)
        if form.is_valid():
            report = form.save(commit=False)
            report.save()
            form.save_m2m()  # Save tags
            return redirect("report_view", pk=report.pk)
    else:
        form = NewReportForm()
        form.fields["report_id"].initial = report_id_format
        form.fields[
            "executive_summary"
        ].initial = ""  # PETEREPORT_TEMPLATES['initial_text']
        form.fields[
            "audit_objectives"
        ].initial = ""  # PETEREPORT_TEMPLATES['initial_text']
        form.fields["scope"].initial = ""  # PETEREPORT_TEMPLATES['initial_text']
        form.fields["outofscope"].initial = ""  # PETEREPORT_TEMPLATES['initial_text']
        form.fields["methodology"].initial = ""  # PETEREPORT_TEMPLATES['initial_text']
        form.fields[
            "recommendation"
        ].initial = ""  # PETEREPORT_TEMPLATES['initial_text']
        form.fields["report_date"].initial = today
    return render(request, "reports/report_add.html", {"form": form})


@login_required
@allowed_users(allowed_roles=["administrator"])
def report_delete(request):
    if request.method == "POST":
        delete_id = request.POST["delete_id"]
        DB_Report.objects.filter(pk=delete_id).delete()

        return HttpResponse('{"status":"success"}', content_type="application/json")
    else:
        return HttpResponseServerError(
            '{"status":"fail"}', content_type="application/json"
        )


@login_required
@allowed_users(allowed_roles=["administrator"])
def report_duplicate(request):
    if request.method == "POST":
        duplicate_id = request.POST["duplicate_id"]
        report = DB_Report.objects.get(pk=duplicate_id)
        report.pk = None
        report._state.adding = True
        copy_datetime = "-COPY-" + str(datetime.datetime.now().strftime("%Y%m%d%H%M"))
        report.report_id = report.report_id + copy_datetime

        try:
            report.save()
        except django.db.utils.IntegrityError:
            report.report_id = (
                DB_Report.objects.filter(
                    report_id__contains=report.report_id,
                    report_id__endswith=copy_datetime,
                )
                .latest("creation_date")
                .report_id
            )
            report.report_id = report.report_id + copy_datetime
            report.save()

        # Now, duplicate findings
        DB_finding_query = DB_Finding.objects.filter(report_id=duplicate_id)
        for finding in DB_finding_query:
            finding.pk = None
            finding._state.adding = True
            finding.finding_id = finding.finding_id + copy_datetime
            finding.report_id = report.pk
            try:
                finding.save()
            except django.db.utils.IntegrityError:
                finding.finding_id = (
                    DB_Finding.objects.filter(
                        finding_id__contains=finding.finding_id,
                        finding_id__endswith=copy_datetime,
                    )
                    .latest("creation_date")
                    .finding_id
                )
                finding.finding_id = finding.finding_id + copy_datetime
                finding.save()

        # Now, duplicate CSPN Evaluations
        DB_cspn_query = DB_CSPN_Evaluation.objects.filter(report_id=duplicate_id)
        for cspn_eval in DB_cspn_query:
            cspn_eval.pk = None
            cspn_eval._state.adding = True
            cspn_eval.cspn_id = cspn_eval.cspn_id + copy_datetime
            cspn_eval.report_id = report.pk
            try:
                cspn_eval.save()
            except django.db.utils.IntegrityError:
                cspn_eval.cspn_id = (
                    DB_CSPN_Evaluation.objects.filter(
                        cspn_id__contains=cspn_eval.cspn_id,
                        cspn_id__endswith=copy_datetime,
                    )
                    .latest("creation_date")
                    .cspn_id
                )
                cspn_eval.cspn_id = cspn_eval.cspn_id + copy_datetime
                cspn_eval.save()

        return HttpResponse('{"status":"success"}', content_type="application/json")
    else:
        return HttpResponseServerError(
            '{"status":"fail"}', content_type="application/json"
        )


@login_required
@allowed_users(allowed_roles=["administrator"])
def report_edit(request, pk):
    report = get_object_or_404(DB_Report, pk=pk)

    if request.method == "POST":
        form = NewReportForm(request.POST, instance=report)
        if form.is_valid():
            report = form.save(commit=False)
            report.save()
            form.save_m2m()  # Save tags
            return redirect("report_view", pk=report.pk)
    else:
        form = NewReportForm(instance=report)
    return render(request, "reports/report_add.html", {"form": form})


@login_required
def report_view(request, pk):
    DB_report_query = get_object_or_404(DB_Report, pk=pk)
    DB_finding_query = (
        DB_Finding.objects.filter(report=DB_report_query)
        .order_by("order", "cvss_score", "status")
        .reverse()
    )
    count_finding_query = DB_finding_query.count()
    bookmark_exists = DB_report_query.bookmarks.filter(user=request.user).count() == 1
    report_tags = ", ".join(o.name for o in DB_Report.tags.all())

    DB_appendix_query = DB_Appendix.objects.filter(report=pk)
    count_appendix_query = DB_appendix_query.count()

    DB_attackflow_query = DB_AttackFlow.objects.filter(report=pk)
    count_attackflow_query = DB_attackflow_query.count()

    DB_deliverable_query = DB_Deliverable.objects.filter(report=pk)
    count_deliverable_query = DB_deliverable_query.count()

    count_findings_critical = 0
    count_findings_high = 0
    count_findings_medium = 0
    count_findings_low = 0
    count_findings_info = 0
    count_findings_none = 0

    cwe_rows = []
    owasp_rows = []

    for finding in DB_finding_query:
        # Only reporting Critical/High/Medium/Low/Info findings
        if finding.severity == "None":
            count_findings_none += 1
        else:
            finding_cwe = f"CWE-{finding.cwe.cwe_id} - {finding.cwe.cwe_name}"
            cwe_rows.append(finding_cwe)
            finding_owasp = (
                f"OWASP-{finding.owasp.owasp_full_id} - {finding.owasp.owasp_name}"
            )
            owasp_rows.append(finding_owasp)

            if finding.severity == "Critical":
                count_findings_critical += 1
            elif finding.severity == "High":
                count_findings_high += 1
            elif finding.severity == "Medium":
                count_findings_medium += 1
            elif finding.severity == "Low":
                count_findings_low += 1
            elif finding.severity == "Info":
                count_findings_info += 1

    cwe_cat = Counter(cwe_rows)
    cwe_categories = []

    for key_cwe, value_cwe in cwe_cat.items():
        fixed_key_cwe = "\n".join(
            key_cwe[i : i + 60] for i in range(0, len(key_cwe), 60)
        )
        dict_cwe = {"value": value_cwe, "name": fixed_key_cwe}
        cwe_categories.append(dict_cwe)

    owasp_cat = Counter(owasp_rows)
    owasp_categories = []

    for key_owasp, value_owasp in owasp_cat.items():
        fixed_key_owasp = "\n".join(
            key_owasp[i : i + 60] for i in range(0, len(key_owasp), 60)
        )
        dict_owasp = {"value": value_owasp, "name": fixed_key_owasp}
        owasp_categories.append(dict_owasp)
        
    form = ReportToCloneForm()
    form.fields["report_to_clone"].initial = DB_report_query.pk

    return render(
        request,
        "reports/report_view.html",
        {
            "form": form,
            "DB_appendix_query": DB_appendix_query,
            "DB_report_query": DB_report_query,
            "DB_finding_query": DB_finding_query,
            "bookmark_exists": bookmark_exists,
            "count_appendix_query": count_appendix_query,
            "count_finding_query": count_finding_query,
            "count_findings_critical": count_findings_critical,
            "count_findings_high": count_findings_high,
            "count_findings_medium": count_findings_medium,
            "count_findings_low": count_findings_low,
            "count_findings_info": count_findings_info,
            "count_findings_none": count_findings_none,
            "cwe_categories": cwe_categories,
            "owasp_categories": owasp_categories,
            "DB_attackflow_query": DB_attackflow_query,
            "count_attackflow_query": count_attackflow_query,
            "DB_deliverable_query": DB_deliverable_query,
            "count_deliverable_query": count_deliverable_query,
            "report_tags": report_tags,
            "templates_directories": TEMPLATES_DIRECTORIES,
            "enable_cspn": PETEREPORT_CONFIG["enable_cspn"],
        },
    )


def report_uploadsummaryfindings(request, pk):
    DB_report_query = get_object_or_404(DB_Report, pk=pk)

    if request.method == "POST":
        # Severitybar
        summary_finding_file_base64 = request.POST["fileSeveritybar"]
        formatf, summary_finding_file_str = summary_finding_file_base64.split(
            ";base64,"
        )
        summary_ext = formatf.split("/")[-1]
        dataimgSeveritybar = ContentFile(base64.b64decode(summary_finding_file_str))

        # CWE Categories
        cwe_summary_categories_file_base64 = request.POST["file_cwe"]
        formatf, cwe_summary_categories_finding_file_str = (
            cwe_summary_categories_file_base64.split(";base64,")
        )
        cwe_ext = formatf.split("/")[-1]
        dataCWE = ContentFile(base64.b64decode(cwe_summary_categories_finding_file_str))

        # OWASP Categories
        owasp_summary_categories_file_base64 = request.POST["file_owasp"]
        formatf, owasp_summary_categories_finding_file_str = (
            owasp_summary_categories_file_base64.split(";base64,")
        )
        owasp_ext = formatf.split("/")[-1]
        dataOWASP = ContentFile(
            base64.b64decode(owasp_summary_categories_finding_file_str)
        )

        # Force base64 encoding even for MEDIA otherwise pandoc into Docker cannot retrieve media
        if (
            PETEREPORT_MARKDOWN["martor_upload_method"] == "BASE64"
            or PETEREPORT_MARKDOWN["martor_upload_method"] == "MEDIA"
        ):
            DB_report_query.executive_summary_image = summary_finding_file_base64
            DB_report_query.cwe_categories_summary_image = (
                cwe_summary_categories_file_base64
            )
            DB_report_query.owasp_categories_summary_image = (
                owasp_summary_categories_file_base64
            )
            DB_report_query.save()
        elif PETEREPORT_MARKDOWN["martor_upload_method"] == "OLD_MEDIA":
            # Severity chart
            file_name_severity = (
                DB_report_query.report_id + "_severity_summary_finding." + summary_ext
            )
            img_url_severity = os.path.join(
                "{}".format(time.strftime("%Y/%m/%d/")), file_name_severity
            )
            media_url_severity = os.path.join(MEDIA_ROOT, img_url_severity)

            if os.path.exists(media_url_severity):
                os.remove(media_url_severity)

            fs = FileSystemStorage()
            filename_severity = fs.save(img_url_severity, dataimgSeveritybar)
            uploaded_file_url_severity = fs.url(filename_severity)

            DB_report_query.executive_summary_image = uploaded_file_url_severity

            # CWE
            file_name_categories = (
                DB_report_query.report_id + "_cwe_categories_summary_finding." + cwe_ext
            )
            img_url_categories = os.path.join(
                "{}".format(time.strftime("%Y/%m/%d/")), file_name_categories
            )
            media_url_categories = os.path.join(MEDIA_ROOT, img_url_categories)

            if os.path.exists(media_url_categories):
                os.remove(media_url_categories)

            fs = FileSystemStorage()
            filename_categories = fs.save(img_url_categories, dataCWE)
            uploaded_file_url_categories = fs.url(filename_categories)

            DB_report_query.cwe_categories_summary_image = uploaded_file_url_categories

            # OWASP
            file_name_categories = (
                DB_report_query.report_id
                + "_owasp_categories_summary_finding."
                + owasp_ext
            )
            img_url_categories = os.path.join(
                "{}".format(time.strftime("%Y/%m/%d/")), file_name_categories
            )
            media_url_categories = os.path.join(MEDIA_ROOT, img_url_categories)

            if os.path.exists(media_url_categories):
                os.remove(media_url_categories)

            fs = FileSystemStorage()
            filename_categories = fs.save(img_url_categories, dataOWASP)
            uploaded_file_url_categories = fs.url(filename_categories)

            DB_report_query.owasp_categories_summary_image = (
                uploaded_file_url_categories
            )

            DB_report_query.save()

        # return HttpResponse('{"status":"success"}', content_type="application/json")
    else:
        return HttpResponseServerError(
            '{"status":"fail"}', content_type="application/json"
        )


@login_required
def report_download(request, export_type, cst, pk):
    if request.method == "POST":
        report_uploadsummaryfindings(request, pk)
        # Used only to build URL into template
        if export_type in ["markdown", "pdf"]:
            return report_download_generic(export_type, cst, pk)
    raise Http404


def report_download_generic(export_type, cst, pk):
    export_type_title = str(export_type).upper()
    logger.debug(f"Generating {export_type_title} Report [{str(pk)}]")

    start_report = timer()

    tpl_dir = os.path.join(TEMPLATES_ROOT, "tpl", export_type)
    tpl_cst_dir = os.path.join(tpl_dir, cst)
    tpl_cst_dir_pp = pathlib.PurePath(tpl_cst_dir)
    if tpl_cst_dir_pp.is_relative_to(tpl_dir):
        # DB
        DB_report_query = get_object_or_404(DB_Report, pk=pk)
        DB_finding_query = (
            DB_Finding.objects.filter(report=DB_report_query)
            .order_by("order", "cvss_score", "status")
            .reverse()
        )
        DB_cspn_query = DB_CSPN_Evaluation.objects.filter(
            report=DB_report_query
        ).order_by("stage__cspn_id")

        DB_attackflow_query = DB_AttackFlow.objects.filter(
            report=DB_report_query
        ).order_by("title")

        DB_appendix_query = DB_Appendix.objects.filter(report=DB_report_query).order_by(
            "title"
        )

        DB_settings_query = DB_Settings.objects.get()

        # Datetime
        now = datetime.datetime.now()
        report_date = DB_report_query.report_date.strftime("%Y-%m-%d")

        # Report filename
        name_file = uutils.build_report_file_name(
            PETEREPORT_TEMPLATES[f"report_{export_type}_name"],
            cst,
            DB_report_query.title,
            str(now.strftime("%Y%m%d_%H%M%S")),
            export_type,
        )

        # COLORS
        CRITICAL = "CC0000"
        HIGH = "FF0000"
        WARNING = "FFB000"
        LOW = "05B04F"
        INFO = "002060"

        # INIT
        template_findings = template_appendix = template_attackflows = ""
        markdown_report = render_findings_summary = render_findings = ""
        template_cspn_evaluations = cspn_eval_summary = ""

        md_author = DB_settings_query.company_name
        md_subject = PETEREPORT_MARKDOWN["subject"]
        md_website = DB_settings_query.company_website
        counter_finding = counter_finding_critical = counter_finding_high = (
            counter_finding_medium
        ) = counter_finding_low = counter_finding_info = 0
        counter_cspn_eval = 0
        title_background_image = os.path.join(
            tpl_cst_dir, PETEREPORT_TEMPLATES[f"report_title_background"]
        )
        pages_background_image = os.path.join(
            tpl_cst_dir, PETEREPORT_TEMPLATES[f"report_pages_background"]
        )

        # IMAGES
        # Force base64 encoding even for MEDIA otherwise pandoc into Docker cannot retrieve media
        if (
            PETEREPORT_MARKDOWN["martor_upload_method"] == "BASE64"
            or PETEREPORT_MARKDOWN["martor_upload_method"] == "MEDIA"
        ):
            report_executive_summary_image = DB_report_query.executive_summary_image
            report_cwe_categories_image = DB_report_query.cwe_categories_summary_image
            report_owasp_categories_image = (
                DB_report_query.owasp_categories_summary_image
            )
        elif PETEREPORT_MARKDOWN["martor_upload_method"] == "OLD_MEDIA":
            report_executive_summary_image = os.path.join(
                MARTOR_MEDIA_URL,
                "{}".format(time.strftime("%Y/%m/%d/")),
                DB_report_query.executive_summary_image,
            )
            report_cwe_categories_image = os.path.join(
                MARTOR_MEDIA_URL,
                "{}".format(time.strftime("%Y/%m/%d/")),
                DB_report_query.cwe_categories_summary_image,
            )
            report_owasp_categories_image = os.path.join(
                MARTOR_MEDIA_URL,
                "{}".format(time.strftime("%Y/%m/%d/")),
                DB_report_query.owasp_categories_summary_image,
            )

        logger.debug("Generating Findings")
        for finding in DB_finding_query:
            # Format display_id
            finding.display_id = uutils.format_finding_display_id(finding.display_id)

            # Custom fields
            template_custom_fields = ""

            # Only reporting Critical/High/Medium/Low/Info findings
            if finding.severity == "None":
                pass
            else:
                start_finding = timer()
                counter_finding += 1

                if finding.severity == "Critical":
                    color_cell_bg = CRITICAL
                    color_text_severity = CRITICAL
                    counter_finding_critical += 1
                    icon_finding = "important"
                    severity_color = "criticalcolor"
                    severity_box = "criticalbox"
                elif finding.severity == "High":
                    color_cell_bg = HIGH
                    color_text_severity = HIGH
                    counter_finding_high += 1
                    icon_finding = "highnote"
                    severity_color = "highcolor"
                    severity_box = "highbox"
                elif finding.severity == "Medium":
                    color_cell_bg = WARNING
                    color_text_severity = WARNING
                    counter_finding_medium += 1
                    icon_finding = "mediumnote"
                    severity_color = "mediumcolor"
                    severity_box = "mediumbox"
                elif finding.severity == "Low":
                    color_cell_bg = LOW
                    color_text_severity = LOW
                    counter_finding_low += 1
                    icon_finding = "lownote"
                    severity_color = "lowcolor"
                    severity_box = "lowbox"
                else:
                    color_cell_bg = INFO
                    color_text_severity = INFO
                    counter_finding_info += 1
                    icon_finding = "debugnote"
                    severity_color = "debugcolor"
                    severity_box = "infobox"

                # Summary table
                try:
                    render_template_file = os.path.join(
                        "tpl", export_type, cst, "finding_summary.md"
                    )
                    render_findings_summary += render_to_string(
                        render_template_file,
                        {
                            "finding": finding,
                            "counter_finding": counter_finding,
                            "severity_box": severity_box,
                        },
                    )
                except TemplateDoesNotExist:
                    logger.warning(
                        f"Template {render_template_file} does not exist for {export_type}/{cst}"
                    )

                # Custom fields
                if finding.custom_field_finding.all():
                    for field_in_finding in finding.custom_field_finding.all():
                        md_custom_fields = f"**{bleach.clean(field_in_finding.title)}**\n\n{bleach.clean(field_in_finding.description)}\n\n"

                        template_custom_fields += "".join(md_custom_fields)

                # Finding
                render_template_file = os.path.join(
                    "tpl", export_type, cst, "finding.md"
                )
                try:
                    render_findings = render_to_string(
                        render_template_file,
                        {
                            "finding": finding,
                            "icon_finding": icon_finding,
                            "severity_color": severity_color,
                            "template_custom_fields": template_custom_fields,
                        },
                    )
                    template_findings += "".join(render_findings)
                except TemplateDoesNotExist:
                    logger.warning(
                        f"Template {render_template_file} does not exist for {export_type}/{cst}"
                    )

                end_finding = timer()
                logger.debug(
                    f"Finding: [{finding.finding_id}] {finding.title} ⇨ {str(end_finding - start_finding)} s"
                )

        if str(cst).startswith("cspn"):
            logger.debug("Generating CSPN Evaluations")
            for cspn_eval in DB_cspn_query:
                start_cspn_eval = timer()
                counter_cspn_eval += 1

                if cspn_eval.status == "Evaluated":
                    icon_cspn = "lownote"
                    evaluated_color = "lowcolor"
                    evaluated_box = "lowbox"
                else:
                    icon_cspn = "debugnote"
                    evaluated_color = "debugcolor"
                    evaluated_box = "infobox"

                render_template_file = os.path.join(
                    "tpl", export_type, cst, "cspn_eval_summary.md"
                )
                try:
                    cspn_eval_summary += render_to_string(
                        render_template_file,
                        {"cspn_eval": cspn_eval, "evaluated_box": evaluated_box},
                    )
                except TemplateDoesNotExist:
                    logger.warning(
                        f"Template {render_template_file} does not exist for {export_type}/{cst}"
                    )

                # CSPN evals
                render_template_file = os.path.join(
                    "tpl", export_type, cst, "cspn_evaluation.md"
                )
                try:
                    cspn_evaluations = render_to_string(
                        render_template_file,
                        {
                            "cspn_eval": cspn_eval,
                            "icon_cspn": icon_cspn,
                            "evaluated_color": evaluated_color,
                        },
                    )
                    template_cspn_evaluations += "".join(cspn_evaluations)
                except TemplateDoesNotExist:
                    logger.warning(
                        f"Template {render_template_file} does not exist for {export_type}/{cst}"
                    )

                end_cspn_eval = timer()
                logger.debug(
                    f"CSPN Evaluations: [{cspn_eval.cspn_id}] {cspn_eval.stage.cspn_id} ⇨ {str(end_cspn_eval - start_cspn_eval)} s"
                )

        # Appendix
        counter_appendix = 0
        if DB_appendix_query.all():
            for appendix in DB_appendix_query.all():
                counter_appendix += 1
                render_template_file = os.path.join(
                    "tpl", export_type, cst, "appendix.md"
                )
                try:
                    render_appendix = render_to_string(
                        render_template_file,
                        {"appendix": appendix},
                    )
                    template_appendix += "".join(render_appendix)
                except TemplateDoesNotExist:
                    logger.warning(
                        f"Template {render_template_file} does not exist for {export_type}/{cst}"
                    )

        # AttackFlow
        counter_attackflow = 0
        if DB_attackflow_query.all():
            for attackflow in DB_attackflow_query.all():
                counter_attackflow += 1
                render_template_file = os.path.join(
                    "tpl", export_type, cst, "attackflow.md"
                )
                try:
                    render_attackflow = render_to_string(
                        render_template_file,
                        {
                            "attackflow": attackflow,
                            "findings": attackflow.findings.all(),
                        },
                    )
                    template_attackflows += "".join(render_attackflow + "\n")
                except TemplateDoesNotExist:
                    logger.warning(
                        f"Template {render_template_file} does not exist for {export_type}/{cst}"
                    )

        start_report_yaml = timer()
        render_template_file = os.path.join("tpl", export_type, cst, "header.yaml")
        try:
            markdown_report = render_to_string(
                render_template_file,
                {
                    "DB_report_query": DB_report_query,
                    "md_author": md_author,
                    "report_date": report_date,
                    "md_subject": md_subject,
                    "md_website": md_website,
                    "report_language": PETEREPORT_TEMPLATES["report_language"],
                    "titlepagecolor": PETEREPORT_TEMPLATES["titlepage-color"],
                    "titlepagetextcolor": PETEREPORT_TEMPLATES["titlepage-text-color"],
                    "titlerulecolor": PETEREPORT_TEMPLATES["titlepage-rule-color"],
                    "titlepageruleheight": PETEREPORT_TEMPLATES[
                        "titlepage-rule-height"
                    ],
                    "title_background": title_background_image,
                    "pages_background": pages_background_image,
                },
            )
        except TemplateDoesNotExist:
            logger.warning(
                f"Template {render_template_file} does not exist for {export_type}/{cst}"
            )
        end_report_yaml = timer()
        logger.debug(
            f"Report YAML: [{DB_report_query.report_id}] {DB_report_query.title} ⇨ {str(end_report_yaml - start_report_yaml)} s"
        )

        start_report_markdown = timer()
        render_template_file = os.path.join("tpl", export_type, cst, "report.md")
        try:
            markdown_report += render_to_string(
                render_template_file,
                {
                    "md_author": md_author,
                    "md_address": DB_Settings.objects.get().company_address,
                    "DB_report_query": DB_report_query,
                    "report_executive_summary_image": report_executive_summary_image,
                    "report_cwe_categories_image": report_cwe_categories_image,
                    "report_owasp_categories_image": report_owasp_categories_image,
                    "finding_summary": render_findings_summary,
                    "cspn_eval_summary": cspn_eval_summary,
                    "template_findings": template_findings,
                    "template_appendix": template_appendix,
                    "template_attackflows": template_attackflows,
                    "counter_appendix": counter_appendix,
                    "counter_finding": counter_finding,
                    "counter_attackflow": counter_attackflow,
                    "template_cspn_evaluations": template_cspn_evaluations,
                },
            )
        except TemplateDoesNotExist:
            logger.warning(
                f"Template {render_template_file} does not exist for {export_type}/{cst}"
            )

        final_markdown = textwrap.dedent(markdown_report)
        final_markdown_output = mark_safe(final_markdown)
        end_report_markdow = timer()
        logger.debug(
            f"Report Markdown: [{DB_report_query.report_id}] {DB_report_query.title} ⇨ {str(end_report_markdow - start_report_markdown)} s"
        )

        # Replace media with local data
        if PETEREPORT_MARKDOWN["martor_upload_method"] == "MEDIA":
            start_report_media = timer()
            final_markdown_output = uurls.replace_media_url(final_markdown_output)
            end_report_media = timer()
            logger.debug(
                f"Report Include Media: [{DB_report_query.report_id}] {DB_report_query.title} ⇨ {str(end_report_media - start_report_media)} s"
            )

        file_output = os.path.join(REPORTS_MEDIA_ROOT, export_type, name_file)
        start_report_latex = timer()
        try:
            if export_type == "pdf":
                content_type = "application/pdf"
                header_file = os.path.join(tpl_dir, cst, "header.tex")
                petereport_latex_tpl = os.path.join(tpl_dir, cst, "petereport.latex")

                # Remove Unicode characters, not parsed by pdflatex
                final_markdown_output = final_markdown_output.encode(
                    encoding="utf-8", errors="ignore"
                ).decode()

                pandoc_extra_args = [
                    "-F",
                    "pandoc-crossref",
                    "-H",
                    header_file,
                    "--from",
                    "markdown+yaml_metadata_block+raw_html",
                    "--template",
                    petereport_latex_tpl,
                    "--table-of-contents",
                    "--toc-depth",
                    "4",
                    "--number-sections",
                    "--highlight-style",
                    "breezedark",
                    "--filter",
                    "pandoc-latex-environment",
                    "--pdf-engine",
                    PETEREPORT_MARKDOWN["pdf_engine"],
                    "--listings",
                ]
                pypandoc.convert_text(
                    final_markdown_output,
                    to=export_type,
                    outputfile=file_output,
                    format="md",
                    extra_args=pandoc_extra_args,
                )

            elif export_type == "markdown":
                content_type = "text/markdown"
                final_markdown_output = mark_safe(
                    textwrap.dedent(final_markdown_output)
                )

                # Replace media with local data
                if PETEREPORT_MARKDOWN["martor_upload_method"] == "MEDIA":
                    final_markdown_output = uurls.replace_media_url(
                        final_markdown_output
                    )

                file_output = os.path.join(REPORTS_MEDIA_ROOT, export_type, name_file)
                with open(file_output, "w") as fh:
                    fh.write(final_markdown_output)

            deliverable = DB_Deliverable(
                report=DB_report_query,
                filename=name_file,
                generation_date=now.date(),
                filetemplate=cst,
                filetype=export_type,
            )
            deliverable.save()

            end_report_latex = timer()
            logger.debug(
                f"Report LateX: [{DB_report_query.report_id}] {DB_report_query.title} ⇨ {str(end_report_latex - start_report_latex)} s"
            )

            end_report = timer()
            logger.debug(
                f"Report: [{DB_report_query.report_id}] {DB_report_query.title} ⇨ {str(end_report - start_report)} s"
            )

            if os.path.exists(file_output):
                with open(file_output, "rb") as fh:
                    response = HttpResponse(fh.read(), content_type=content_type)
                    response["Content-Disposition"] = (
                        "attachment; filename=" + os.path.basename(name_file)
                    )
                    return response

        except Exception as ex:
            if DEBUG_PANDOC_ON_ERROR:
                try:
                    name_file += ".PANDOC_DEBUG.md"

                    pandoc_cmd = f"pandoc --to={export_type} -o pandoc_debug.{export_type} --from=md {' '.join(pandoc_extra_args)} {name_file}"
                    pandoc_cmd = pandoc_cmd.replace(str(BASE_DIR) + "/", "")
                    pandoc_output_file = os.path.join(
                        REPORTS_MEDIA_ROOT, "pandoc", name_file
                    )
                    deliverable = DB_Deliverable(
                        report=DB_report_query,
                        filename=name_file,
                        generation_date=now.date(),
                        filetemplate=cst,
                        filetype="pandoc",
                    )
                    deliverable.save()

                    with open(pandoc_output_file, "w") as pf:
                        pf.write(final_markdown_output)

                    pandoc_debug_error_message = (
                        "<br><hr><br>You can test the markdown file generated with this pandoc command:"
                        + "<br><br><i>"
                        + pandoc_cmd
                        + "</i>"
                        + "<br><br>The markdown file is available into the Deliverable section ; please delete it after your debug session!"
                    )
                except Exception as exi:
                    pandoc_debug_error_message = (
                        "Cannot retrieve all data of Pandoc conversion<br>"
                        + str(exi).replace("\n", "<br>")
                    )
                    logger.error(pandoc_debug_error_message)
                    logger.error(exi, exc_info=True)
            else:
                pandoc_debug_error_message = ""
            end_report = timer()
            error_msg = (
                "Error into Report generation: ["
                + DB_report_query.report_id
                + "] "
                + DB_report_query.title
                + " ⇨ "
                + str(end_report - start_report)
                + " s"
            )
            logger.error(error_msg)
            logger.error(ex, exc_info=True)

            return HttpResponseServerError(
                "<h2>🤬🤬🤬🤬&nbsp;<b>Hacker, your markdown is so bad that the Pandoc LaTeX conversion is broken!</b>&nbsp;🤬🤬🤬🤬<br></h2>"
                + "<hr><h2><br>"
                + error_msg.strip()
                + "</h2><br><br>"
                + str(ex).strip().replace("\n", "<br>")
                + pandoc_debug_error_message
            )
    raise Http404


# ----------------------------------------------------------------------
#                           Deliverables
# ----------------------------------------------------------------------


@login_required
def deliverable_list(request):
    DB_deliverable_query = DB_Deliverable.objects.order_by("filename").all()
    return render(
        request,
        "deliverable/deliverable_list.html",
        {"DB_deliverable_query": DB_deliverable_query},
    )


@login_required
def deliverable_download(request, pk):
    deliverable = get_object_or_404(DB_Deliverable, pk=pk)
    file_path = os.path.join(
        REPORTS_MEDIA_ROOT, deliverable.filetype, deliverable.filename
    )

    if os.path.exists(file_path):
        with open(file_path, "rb") as fh:
            if deliverable.filetype == "jupyter":
                content_type = "application/x-ipynb+json"
            elif deliverable.filetype == "pdf":
                content_type = "application/pdf"
            elif deliverable.filetype == "html":
                content_type = "text/html; charset=utf-8"
            elif deliverable.filetype == "markdown":
                content_type = "text/markdown"
            else:
                content_type = "application/octet-stream"
            response = HttpResponse(fh.read(), content_type=content_type)
            response["Content-Disposition"] = (
                "attachment; filename=" + os.path.basename(file_path)
            )
            return response

    raise Http404


@login_required
@allowed_users(allowed_roles=["administrator"])
def deliverable_report_add(request, pk):
    report = get_object_or_404(DB_Report, pk=pk)

    if request.method == "POST":
        form = CustomDeliverableReportForm(request.POST, request.FILES)
        if form.is_valid():
            cst = "custom"
            now = datetime.datetime.now()
            files = request.FILES.getlist("custom_deliverables")
            for f in files:
                file_path = pathlib.PurePath(f.name)
                name_file = uutils.build_report_file_name(
                    PETEREPORT_TEMPLATES["report_custom_name"],
                    report.title,
                    file_path.stem,
                    str(now.strftime("%Y%m%d_%H%M%S")),
                    file_path.suffix.split(".")[-1],
                )
                file_path = pathlib.PurePath(REPORTS_MEDIA_ROOT, "custom", name_file)
                if os.path.exists(file_path):
                    os.remove(file_path)
                with open(file_path, "wb+") as destination:
                    for chunk in f.chunks():
                        destination.write(chunk)
                    deliverable = DB_Deliverable(
                        report=report,
                        filename=file_path.name,
                        generation_date=now.date(),
                        filetemplate=file_path.suffix.replace(".", "").lower(),
                        filetype=cst,
                    )
                    deliverable.save()
            return HttpResponse('{"status":"success"}', content_type="application/json")

    return HttpResponseServerError('{"status":"fail"}', content_type="application/json")


@login_required
@allowed_users(allowed_roles=["administrator"])
def deliverable_delete(request):
    if request.method == "POST":
        delete_id = request.POST["delete_id"]
        deliverable = get_object_or_404(DB_Deliverable, pk=delete_id)
        file_path = os.path.join(
            REPORTS_MEDIA_ROOT, deliverable.filetype, deliverable.filename
        )
        if os.path.exists(file_path):
            os.remove(file_path)
        DB_Deliverable.objects.filter(pk=delete_id).delete()

        return HttpResponse('{"status":"success"}', content_type="application/json")
    else:
        return HttpResponseServerError(
            '{"status":"fail"}', content_type="application/json"
        )


# ----------------------------------------------------------------------
#                           CSPN Evaluations
# ----------------------------------------------------------------------


@login_required
def report_cspn_evaluations(request, pk):
    DB_report_query = get_object_or_404(DB_Report, pk=pk)
    DB_cspn_query = DB_CSPN_Evaluation.objects.filter(report=DB_report_query).order_by(
        "stage__cspn_id"
    )
    count_cspn_query = DB_cspn_query.count()
    
    form = ReportToCloneForm()
    form.fields["report_to_clone"].initial = DB_report_query.pk

    return render(
        request,
        "cspn/report_cspn.html",
        {
            "form": form,
            "DB_report_query": DB_report_query,
            "DB_cspn_query": DB_cspn_query,
            "count_cspn_query": count_cspn_query,
        },
    )


@login_required
@allowed_users(allowed_roles=["administrator"])
def cspn_add(request, pk):
    DB_report_query = get_object_or_404(DB_Report, pk=pk)

    if request.method == "POST":
        form = NewCSPNEvaluationForm(request.POST)

        if form.is_valid():
            cspn = form.save(commit=False)
            cspn.report = DB_report_query
            cspn.cspn_id = uuid.uuid4()
            cspn.save()
            form.save_m2m()  # Save tags
            if "_next" in request.POST:
                return redirect("cspn_add", pk=pk)
            else:
                return redirect("report_cspn_evaluations", pk=pk)

    else:
        form = NewCSPNEvaluationForm()
        form.fields["evaluation"].initial = ""
        form.fields["expert_notice"].initial = ""
        form.fields["stage"].initial = "-1"

    return render(
        request, "cspn/cspn_add.html", {"form": form, "DB_report": DB_report_query}
    )


@login_required
@allowed_users(allowed_roles=["administrator"])
def cspn_delete(request):
    if request.method == "POST":
        delete_id = request.POST["delete_id"]
        DB_CSPN_Evaluation.objects.filter(pk=delete_id).delete()

        return HttpResponse('{"status":"success"}', content_type="application/json")
    else:
        return HttpResponseServerError(
            '{"status":"fail"}', content_type="application/json"
        )


@login_required
@allowed_users(allowed_roles=["administrator"])
def cspn_duplicate(request):
    if request.method == "POST":
        report_to_clone = request.POST["report_to_clone"]
        report = get_object_or_404(DB_Report, pk=report_to_clone)
        duplicate_id = request.POST["duplicate_id"]
        cspn = DB_CSPN_Evaluation.objects.get(pk=duplicate_id)
        cspn.report = report
        cspn.pk = None
        cspn._state.adding = True
        copy_datetime = "-COPY-" + str(datetime.datetime.now().strftime("%Y%m%d%H%M"))
        cspn.cspn_id = cspn.cspn_id + copy_datetime

        try:
            cspn.save()
        except django.db.utils.IntegrityError:
            cspn.cspn_id = (
                DB_CSPN_Evaluation.objects.filter(
                    cspn_id__contains=cspn.cspn_id, cspn_id__endswith=copy_datetime
                )
                .latest("creation_date")
                .cspn_id
            )
            cspn.cspn_id = cspn.icspn_idd + copy_datetime
            cspn.save()

        return HttpResponse('{"status":"success"}', content_type="application/json")
    else:
        return HttpResponseServerError(
            '{"status":"fail"}', content_type="application/json"
        )


@login_required
def cspn_view(request, pk):
    cspn = get_object_or_404(DB_CSPN_Evaluation, pk=pk)
    DB_cspn_query = DB_CSPN_Evaluation.objects.filter(pk=pk).order_by("stage__cspn_id")
    bookmark_exists = DB_cspn_query.bookmarks.filter(user=request.user).count() == 1
    cspn_tags = ", ".join(o.name for o in cspn.tags.all())

    return render(
        request,
        "cspn/cspn_view.html",
        {
            "DB_report": cspn.report,
            "cspn": cspn,
            "bookmark_exists": bookmark_exists,
            "cspn_tags": cspn_tags,
        },
    )


@login_required
def cspn_list(request):
    DB_cspn_query = DB_CSPN_Evaluation.objects.order_by("stage__cspn_id")
    count_cspn_query = DB_cspn_query.count()
    
    form = ReportToCloneForm()
    form.fields["report_to_clone"].initial = DB_cspn_query.report.pk

    return render(
        request,
        "cspn/cspn_list.html",
        {
            "form": form,
            "Status": "",
            "Link": "list",
            "DB_cspn_query": DB_cspn_query,
            "count_cspn_query": count_cspn_query,
        },
    )


@login_required
@allowed_users(allowed_roles=["administrator"])
def cspn_edit(request, pk):
    cspn = get_object_or_404(DB_CSPN_Evaluation, pk=pk)
    report = cspn.report
    DB_report_query = get_object_or_404(DB_Report, pk=report.pk)

    if request.method == "POST":
        form = NewCSPNEvaluationForm(request.POST, instance=cspn)
        if form.is_valid():
            cspn = form.save(commit=False)
            cspn.save()
            form.save_m2m()  # Save tags

            if "_next" in request.POST:
                return redirect("cspn_add", pk=report.pk)
            else:
                return redirect("report_cspn_evaluations", pk=report.pk)

    else:
        form = NewCSPNEvaluationForm(instance=cspn)
    return render(
        request, "cspn/cspn_add.html", {"form": form, "DB_report": DB_report_query}
    )


# ----------------------------------------------------------------------
#                           Findings
# ----------------------------------------------------------------------


@login_required
def report_findings(request, pk):
    DB_report_query = get_object_or_404(DB_Report, pk=pk)
    DB_finding_query = (
        DB_Finding.objects.filter(report=DB_report_query)
        .order_by("order", "cvss_score", "status")
        .reverse()
    )
    count_finding_query = DB_finding_query.count()

    form = ReportToCloneForm()
    form.fields["report_to_clone"].initial = DB_report_query.pk

    return render(
        request,
        "findings/report_findings.html",
        {
            "form": form,
            "DB_report_query": DB_report_query,
            "DB_finding_query": DB_finding_query,
            "count_finding_query": count_finding_query,
        },
    )


@login_required
def finding_list(request):
    DB_finding_query = DB_Finding.objects.order_by("cvss_score", "status").reverse()
    count_finding_query = DB_finding_query.count()
    form = ReportToCloneForm()

    return render(
        request,
        "findings/findings_list.html",
        {
            "form": form,
            "Status": "",
            "Link": "list",
            "DB_finding_query": DB_finding_query,
            "count_finding_query": count_finding_query,
        },
    )


@login_required
def findings_opened(request):
    DB_finding_query = (
        DB_Finding.objects.filter(status="Opened")
        .order_by("cvss_score", "status")
        .reverse()
    )
    count_finding_query = DB_finding_query.count()

    return render(
        request,
        "findings/findings_list.html",
        {
            "Status": "Opened",
            "Link": "opened",
            "DB_finding_query": DB_finding_query,
            "count_finding_query": count_finding_query,
        },
    )


@login_required
def findings_closed(request):
    DB_finding_query = (
        DB_Finding.objects.filter(status="Closed")
        .order_by("cvss_score", "status")
        .reverse()
    )
    count_finding_query = DB_finding_query.count()

    return render(
        request,
        "findings/findings_list.html",
        {
            "Status": "Closed",
            "Link": "closed",
            "DB_finding_query": DB_finding_query,
            "count_finding_query": count_finding_query,
        },
    )


@login_required
@allowed_users(allowed_roles=["administrator"])
def finding_add(request, pk):
    DB_report_query = get_object_or_404(DB_Report, pk=pk)

    if request.method == "POST":
        form = NewFindingForm(request.POST)

        if form.is_valid():
            finding = form.save(commit=False)
            finding.report = DB_report_query
            finding.finding_id = uuid.uuid4()
            finding.save()
            form.save_m2m()  # Save tags

            if "_next" in request.POST:
                return redirect("finding_add", pk=pk)
            else:
                return redirect("report_findings", pk=pk)

    else:
        form = NewFindingForm()
        form.fields["description"].initial = ""  # PETEREPORT_TEMPLATES['initial_text']
        form.fields["location"].initial = ""  # PETEREPORT_TEMPLATES['initial_text']
        form.fields["impact"].initial = ""  # PETEREPORT_TEMPLATES['initial_text']
        form.fields[
            "recommendation"
        ].initial = ""  # PETEREPORT_TEMPLATES['initial_text']
        form.fields["ref"].initial = ""  # PETEREPORT_TEMPLATES['initial_text']
        form.fields["cwe"].initial = "-1"
        form.fields["owasp"].initial = "-1"

    cvss_version = DB_report_query.cvss_version
    return render(
        request,
        "findings/finding_add_" + cvss_version + ".html",
        {
            "form": form,
            "DB_report": DB_report_query,
        },
    )


@login_required
@allowed_users(allowed_roles=["administrator"])
def finding_edit(request, pk):
    finding = get_object_or_404(DB_Finding, pk=pk)
    report = finding.report
    DB_report_query = get_object_or_404(DB_Report, pk=report.pk)

    if request.method == "POST":
        form = NewFindingForm(request.POST, instance=finding)
        if form.is_valid():
            finding = form.save(commit=False)
            finding.save()
            form.save_m2m()  # Save tags

            if "_next" in request.POST:
                return redirect("finding_add", pk=report.pk)
            else:
                return redirect("report_findings", pk=report.pk)

    else:
        form = NewFindingForm(instance=finding)
    cvss_version = finding.report.cvss_version
    return render(
        request,
        "findings/finding_add_" + cvss_version + ".html",
        {"form": form, "DB_report": DB_report_query},
    )


@login_required
@allowed_users(allowed_roles=["administrator"])
def finding_delete(request):
    if request.method == "POST":
        delete_id = request.POST["delete_id"]
        DB_Finding.objects.filter(pk=delete_id).delete()

        return HttpResponse('{"status":"success"}', content_type="application/json")
    else:
        return HttpResponseServerError(
            '{"status":"fail"}', content_type="application/json"
        )


@login_required
@allowed_users(allowed_roles=["administrator"])
def finding_duplicate(request):
    if request.method == "POST":
        report_to_clone = request.POST["report_to_clone"]
        report = get_object_or_404(DB_Report, pk=report_to_clone)
        duplicate_id = request.POST["duplicate_id"]
        finding = DB_Finding.objects.get(pk=duplicate_id)
        finding.report = report
        finding.pk = None
        finding._state.adding = True
        copy_datetime = "-COPY-" + str(datetime.datetime.now().strftime("%Y%m%d%H%M"))
        finding.finding_id = finding.finding_id + copy_datetime

        try:
            finding.save()
        except django.db.utils.IntegrityError:
            finding.finding_id = (
                DB_Finding.objects.filter(
                    finding_id__contains=finding.finding_id,
                    finding_id__endswith=copy_datetime,
                )
                .latest("creation_date")
                .finding_id
            )
            finding.finding_id = finding.finding_id + copy_datetime
            finding.save()

        return HttpResponse('{"status":"success"}', content_type="application/json")
    else:
        return HttpResponseServerError(
            '{"status":"fail"}', content_type="application/json"
        )


@login_required
@allowed_users(allowed_roles=["administrator"])
def template_duplicate(request):
    if request.method == "POST":
        duplicate_id = request.POST["duplicate_id"]
        finding = DB_Finding_Template.objects.get(pk=duplicate_id)
        finding.pk = None
        finding._state.adding = True
        copy_datetime = "-COPY-" + str(datetime.datetime.now().strftime("%Y%m%d%H%M"))
        finding.finding_id = finding.finding_id + copy_datetime

        try:
            finding.save()
        except django.db.utils.IntegrityError:
            finding.finding_id = (
                DB_Finding_Template.objects.filter(
                    finding_id__contains=finding.finding_id,
                    finding_id__endswith=copy_datetime,
                )
                .latest("creation_date")
                .finding_id
            )
            finding.finding_id = finding.finding_id + copy_datetime
            finding.save()

        return HttpResponse('{"status":"success"}', content_type="application/json")
    else:
        return HttpResponseServerError(
            '{"status":"fail"}', content_type="application/json"
        )


@login_required
def finding_view(request, pk):
    finding = get_object_or_404(DB_Finding, pk=pk)
    DB_finding_query = (
        DB_Finding.objects.filter(pk=pk).order_by("cvss_score", "status").reverse()
    )
    bookmark_exists = finding.bookmarks.filter(user=request.user).count() == 1
    finding_tags = ", ".join(o.name for o in finding.tags.all())
    DB_appendix = DB_Appendix.objects.filter(findings__in=DB_finding_query)
    DB_attackflow = DB_AttackFlow.objects.filter(findings__in=DB_finding_query)
    DB_field = DB_Custom_field.objects.filter(finding__in=DB_finding_query)

    return render(
        request,
        "findings/finding_view.html",
        {
            "DB_report": finding.report,
            "finding": finding,
            "finding_display_id": uutils.format_finding_display_id(finding.display_id),
            "DB_appendix": DB_appendix,
            "DB_attackflow": DB_attackflow,
            "DB_field": DB_field,
            "finding_tags": finding_tags,
            "bookmark_exists": bookmark_exists,
        },
    )


@login_required
def findings_download_csv(request, pk):
    DB_report_query = get_object_or_404(DB_Report, pk=pk)
    DB_finding_query = DB_Finding.objects.filter(report=DB_report_query)

    now = datetime.datetime.now()

    name_file = uutils.build_report_file_name(
        PETEREPORT_TEMPLATES["report_csv_name"],
        "default",
        DB_report_query.title,
        str(now.strftime("%Y%m%d_%H%M%S")),
        "csv",
    )

    # Create the HttpResponse object with the appropriate CSV header.
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="' + name_file + '"'

    csv.register_dialect("MMDialect", quoting=csv.QUOTE_ALL, skipinitialspace=True)
    writer = csv.writer(response, dialect="MMDialect")
    writer.writerow(
        [
            "ID",
            "Status",
            "Title",
            "Severity",
            "CVSS Base Score",
            "CVSS Score",
            "CWE",
            "CWE ID",
            "OWASP",
            "OWASP ID",
            "Description",
            "POC",
            "Location",
            "Impact",
            "Recommendation",
            "References",
            "Appendix",
            "Appendix Description",
        ]
    )
    for finding in DB_finding_query:
        cwe_title = f"CWE-{finding.cwe.cwe_id} - {finding.cwe.cwe_name}"
        cwe_id = finding.cwe.cwe_id
        owasp_title = (
            f"OWASP-{finding.owasp.owasp_full_id} - {finding.owasp.owasp_name}"
        )
        owasp_id = finding.owasp.owasp_full_id

        if finding.appendix_findings.exists():
            for appendix in finding.appendix_findings.all():
                appendix_title = appendix.title
                appendix_description = appendix.description
        else:
            appendix_title = ""
            appendix_description = ""

        # Remove non ascii/unicode characters
        finding_display_id_encoded = finding.display_id.encode(
            "ascii", "ignore"
        ).decode()
        finding_title_encoded = finding.title.encode("ascii", "ignore").decode()
        finding_description_encoded = finding.description.encode(
            "ascii", "ignore"
        ).decode()
        finding_poc_encoded = finding.poc.encode("ascii", "ignore").decode()
        finding_location_encoded = finding.location.encode("ascii", "ignore").decode()
        finding_impact_encoded = finding.impact.encode("ascii", "ignore").decode()
        finding_recommendation_encoded = finding.recommendation.encode(
            "ascii", "ignore"
        ).decode()
        finding_references_encoded = finding.ref.encode("ascii", "ignore").decode()
        appendix_title_encoded = appendix_title.encode("ascii", "ignore").decode()
        appendix_description_encoded = appendix_description.encode(
            "ascii", "ignore"
        ).decode()

        writer.writerow(
            [
                finding.finding_id,
                finding_display_id_encoded,
                finding.status,
                finding_title_encoded,
                finding.severity,
                finding.cvss_base_score,
                finding.cvss_score,
                cwe_title,
                cwe_id,
                owasp_title,
                owasp_id,
                finding_description_encoded,
                finding_poc_encoded,
                finding_location_encoded,
                finding_impact_encoded,
                finding_recommendation_encoded,
                finding_references_encoded,
                appendix_title_encoded,
                appendix_description_encoded,
            ]
        )

    return response


@login_required
@allowed_users(allowed_roles=["administrator"])
def finding_order(request, pk):
    if request.method == "POST":
        try:
            finding = DB_Finding.objects.get(pk=pk)
            finding.order = int(
                re.sub(clean_html_tag_regexp, "", request.body.decode("utf-8"))
            )
            finding.save(update_fields=["order"])
            return HttpResponse(
                '{"order":' + str(finding.order) + "}", content_type="application/json"
            )
        except DB_Report.DoesNotExist:
            return HttpResponseServerError(
                '{"status":"finding does not exist"}', content_type="application/json"
            )
        except ValueError:
            return HttpResponseServerError(
                '{"status":"order is not an integer"}', content_type="application/json"
            )
        except TypeError:
            return HttpResponseServerError(
                '{"status":"order is not an integer"}', content_type="application/json"
            )
    else:
        return HttpResponseServerError(
            '{"status":"bad http method"}', content_type="application/json"
        )


@login_required
@allowed_users(allowed_roles=["administrator"])
def findings_upload_csv(request, pk):
    DB_report_query = get_object_or_404(DB_Report, pk=pk)

    if request.method == "POST":
        csv_file = request.FILES["file"].file

        csv_file_string = io.TextIOWrapper(csv_file, encoding="UTF-8")
        # csv_file_string = io.TextIOWrapper(csv_file, encoding='ISO-8859-1')

        csvReader = csv.reader(csv_file_string, dialect="excel")

        csv.field_size_limit(100000000)

        header = next(csvReader)
        f_id = header.index("ID")
        f_display_id = header.index("Display_ID")
        f_status = header.index("Status")
        f_title = header.index("Title")
        f_severity = header.index("Severity")
        f_cvss_score = header.index("CVSS Base Score")
        f_cvss = header.index("CVSS Score")
        f_cwe = header.index("CWE ID")
        f_owasp = header.index("OWASP ID")
        f_description = header.index("Description")
        f_location = header.index("Location")
        f_impact = header.index("Impact")
        f_recommendation = header.index("Recommendation")
        f_ref = header.index("References")
        f_appendix = header.index("Appendix")
        f_appendix_description = header.index("Appendix Description")

        List = []

        for row in csvReader:
            fid = row[f_id]
            fdisplayid = row[f_display_id]
            ftitle = row[f_title]
            fstatus = row[f_status]
            fseverity = row[f_severity]
            fcvss_score = row[f_cvss_score]
            fcvss = row[f_cvss]
            fcwe = row[f_cwe]
            fowasp = row[f_owasp]
            fdescription = row[f_description]
            flocation = row[f_location]
            fimpact = row[f_impact]
            frecommendation = row[f_recommendation]
            fref = row[f_ref]
            fappendix = row[f_appendix]
            fappendixdescription = row[f_appendix_description]

            List.append(
                [
                    fid,
                    fdisplayid,
                    ftitle,
                    fstatus,
                    fseverity,
                    fcvss_score,
                    fcvss,
                    fcwe,
                    fowasp,
                    fdescription,
                    flocation,
                    fimpact,
                    frecommendation,
                    fref,
                    fappendix,
                    fappendixdescription,
                ]
            )

            DB_cwe = get_object_or_404(DB_CWE, cwe_id=fcwe)
            DB_owasp = get_object_or_404(DB_OWASP, owasp_id=fowasp)

            # Save finding
            finding_to_DB = DB_Finding(
                report=DB_report_query,
                finding_id=fid,
                display_id=fdisplayid,
                title=ftitle,
                status=fstatus,
                severity=fseverity,
                cvss_base_score=fcvss_score,
                cvss_score=fcvss,
                description=fdescription,
                location=flocation,
                impact=fimpact,
                recommendation=frecommendation,
                ref=fref,
                cwe=DB_cwe,
                owasp=DB_owasp,
            )
            finding_to_DB.save()

            # Save appendix
            if fappendix:
                appendix_to_DB = DB_Appendix(
                    title=fappendix, description=fappendixdescription
                )
                appendix_to_DB.save()
                appendix_to_DB.finding.add(finding_to_DB)

        return redirect("report_view", pk=pk)

    return render(
        request, "findings/uploadfindings.html", {"DB_report_query": DB_report_query}
    )


@login_required
@allowed_users(allowed_roles=["administrator"])
def defectdojo_products(request, pk):
    DB_report_query = get_object_or_404(DB_Report, pk=pk)
    DefectDojoURL = DEFECTDOJO_CONFIG["DefectDojoURL"]
    DefectDojoURLProducts = f"{DefectDojoURL}/api/v2/products/"
    DefectDojoApiKey = DEFECTDOJO_CONFIG["apiKey"]

    headersapi = {"Authorization": DefectDojoApiKey}
    params = {"limit": 10000}

    try:
        r = requests.get(
            DefectDojoURLProducts, params=params, headers=headersapi, verify=False
        )
    except requests.exceptions.HTTPError:
        return HttpResponseNotFound(
            f"Not found. Response error from DefectDojo {DefectDojoURL}"
        )

    if not (r.status_code == 200 or r.status_code == 201):
        return HttpResponseNotFound(
            f"No data found. Response error from DefectDojo {DefectDojoURL}"
        )

    jsondata = json.loads(r.text)

    DDproducts_count = jsondata["count"]
    DDproducts = jsondata["results"]

    return render(
        request,
        "defectdojo/defectdojo_products.html",
        {
            "DB_report_query": DB_report_query,
            "DDproducts_count": DDproducts_count,
            "DDproducts": DDproducts,
            "DefectDojoURL": DefectDojoURL,
        },
    )


@login_required
@allowed_users(allowed_roles=["administrator"])
def defectdojo_viewfindings(request, pk, ddpk):
    DB_report_query = get_object_or_404(DB_Report, pk=pk)
    DefectDojoURL = DEFECTDOJO_CONFIG["DefectDojoURL"]
    DefectDojoURLProducts = f"{DefectDojoURL}/api/v2/products/{ddpk}"
    DefectDojoApiKey = DEFECTDOJO_CONFIG["apiKey"]

    headersapi = {"Authorization": DefectDojoApiKey}

    try:
        r = requests.get(DefectDojoURLProducts, headers=headersapi, verify=False)
    except requests.exceptions.HTTPError:
        return HttpResponseNotFound(
            f"Not found. Response error from DefectDojo {DefectDojoURL}"
        )

    if not (r.status_code == 200 or r.status_code == 201):
        return HttpResponseNotFound(
            f"No data found. Response error from DefectDojo {DefectDojoURL}"
        )

    jsondata = json.loads(r.text)
    DDproduct_findings_count = jsondata["findings_count"]
    DDproduct_name = jsondata["name"]
    DDproduct_findings_ids = jsondata["findings_list"]

    DDproduct_findings = {}

    for finding in DDproduct_findings_ids:
        DefectDojoURLFindings = f"{DefectDojoURL}/api/v2/findings/{finding}"
        r = requests.get(DefectDojoURLFindings, headers=headersapi, verify=False)

        jsondata = json.loads(r.text)

        DDproduct_findings[finding] = {}

        DDproduct_findings[finding]["id"] = jsondata["id"]
        DDproduct_findings[finding]["title"] = jsondata["title"] or ""
        DDproduct_findings[finding]["cvssv3"] = jsondata["cvssv3"] or ""
        DDproduct_findings[finding]["cvssv3_score"] = jsondata["cvssv3_score"] or 0
        DDproduct_findings[finding]["cwe"] = jsondata["cwe"] or 0
        DDproduct_findings[finding]["severity"] = (
            (jsondata["severity"]).capitalize() or ""
        )

    return render(
        request,
        "defectdojo/defectdojo_findings_products.html",
        {
            "DDproduct_findings_count": DDproduct_findings_count,
            "DDproduct_name": DDproduct_name,
            "DDproduct_findings": DDproduct_findings,
            "DB_report_query": DB_report_query,
            "DefectDojoURL": DefectDojoURL,
        },
    )


@login_required
@allowed_users(allowed_roles=["administrator"])
def defectdojo_import(request, pk, ddpk):
    DB_report_query = get_object_or_404(DB_Report, pk=pk)
    DefectDojoURL = DEFECTDOJO_CONFIG["DefectDojoURL"]
    DefectDojoURLProducts = f"{DefectDojoURL}/api/v2/products/{ddpk}"
    DefectDojoApiKey = DEFECTDOJO_CONFIG["apiKey"]

    headersapi = {"Authorization": DefectDojoApiKey}

    r = requests.get(DefectDojoURLProducts, headers=headersapi, verify=False)

    if not (r.status_code == 200 or r.status_code == 201):
        return HttpResponseNotFound("Not found. Response error from DefectDojo")

    jsondata = json.loads(r.text)
    DDproduct_findings = jsondata["findings_list"]

    for finding in DDproduct_findings:
        DefectDojoURLFindings = f"{DefectDojoURL}/api/v2/findings/{finding}"
        r = requests.get(DefectDojoURLFindings, headers=headersapi, verify=False)

        jsondata = json.loads(r.text)

        finding_id = jsondata["id"]
        finding_display_id = jsondata["display_id"] or ""
        finding_title = jsondata["title"] or ""
        finding_cvssv3 = jsondata["cvssv3"] or ""
        finding_cvssv3_score = jsondata["cvssv3_score"] or 0
        finding_cwe = jsondata["cwe"] or 0
        finding_severity = (jsondata["severity"]).capitalize() or ""
        finding_description = jsondata["description"] or ""
        finding_mitigation = jsondata["mitigation"] or ""
        finding_impact = jsondata["impact"] or ""
        finding_steps_to_reproduce = jsondata["steps_to_reproduce"] or ""
        finding_ref = jsondata["references"] or ""
        finding_hash_code = jsondata["hash_code"] or uuid.uuid4()
        finding_file_path = jsondata["file_path"] or ""

        finding_final_description = (
            (finding_description + "\n----------\n" + finding_steps_to_reproduce)
            .replace("{", "\{\{")
            .replace("}", "\}\}")
        )

        cweDB = (
            DB_CWE.objects.filter(cwe_id=finding_cwe).first()
            or DB_CWE.objects.filter(cwe_id=0).first()
        )

        # Save Finding
        finding_to_DB = DB_Finding(
            report=DB_report_query,
            finding_id=finding_hash_code,
            display_id=finding_display_id,
            status="Open",
            title=finding_title,
            severity=finding_severity,
            cvss_base_score=finding_cvssv3,
            cvss_score=finding_cvssv3_score,
            description=finding_final_description,
            location=finding_file_path,
            impact=finding_impact,
            recommendation=finding_mitigation,
            ref=finding_ref,
            cwe=cweDB,
        )
        finding_to_DB.save()

    return redirect("report_view", pk=pk)


@login_required
@allowed_users(allowed_roles=["administrator"])
def defectdojo_import_finding(request, pk, ddpk):
    DB_report_query = get_object_or_404(DB_Report, pk=pk)
    DefectDojoURL = DEFECTDOJO_CONFIG["DefectDojoURL"]
    DefectDojoURLFindings = f"{DefectDojoURL}/api/v2/findings/{ddpk}"
    DefectDojoApiKey = DEFECTDOJO_CONFIG["apiKey"]

    headersapi = {"Authorization": DefectDojoApiKey}

    r = requests.get(DefectDojoURLFindings, headers=headersapi, verify=False)

    if not (r.status_code == 200 or r.status_code == 201):
        return HttpResponseNotFound("Not found. Response error from DefectDojo")

    jsondata = json.loads(r.text)

    jsondata["id"]
    finding_display_id = jsondata["display_id"] or ""
    finding_title = jsondata["title"] or ""
    finding_cvssv3 = jsondata["cvssv3"] or ""
    finding_cvssv3_score = jsondata["cvssv3_score"] or 0
    finding_cwe = jsondata["cwe"] or 0
    finding_severity = (jsondata["severity"]).capitalize() or ""
    finding_description = jsondata["description"] or ""
    finding_mitigation = jsondata["mitigation"] or ""
    finding_impact = jsondata["impact"] or ""
    finding_steps_to_reproduce = jsondata["steps_to_reproduce"] or ""
    finding_ref = jsondata["references"] or ""
    finding_hash_code = jsondata["hash_code"] or uuid.uuid4()
    finding_file_path = jsondata["file_path"] or ""

    finding_final_description = (
        (finding_description + "\n----------\n" + finding_steps_to_reproduce)
        .replace("{", "\{\{")
        .replace("}", "\}\}")
    )

    cweDB = (
        DB_CWE.objects.filter(cwe_id=finding_cwe).first()
        or DB_CWE.objects.filter(cwe_id=0).first()
    )

    # Save Finding
    finding_to_DB = DB_Finding(
        report=DB_report_query,
        finding_id=finding_hash_code,
        display_id=finding_display_id,
        status="Open",
        title=finding_title,
        severity=finding_severity,
        cvss_base_score=finding_cvssv3,
        cvss_score=finding_cvssv3_score,
        description=finding_final_description,
        location=finding_file_path,
        impact=finding_impact,
        recommendation=finding_mitigation,
        ref=finding_ref,
        cwe=cweDB,
    )
    finding_to_DB.save()

    return redirect("report_view", pk=pk)


# ----------------------------------------------------------------------
#                           Appendix
# ----------------------------------------------------------------------


@login_required
def report_appendix(request, pk):
    DB_report_query = get_object_or_404(DB_Report, pk=pk)

    DB_appendix_query = (
        DB_Appendix.objects.filter(report=DB_report_query).order_by("title").reverse()
    )
    count_appendix_query = DB_appendix_query.count()
    
    form = ReportToCloneForm()
    form.fields["report_to_clone"].initial = DB_report_query.pk

    return render(
        request,
        "appendix/report_appendix.html",
        {
            "form":form,
            "DB_report_query": DB_report_query,
            "DB_appendix_query": DB_appendix_query,
            "count_appendix_query": count_appendix_query,
        },
    )


@login_required
@allowed_users(allowed_roles=["administrator"])
def appendix_edit(request, pk):
    appendix = get_object_or_404(DB_Appendix, pk=pk)
    report = appendix.report
    DB_report_query = get_object_or_404(DB_Report, pk=report.pk)

    if request.method == "POST":
        form = NewAppendixForm(request.POST, instance=appendix, reportpk=report.pk)
        if form.is_valid():
            appendix = form.save(commit=False)
            appendix.save()
            form.save_m2m()  # Save tags

            if "_next" in request.POST:
                return redirect("appendix_add", pk=report.pk)
            else:
                return redirect("report_appendix", pk=report.pk)
    else:
        form = NewAppendixForm(instance=appendix, reportpk=report.pk)

    return render(
        request,
        "appendix/appendix_add.html",
        {
            "form": form,
            "DB_report_query": DB_report_query,
        },
    )


@login_required
@allowed_users(allowed_roles=["administrator"])
def appendix_add(request, pk):
    DB_report_query = get_object_or_404(DB_Report, pk=pk)
    if request.method == "POST":
        form = NewAppendixForm(request.POST, reportpk=pk)
        if form.is_valid():
            appendix = form.save(commit=False)
            appendix.report = DB_report_query
            appendix.save()

            findings = DB_Finding.objects.filter(pk__in=form["findings"].data)
            appendix.findings.set(findings)

            if "_next" in request.POST:
                return redirect("appendix_add", pk=pk)
            else:
                return redirect("report_appendix", pk=pk)
    else:
        form = NewAppendixForm(reportpk=pk)

    return render(
        request,
        "appendix/appendix_add.html",
        {"form": form, "DB_report_query": DB_report_query},
    )


@login_required
@allowed_users(allowed_roles=["administrator"])
def appendix_delete(request):
    if request.method == "POST":
        delete_id = request.POST["delete_id"]
        DB_Appendix.objects.filter(pk=delete_id).delete()

        return HttpResponse('{"status":"success"}', content_type="application/json")
    else:
        return HttpResponseServerError(
            '{"status":"fail"}', content_type="application/json"
        )


@login_required
def appendix_view(request, pk):
    appendix = get_object_or_404(DB_Appendix, pk=pk)

    return render(
        request,
        "appendix/appendix_view.html",
        {"DB_appendix_query": appendix},
    )


@login_required
@allowed_users(allowed_roles=["administrator"])
def appendix_duplicate(request):
    if request.method == "POST":
        report_to_clone = request.POST["report_to_clone"]
        report = get_object_or_404(DB_Report, pk=report_to_clone)
        duplicate_id = request.POST["duplicate_id"]
        appendix = DB_Appendix.objects.get(pk=duplicate_id)
        appendix.report = report
        findings = appendix.findings.all()
        appendix.pk = None
        copy_datetime = "-COPY-" + str(datetime.datetime.now().strftime("%Y%m%d%H%M"))
        appendix.title = appendix.title + copy_datetime

        appendix.save()
        appendix.findings.set(findings)
        return HttpResponse('{"status":"success"}', content_type="application/json")
    else:
        return HttpResponseServerError(
            '{"status":"fail"}', content_type="application/json"
        )


# ----------------------------------------------------------------------
#                           Attack Flow
# ----------------------------------------------------------------------


@login_required
def report_attackflows(request, pk):
    DB_report_query = get_object_or_404(DB_Report, pk=pk)

    DB_attackflow_query = (
        DB_AttackFlow.objects.filter(report=DB_report_query).order_by("title").reverse()
    )
    count_attackflow_query = DB_attackflow_query.count()
    
    form = ReportToCloneForm()
    form.fields["report_to_clone"].initial = DB_report_query.pk

    return render(
        request,
        "attackflow/report_attackflows.html",
        {
            "form": form,
            "DB_report_query": DB_report_query,
            "DB_attackflow_query": DB_attackflow_query,
            "count_attackflow_query": count_attackflow_query,
        },
    )


@login_required
@allowed_users(allowed_roles=["administrator"])
def attackflow_edit(request, pk):
    attackflow = get_object_or_404(DB_AttackFlow, pk=pk)

    report = attackflow.report
    DB_report_query = get_object_or_404(DB_Report, pk=report.pk)

    if request.method == "POST":
        form = NewAttackFlowForm(request.POST, instance=attackflow, reportpk=report.pk)
        if form.is_valid():
            attackflow = form.save(commit=False)
            attackflow.save()
            form.save_m2m()  # Save tags

            if "_next" in request.POST:
                return redirect("attackflow_add", pk=report.pk)
            else:
                return redirect("report_attackflows", pk=report.pk)
    else:
        form = NewAttackFlowForm(instance=attackflow, reportpk=report.pk)

    return render(
        request,
        "attackflow/attackflow_add.html",
        {
            "form": form,
            "DB_report_query": DB_report_query,
        },
    )


@login_required
def attackflow_view(request, pk):
    attackflow = get_object_or_404(DB_AttackFlow, pk=pk)

    return render(
        request,
        "attackflow/attackflow_view.html",
        {"DB_attackflow_query": attackflow},
    )


@login_required
@allowed_users(allowed_roles=["administrator"])
def attackflow_add(request, pk):
    DB_report_query = get_object_or_404(DB_Report, pk=pk)
    if request.method == "POST":
        form = NewAttackFlowForm(request.POST, reportpk=pk)
        if form.is_valid():
            attackflow = form.save(commit=False)
            attackflow.report = DB_report_query
            attackflow.save()

            findings = DB_Finding.objects.filter(pk__in=form["findings"].data)
            attackflow.findings.set(findings)

            if "_next" in request.POST:
                return redirect("attackflow_add", pk=pk)
            else:
                return redirect("report_attackflows", pk=pk)
    else:
        form = NewAttackFlowForm(reportpk=pk)

    return render(
        request,
        "attackflow/attackflow_add.html",
        {"form": form, "DB_report_query": DB_report_query},
    )


@login_required
@allowed_users(allowed_roles=["administrator"])
def attackflow_afb_fetch(request, pk):
    attackflow = get_object_or_404(DB_AttackFlow, pk=pk)
    attackflow_afb = attackflow.attackflow_afb

    if isinstance(attackflow_afb, str):
        return HttpResponse(attackflow_afb, content_type="application/json")

    return HttpResponseServerError('{"status":"fail"}', content_type="application/json")


@login_required
@allowed_users(allowed_roles=["administrator"])
def attackflow_afb_edit(request, pk):
    attackflow = get_object_or_404(DB_AttackFlow, pk=pk)

    try:
        attackflow_redirect = request.GET["redirect"]
        target_pk = request.GET["target_pk"]
    except Exception:
        return HttpResponseServerError(
            '{"status":"fail"}', content_type="application/json"
        )

    return render(
        request,
        "attackflow/attackflow_afb.html",
        {
            "attackflow": attackflow,
            "attackflow_redirect": attackflow_redirect,
            "target_pk": target_pk,
        },
    )


@login_required
@allowed_users(allowed_roles=["administrator"])
def attackflow_afb_upload(request, pk):
    attackflow = get_object_or_404(DB_AttackFlow, pk=pk)

    if request.method == "POST":
        data = json.loads(request.body)
        afb_content = data["afb_content"]
        afb_image = data["afb_image"]

        attackflow.attackflow_afb = afb_content
        attackflow.attackflow_image = afb_image
        attackflow.save()

        return HttpResponse('{"status":"success"}', content_type="application/json")
    else:
        return HttpResponseServerError(
            '{"status":"fail"}', content_type="application/json"
        )


@login_required
@allowed_users(allowed_roles=["administrator"])
def attackflow_delete(request):
    if request.method == "POST":
        delete_id = request.POST["delete_id"]
        DB_AttackFlow.objects.filter(pk=delete_id).delete()

        return HttpResponse('{"status":"success"}', content_type="application/json")
    else:
        return HttpResponseServerError(
            '{"status":"fail"}', content_type="application/json"
        )


@login_required
@allowed_users(allowed_roles=["administrator"])
def attackflow_duplicate(request):
    if request.method == "POST":
        report_to_clone = request.POST["report_to_clone"]
        report = get_object_or_404(DB_Report, pk=report_to_clone)
        duplicate_id = request.POST["duplicate_id"]
        attackflow = DB_AttackFlow.objects.get(pk=duplicate_id)
        attackflow.report = report
        findings = attackflow.findings.all()
        attackflow.pk = None
        copy_datetime = "-COPY-" + str(datetime.datetime.now().strftime("%Y%m%d%H%M"))
        attackflow.title = attackflow.title + copy_datetime

        attackflow.save()
        attackflow.findings.set(findings)
        return HttpResponse('{"status":"success"}', content_type="application/json")
    else:
        return HttpResponseServerError(
            '{"status":"fail"}', content_type="application/json"
        )


# ----------------------------------------------------------------------
#                           Custom Fields
# ----------------------------------------------------------------------


@login_required
def customfields(request, pk):
    DB_finding_query = get_object_or_404(DB_Finding, pk=pk)
    DB_custom_query = DB_Custom_field.objects.filter(finding_id=pk)

    count_custom_query = DB_custom_query.count()

    return render(
        request,
        "findings/custom_fields.html",
        {
            "DB_custom_query": DB_custom_query,
            "DB_finding_query": DB_finding_query,
            "count_custom_query": count_custom_query,
        },
    )


@login_required
@allowed_users(allowed_roles=["administrator"])
def field_add(request, pk):
    DB_finding_query = get_object_or_404(DB_Finding, pk=pk)

    if request.method == "POST":
        form = NewFieldForm(request.POST)
        if form.is_valid():
            custom_field = form.save(commit=False)
            custom_field.finding = DB_finding_query
            custom_field.save()

            if "_next" in request.POST:
                return redirect("field_add", pk=pk)
            else:
                return redirect("finding_view", pk=pk)
    else:
        form = NewFieldForm()
        form.fields["description"].initial = ""

    return render(
        request,
        "findings/custom_field_add.html",
        {"form": form, "DB_finding_query": DB_finding_query},
    )


@login_required
@allowed_users(allowed_roles=["administrator"])
def field_edit(request, pk):
    field = get_object_or_404(DB_Custom_field, pk=pk)
    finding_pk = field.finding.pk

    if request.method == "POST":
        form = NewFieldForm(request.POST, instance=field)
        if form.is_valid():
            form.save()
            return redirect("finding_view", pk=finding_pk)
    else:
        form = NewFieldForm(instance=field)
    return render(
        request,
        "findings/custom_field_add.html",
        {"form": form, "DB_finding_query": field.finding},
    )


@login_required
@allowed_users(allowed_roles=["administrator"])
def field_delete(request):
    if request.method == "POST":
        delete_id = request.POST["delete_id"]
        DB_Custom_field.objects.filter(pk=delete_id).delete()

        return HttpResponse('{"status":"success"}', content_type="application/json")
    else:
        return HttpResponseServerError(
            '{"status":"fail"}', content_type="application/json"
        )


# ----------------------------------------------------------------------
#                           Templates
# ----------------------------------------------------------------------


@login_required
def template_list(request):
    DB_findings_query = DB_Finding_Template.objects.order_by("title").reverse()

    return render(
        request, "findings/template_list.html", {"DB_findings_query": DB_findings_query}
    )


@login_required
@allowed_users(allowed_roles=["administrator"])
def template_add(request):
    if request.method == "POST":
        form = NewFindingTemplateForm(request.POST)
        if form.is_valid():
            template = form.save(commit=False)
            template.finding_id = uuid.uuid4()
            template.save()
            form.save_m2m()  # Save tags

            if "_next" in request.POST:
                return redirect("template_add")
            else:
                return redirect("template_list")
    else:
        form = NewFindingTemplateForm()
        form.fields["description"].initial = ""  # PETEREPORT_TEMPLATES['initial_text']
        form.fields["location"].initial = ""  # PETEREPORT_TEMPLATES['initial_text']
        form.fields["impact"].initial = ""  # PETEREPORT_TEMPLATES['initial_text']
        form.fields[
            "recommendation"
        ].initial = ""  # PETEREPORT_TEMPLATES['initial_text']
        form.fields["ref"].initial = ""  # PETEREPORT_TEMPLATES['initial_text']
        form.fields["cwe"].initial = "-1"
        form.fields["owasp"].initial = "-1"

    return render(
        request,
        "findings/template_add_" + PETEREPORT_CONFIG["cvss_version_default"] + ".html",
        {"form": form},
    )


@login_required
@allowed_users(allowed_roles=["administrator"])
def template_edit(request, pk):
    template = get_object_or_404(DB_Finding_Template, pk=pk)

    if request.method == "POST":
        form = NewFindingTemplateForm(request.POST, instance=template)
        if form.is_valid():
            template = form.save(commit=False)
            template.save()
            form.save_m2m()  # Save tags

            if "_next" in request.POST:
                return redirect("template_add")
            else:
                return redirect("template_list")
    else:
        form = NewFindingTemplateForm(instance=template)

    cvss_version = template.get_cvss_version()

    return render(
        request, "findings/template_add_" + cvss_version + ".html", {"form": form}
    )


@login_required
@allowed_users(allowed_roles=["administrator"])
def template_delete(request):
    if request.method == "POST":
        delete_id = request.POST["delete_id"]
        DB_Finding_Template.objects.filter(pk=delete_id).delete()

        return HttpResponse('{"status":"success"}', content_type="application/json")
    else:
        return HttpResponseServerError(
            '{"status":"fail"}', content_type="application/json"
        )


@login_required
def template_view(request, pk):
    DB_template_query = get_object_or_404(DB_Finding_Template, pk=pk)
    bookmark_exists = DB_template_query.bookmarks.filter(user=request.user).count() == 1

    return render(
        request,
        "findings/template_view.html",
        {
            "DB_template_query": DB_template_query,
            "bookmark_exists": bookmark_exists,
        },
    )


@login_required
@allowed_users(allowed_roles=["administrator"])
def template_add_finding(request, pk, cvssversion):
    DB_report_query = get_object_or_404(DB_Report, pk=pk)

    template_version_ids = [
        template.finding_id
        for template in DB_Finding_Template.objects.all()
        if template.get_cvss_version() == cvssversion
    ]
    DB_findings_query = DB_Finding_Template.objects.filter(
        finding_id__in=template_version_ids
    ).order_by("title")

    return render(
        request,
        "findings/templateaddfinding.html",
        {"DB_findings_query": DB_findings_query, "DB_report_query": DB_report_query},
    )


@login_required
@allowed_users(allowed_roles=["administrator"])
def template_add_report(request, pk, reportpk):
    DB_report_query = get_object_or_404(DB_Report, pk=reportpk)
    DB_finding_template_query = get_object_or_404(DB_Finding_Template, pk=pk)

    # save template in DB
    finding_uuid = uuid.uuid4()
    finding_status = "Open"
    finding_to_DB = DB_Finding(
        report=DB_report_query,
        finding_id=finding_uuid,
        display_id=DB_finding_template_query.display_id,
        title=DB_finding_template_query.title,
        severity=DB_finding_template_query.severity,
        cvss_base_score=DB_finding_template_query.cvss_base_score,
        cvss_score=DB_finding_template_query.cvss_score,
        description=DB_finding_template_query.description,
        status=finding_status,
        location=DB_finding_template_query.location,
        impact=DB_finding_template_query.impact,
        recommendation=DB_finding_template_query.recommendation,
        ref=DB_finding_template_query.ref,
        cwe=DB_finding_template_query.cwe,
        owasp=DB_finding_template_query.owasp,
        tags=DB_finding_template_query.tags,
    )

    finding_to_DB.save()

    return redirect("report_view", pk=reportpk)


# ----------------------------------------------------------------------
#                           CWE
# ----------------------------------------------------------------------


@login_required
def cwe_list(request):
    DB_cwe_query = DB_CWE.objects.order_by("cwe_name").all()

    return render(request, "cwe/cwe_list.html", {"DB_cwe_query": DB_cwe_query})


@login_required
@allowed_users(allowed_roles=["administrator"])
def cwe_add(request):
    if request.method == "POST":
        form = NewCWEForm(request.POST)
        if form.is_valid():
            cwe = form.save(commit=False)
            cwe.save()
            return redirect("cwe_list")
    else:
        form = NewCWEForm()
        latest_id = DB_CWE.objects.latest("cwe_id").cwe_id
        latest_id + 1
        # form.fields['cwe_id'].initial = next_id
        # form.fields['cwe_description'].initial = PETEREPORT_TEMPLATES['initial_text']

    return render(request, "cwe/cwe_add.html", {"form": form})


@login_required
@allowed_users(allowed_roles=["administrator"])
def cwe_delete(request):
    if request.method == "POST":
        delete_id = request.POST["delete_id"]
        if delete_id == -1:
            return HttpResponseServerError(
                '{"status":"fail", "reason": "Cannot delete CWE ID -1"}',
                content_type="application/json",
            )

        DB_CWE.objects.filter(pk=delete_id).delete()
        return HttpResponse('{"status":"success"}', content_type="application/json")
    else:
        return HttpResponseServerError(
            '{"status":"fail"}', content_type="application/json"
        )


@login_required
@allowed_users(allowed_roles=["administrator"])
def cwe_edit(request, pk):
    cwe = get_object_or_404(DB_CWE, pk=pk)

    if request.method == "POST":
        form = NewCWEForm(request.POST, instance=cwe)
        if form.is_valid():
            form.save()
            return redirect("cwe_list")
    else:
        form = NewCWEForm(instance=cwe)
    return render(request, "cwe/cwe_add.html", {"form": form})


# ----------------------------------------------------------------------
#                           OWASP
# ----------------------------------------------------------------------


@login_required
def owasp_list(request):
    DB_owasp_query = DB_OWASP.objects.order_by("owasp_name").all()

    return render(request, "owasp/owasp_list.html", {"DB_owasp_query": DB_owasp_query})


@login_required
@allowed_users(allowed_roles=["administrator"])
def owasp_add(request):
    if request.method == "POST":
        form = NewOWASPForm(request.POST)
        if form.is_valid():
            owasp = form.save(commit=False)
            owasp.save()
            return redirect("owasp_list")
    else:
        form = NewOWASPForm()

    return render(request, "owasp/owasp_add.html", {"form": form})


@login_required
@allowed_users(allowed_roles=["administrator"])
def owasp_delete(request):
    if request.method == "POST":
        delete_id = request.POST["delete_id"]
        if delete_id == -1:
            return HttpResponseServerError(
                '{"status":"fail", "reason": "Cannot delete OWASP ID -1"}',
                content_type="application/json",
            )

        DB_OWASP.objects.filter(pk=delete_id).delete()

        return HttpResponse('{"status":"success"}', content_type="application/json")
    else:
        return HttpResponseServerError(
            '{"status":"fail"}', content_type="application/json"
        )


@login_required
@allowed_users(allowed_roles=["administrator"])
def owasp_edit(request, pk):
    owasp = get_object_or_404(DB_OWASP, pk=pk)

    if request.method == "POST":
        form = NewOWASPForm(request.POST, instance=owasp)
        if form.is_valid():
            form.save()
            return redirect("owasp_list")
    else:
        form = NewOWASPForm(instance=owasp)
    return render(request, "owasp/owasp_add.html", {"form": form})


# ----------------------------------------------------------------------
#                           FTS Search
# ----------------------------------------------------------------------


@login_required
def fts(request):
    search_results = []  # item link, model type, item label, search result
    if request.method == "POST":
        form = NewFTSForm(request.POST)
        if form.is_valid():
            query = request.POST.get("q")
            models = request.POST.getlist("models")
            for model in models:
                try:
                    db_model = DB_FTSModel.objects.get(pk=model)
                    table_model_name = "preport_" + db_model.model_name.lower()
                    search_model_res = ufts.search_into_model(
                        table_model_name=table_model_name, query=query
                    )
                    if search_model_res is not None and len(search_model_res) > 0:
                        model = globals()[db_model.model_name]()
                        model_label = db_model.get_label().lower()
                        for res in search_model_res:
                            try:
                                item = model.__class__.objects.get(pk=res[0])
                                item_link = uurls.get_object_url(item)
                                search_results.append(
                                    (item_link, model_label, item.get_label(), res[1])
                                )
                            except DB_FTSModel.DoesNotExist:
                                pass
                except DB_FTSModel.DoesNotExist:
                    pass
    else:
        form = NewFTSForm()

    return render(
        request,
        "fts/fts.html",
        {
            "form": form,
            "search_results": search_results,
            "search_results_count": len(search_results),
        },
    )


# ----------------------------------------------------------------------
#                           Share
# ----------------------------------------------------------------------


@login_required
def share_list(request):
    DB_share_query = DB_ShareConnection.objects.order_by("title").all()
    return render(request, "share/share_list.html", {"DB_share_query": DB_share_query})


@login_required
def share_view(request, pk: int):
    # TODO
    raise Http404


@login_required
@allowed_users(allowed_roles=["administrator"])
def share_add(request):
    if request.method == "POST":
        form = NewShareForm(request.POST)
        if form.is_valid():
            share = form.save(commit=False)
            share.save()
            form.save_m2m()  # Save tags
            return redirect("share_list")
    else:
        form = NewShareForm()
    return render(
        request,
        "share/share_add.html",
        {
            "form": form,
            "list_func_deliverable": list(ushare.shares_deliverable.keys()),
            "list_func_finding": list(ushare.shares_finding.keys()),
        },
    )


@login_required
@allowed_users(allowed_roles=["administrator"])
def share_edit(request, pk):
    DB_share_query = get_object_or_404(DB_ShareConnection, pk=pk)
    if request.method == "POST":
        form = NewShareForm(request.POST, instance=DB_share_query)
        if form.is_valid():
            share = form.save(commit=False)
            share.save()
            form.save_m2m()  # Save tags
            return redirect("share_list")
    else:
        form = NewShareForm(instance=DB_share_query)
        # form.fields['creation_date'].initial = today
    return render(
        request,
        "share/share_add.html",
        {
            "form": form,
            "list_func_deliverable": list(ushare.shares_deliverable.keys()),
            "list_func_finding": list(ushare.shares_finding.keys()),
        },
    )


@login_required
@allowed_users(allowed_roles=["administrator"])
def share_delete(request):
    if request.method == "POST":
        delete_id = request.POST["delete_id"]
        DB_ShareConnection.objects.filter(pk=delete_id).delete()
        return HttpResponse('{"status":"success"}', content_type="application/json")
    else:
        return HttpResponseServerError(
            '{"status":"fail"}', content_type="application/json"
        )


@login_required
@allowed_users(allowed_roles=["administrator"])
def share_deliverable(request):
    if request.method == "POST":
        report = get_object_or_404(DB_Report, pk=request.POST["report_pk"])
        deliverable = get_object_or_404(
            DB_Deliverable, pk=request.POST["deliverable_pk"]
        )
        ShareClass = (
            ushare.shares_deliverable.get(report.share_deliverable.func, None)
            if report.share_deliverable
            else None
        )
        if ShareClass:
            try:
                shareobj = ShareClass(report.share_deliverable)

                file = os.path.join(
                    REPORTS_MEDIA_ROOT, deliverable.filetype, deliverable.filename
                )
                share_date, share_uuid = shareobj(
                    filename=file,
                    project=report.report_id,
                    remote_user=request.user.id,
                    name=report.title,
                )
                deliverable.share_date = share_date
                deliverable.share_uuid = share_uuid
                deliverable.save()
                data = json.dumps({"status": 200}, cls=LazyEncoder)
                return HttpResponse(data, content_type="application/json", status=200)
            except Exception as e:
                if hasattr(e, "response"):
                    try:
                        content = e.response.content.decode("utf-8")
                    except UnicodeDecodeError:
                        content = e.response.content.decode("iso-8859-1")
                    except Exception as ex:
                        content = str(ex)
                    finally:
                        msg = "Error from Remote Share Function: " + content
                else:
                    msg = str(e)
                data = json.dumps(
                    {"status": 500, "error": msg},
                    cls=LazyEncoder,
                )
                logger.error(e)
                return HttpResponseServerError(data, content_type="application/json")

    data = json.dumps({"status": 405, "error": _("Bad Function")}, cls=LazyEncoder)
    return HttpResponse(data, content_type="application/json", status=405)


# ----------------------------------------------------------------------
#                           Bookmark
# ----------------------------------------------------------------------


@login_required
def bookmark_toggle(request, model, pk):
    if request.method == "GET":
        match model:
            case "cspn_evaluation":
                model = get_object_or_404(DB_CSPN_Evaluation, pk=pk)
            case "customer":
                model = get_object_or_404(DB_Customer, pk=pk)
            case "finding":
                model = get_object_or_404(DB_Finding, pk=pk)
            case "finding_template":
                model = get_object_or_404(DB_Finding_Template, pk=pk)
            case "product":
                model = get_object_or_404(DB_Product, pk=pk)
            case "report":
                model = get_object_or_404(DB_Report, pk=pk)
            case _:
                raise Http404
        bookmark = model.bookmarks.filter(user=request.user).first()
        if bookmark is None:
            bookmark = DB_Bookmark(
                user=request.user,
                content_object=model,
            )
            bookmark.save()
            return HttpResponse('{"status":"created"}', content_type="application/json")
        bookmark.delete()
        return HttpResponse('{"status":"deleted"}', content_type="application/json")
    else:
        return HttpResponseServerError(
            '{"status":"fail"}', content_type="application/json"
        )


@login_required
def bookmark_list(request):
    return render(request, "bookmark/bookmark_list.html")


def build_bookmark_list(request) -> list:
    user = request.user
    DB_bookmark_query = DB_Bookmark.objects.filter(user=user.id)
    bookmarks = []
    for bookmark in DB_bookmark_query:
        item = bookmark.content_object
        item_link = uurls.get_object_url(item)
        item_label = item.get_label()
        bookmarks.append(
            (bookmark.get_model_name(), item_label, item_link, item.pk, bookmark.pk)
        )

        bookmarks = sorted(bookmarks, key=lambda t: (t[0], t[1]))

    return bookmarks
