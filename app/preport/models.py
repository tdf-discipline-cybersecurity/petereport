# -*- coding: utf-8 -*-
from __future__ import unicode_literals
from django.db import models
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericRelation
from martor.models import MartorField
from django.contrib.auth.models import User
from multi_email_field.fields import MultiEmailField
from taggit.managers import TaggableManager
import datetime
import re
from petereport.settings import PETEREPORT_CONFIG

import pathlib

cvss_regex = re.compile(".+ \((CVSS:(.+?)/.+)\)$")


def get_id_for_section(item) -> str:
    return (
        (type(item).__name__ + str(item.pk))
        .replace("DB_", "")
        .replace("-", "")
        .replace("_", "")
    )


# ---------- Bookmark ------------


class DB_Bookmark(models.Model):
    user = models.ForeignKey(
        User, blank=False, on_delete=models.CASCADE, related_name="bookmarks"
    )
    content_type = models.ForeignKey(ContentType, blank=False, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")
    fts_enabled = False

    class Meta:
        verbose_name_plural = "Bookmarks"

    def get_model_name(self):
        return re.sub(r"^DB_", "", self.content_object.get_model_name()).lower()


# ---------- OWASP ------------


class DB_OWASP(models.Model):
    owasp_id = models.IntegerField(blank=False, unique=True)
    owasp_year = models.IntegerField(blank=False, unique=False)
    owasp_name = models.CharField(max_length=255, blank=True)
    owasp_description = models.TextField(blank=True)
    owasp_url = models.CharField(max_length=255, blank=True)
    owasp_full_id = models.CharField(max_length=20, blank=True)
    fts_enabled = True

    class Meta:
        verbose_name_plural = "OWASPs"

    def __str__(self):
        return str(self.owasp_id)

    def save(self, *args, **kwargs):
        prefix = "A"
        if self.owasp_id < 0:
            self.owasp_full_id = "-1"
        elif self.owasp_id < 10:
            prefix += "0"
        self.owasp_full_id = prefix + str(self.owasp_id) + ":" + str(self.owasp_year)
        super().save(*args, **kwargs)

    def get_label(self):
        return "%s - %s" % (self.owasp_full_id, self.owasp_name)


# ---------- CSPN Evaluation Stage ------------


class DB_CSPN_Evaluation_Stage(models.Model):
    cspn_id = models.CharField(blank=False, unique=True, max_length=4)
    name = models.CharField(max_length=255, blank=True)
    fts_enabled = True

    class Meta:
        verbose_name_plural = "CSPN Evaluation Stages"

    def __str__(self):
        return str(self.cspn_id)

    def get_label(self):
        return "%s - %s" % (self.cspn_id, self.name)

    def get_model_name(self):
        return type(self).__name__
    
    def get_id_for_section(self):
        return get_id_for_section(self)


# ---------- CWE ------------


class DB_CWE(models.Model):
    cwe_id = models.IntegerField(blank=False, unique=True)
    cwe_name = models.CharField(max_length=255, blank=True)
    cwe_description = models.TextField(blank=True)
    fts_enabled = True

    class Meta:
        verbose_name_plural = "CWEs"

    def __str__(self):
        return str(self.cwe_id)

    def get_label(self):
        return "%s - %s" % (self.cwe_id, self.cwe_name)


# ---------- Customer ------------


class DB_Customer(models.Model):
    name = models.CharField(max_length=255, blank=False)
    contact_list = MultiEmailField()
    contact_sp_mail = models.EmailField(max_length=255, blank=True)
    contact_dp_mail = models.EmailField(max_length=255, blank=True)
    description = MartorField(blank=True)
    tags = TaggableManager(blank=True)
    bookmarks = GenericRelation(DB_Bookmark)
    fts_enabled = True

    class Meta:
        verbose_name_plural = "Customers"

    def __str__(self):
        return str(self.name)

    def get_label(self):
        return self.name

    def get_model_name(self):
        return type(self).__name__


# ---------- Product ------------


class DB_Product(models.Model):
    customer = models.ForeignKey(DB_Customer, blank=False, on_delete=models.CASCADE)
    name = models.CharField(max_length=255, blank=False)
    description = MartorField(blank=True)
    recovery = MartorField(blank=True)
    installation = MartorField(blank=True)
    usage = MartorField(blank=True)
    tags = TaggableManager(blank=True)
    bookmarks = GenericRelation(DB_Bookmark)
    fts_enabled = True
    fts_excluded_fields = ["customer"]

    class Meta:
        verbose_name_plural = "Products"

    def __str__(self):
        return str(self.name)

    def get_label(self):
        return self.name

    def get_model_name(self):
        return type(self).__name__


# ---------- Settings ------------


def logo_dst(instance, filename):
    return "images/company_picture{}".format(pathlib.Path(filename).suffix)


class DB_Settings(models.Model):
    company_name = models.CharField(max_length=255, blank=False)
    company_website = models.CharField(max_length=255, blank=True)
    company_address = models.CharField(max_length=255, blank=True)
    # File will be uploaded to MEDIA_ROOT/images/<filename>
    company_picture = models.ImageField(upload_to=logo_dst, blank=True)
    fts_enabled = True
    fts_excluded_fields = ["company_picture"]

    def save(self, *args, **kwargs):
        if self.__class__.objects.count():
            self.pk = self.__class__.objects.first().pk
        super().save(*args, **kwargs)

    class Meta:
        verbose_name_plural = "Settings"

    def get_label(self):
        return self.company_name


# ---------- ShareConnection ------------


class DB_ShareConnection(models.Model):
    title = models.CharField(max_length=255, blank=False)
    type = models.CharField(max_length=255, blank=False)
    func = models.CharField(max_length=255, blank=False)
    url = models.CharField(max_length=255, blank=False)
    credentials = models.CharField(max_length=255, blank=False)
    creation_date = models.DateTimeField(auto_now_add=True)
    tags = TaggableManager(blank=True)

    def __str__(self) -> str:
        return str(self.title)

    def get_label(self) -> str:
        return str(self)

    class Meta:
        verbose_name_plural = "Connection"


# ---------- Report ------------


class DB_Report(models.Model):
    product = models.ForeignKey(DB_Product, on_delete=models.CASCADE)
    share_deliverable = models.ForeignKey(
        DB_ShareConnection,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="share_deliverable",
    )
    share_finding = models.ForeignKey(
        DB_ShareConnection,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="share_finding",
    )
    report_id = models.CharField(max_length=255, blank=False, unique=True)
    title = models.CharField(max_length=255, blank=False)
    classification = models.CharField(max_length=255, blank=True)
    version = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=255, blank=True)
    approver = models.CharField(max_length=255, blank=True)
    author = models.CharField(max_length=255, blank=True)
    executive_summary_image = models.TextField(blank=True)
    cwe_categories_summary_image = models.TextField(blank=True)
    owasp_categories_summary_image = models.TextField(blank=True)
    executive_summary = MartorField(blank=True)
    audit_objectives = MartorField(blank=True)
    scope = MartorField(blank=True)
    outofscope = MartorField(blank=True)
    cvss_version = models.CharField(
        blank=True, max_length=200, default=PETEREPORT_CONFIG["cvss_version_default"]
    )
    methodology = MartorField(blank=True)
    recommendation = MartorField(blank=True)
    creation_date = models.DateTimeField(auto_now_add=True)
    report_date = models.DateField(blank=False)
    audit_start = models.DateField(blank=True, null=True)
    audit_end = models.DateField(blank=True, null=True)
    tags = TaggableManager(blank=True)
    bookmarks = GenericRelation(DB_Bookmark)
    fts_enabled = True
    fts_excluded_fields = ["product", "share_deliverable", "share_finding"]

    def __str__(self):
        return str(self.title)

    def get_label(self):
        return self.title
    
    def get_id_for_section(self):
        return get_id_for_section(self)

    def get_model_name(self):
        return type(self).__name__

    class Meta:
        verbose_name_plural = "Reports"


# ---------- Deliverable ------------
class DB_Deliverable(models.Model):
    report = models.ForeignKey(DB_Report, on_delete=models.CASCADE)
    filename = models.CharField(max_length=2048, blank=False, unique=False)
    generation_date = models.DateTimeField(blank=False)
    filetype = models.CharField(max_length=32, blank=False, unique=False)
    filetemplate = models.CharField(max_length=64, blank=False, unique=False)
    share_date = models.DateTimeField(null=True, blank=True)
    share_uuid = models.CharField(max_length=4096, blank=True, unique=False)
    fts_enabled = True
    fts_excluded_fields = ["report"]

    def get_label(self):
        return self.filename

    def __str__(self):
        return str(self.filename)

    class Meta:
        verbose_name_plural = "Deliverables"


# ---------- CSPN Evaluation ------------


class DB_CSPN_Evaluation(models.Model):
    report = models.ForeignKey(DB_Report, on_delete=models.CASCADE)
    cspn_id = models.CharField(blank=True, max_length=200)
    status = models.CharField(blank=True, max_length=200, default="Not Evaluated")
    evaluation = MartorField(blank=True)
    expert_notice = MartorField(blank=True)
    stage = models.ForeignKey(
        DB_CSPN_Evaluation_Stage,
        default=0,
        on_delete=models.SET_DEFAULT,
        null=False,
        blank=False,
    )
    tags = TaggableManager(blank=True)
    bookmarks = GenericRelation(DB_Bookmark)
    fts_enabled = True
    fts_excluded_fields = ["report", "cspn_id", "stage"]

    def __str__(self):
        return str(self.stage)

    def get_label(self):
        return str(self.stage)
    
    def get_id_for_section(self):
        return get_id_for_section(self)

    def get_model_name(self):
        return type(self).__name__

    class Meta:
        verbose_name_plural = "CSPN Evaluations"


# ---------- Finding ------------


class DB_Finding(models.Model):
    report = models.ForeignKey(DB_Report, on_delete=models.CASCADE)
    finding_id = models.CharField(blank=True, max_length=200)
    display_id = models.CharField(blank=True, max_length=10)
    order = models.PositiveIntegerField(default=0)
    status = models.CharField(blank=True, max_length=200, default="Opened")
    created_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(blank=True, null=True)
    title = models.CharField(blank=True, max_length=200)
    severity = models.CharField(blank=True, max_length=200)
    cvss_base_score = models.CharField(blank=True, max_length=200)
    cvss_score = models.DecimalField(max_digits=3, decimal_places=1, default=0)
    description = MartorField(blank=True)
    location = MartorField(blank=True)
    impact = MartorField(blank=True)
    recommendation = MartorField(blank=True)
    ref = MartorField(blank=True)
    poc = MartorField(blank=True)
    cwe = models.ForeignKey(
        DB_CWE, default=0, on_delete=models.SET_DEFAULT, null=False, blank=False
    )
    owasp = models.ForeignKey(
        DB_OWASP, default=0, on_delete=models.SET_DEFAULT, null=False, blank=False
    )
    tags = TaggableManager(blank=True)
    bookmarks = GenericRelation(DB_Bookmark)
    fts_enabled = True
    fts_excluded_fields = ["report", "finding_id", "cwe", "owasp", "order"]

    def __str__(self):
        return str(self.title)

    def get_label(self):
        return self.title

    def save(self, *args, **kwargs):
        if self.status == "Closed" and self.closed_at is None:
            self.closed_at = datetime.datetime.now()
        super().save(*args, **kwargs)

    def get_cvss_score_anchor(self):
        m = cvss_regex.search(self.cvss_base_score)
        if m:
            return m.group(1)

    def get_model_name(self):
        return type(self).__name__
    
    def get_id_for_section(self):
        return get_id_for_section(self)

    class Meta:
        verbose_name_plural = "Findings"


# ---------- Finding templates ------------


class DB_Finding_Template(models.Model):
    finding_id = models.CharField(blank=False, max_length=200)
    display_id = models.CharField(blank=True, max_length=10)
    title = models.CharField(blank=False, max_length=200)
    severity = models.CharField(blank=True, max_length=200)
    cvss_base_score = models.CharField(blank=True, max_length=200)
    cvss_score = models.DecimalField(max_digits=3, decimal_places=1, default=0)
    description = MartorField(blank=True)
    location = MartorField(blank=True)
    impact = MartorField(blank=True)
    recommendation = MartorField(blank=True)
    ref = MartorField(blank=True)
    cwe = models.ForeignKey(
        DB_CWE, default=0, on_delete=models.SET_DEFAULT, null=False, blank=False
    )
    owasp = models.ForeignKey(
        DB_OWASP, default=0, on_delete=models.SET_DEFAULT, null=False, blank=False
    )
    tags = TaggableManager(blank=True)
    bookmarks = GenericRelation(DB_Bookmark)
    fts_enabled = True
    fts_excluded_fields = [
        "finding_id",
        "cwe",
        "owasp",
    ]

    def get_label(self):
        return self.title

    def get_cvss_score_anchor(self):
        m = cvss_regex.search(self.cvss_base_score)
        if m:
            return m.group(1)

    def get_cvss_version(self):
        m = cvss_regex.search(self.cvss_base_score)
        if m:
            return m.group(2)

    def get_model_name(self):
        return type(self).__name__


# ---------- Appendix ------------


class DB_Appendix(models.Model):
    report = models.ForeignKey(DB_Report, on_delete=models.CASCADE)
    findings = models.ManyToManyField(
        DB_Finding, related_name="appendix_finding", blank=True
    )
    title = models.CharField(blank=False, max_length=200)
    description = MartorField(blank=True)
    
    def get_id_for_section(self):
        return get_id_for_section(self)

    def get_label(self):
        return self.title


# ---------- Attack Flow ------------


class DB_AttackFlow(models.Model):
    report = models.ForeignKey(DB_Report, on_delete=models.CASCADE)
    findings = models.ManyToManyField(
        DB_Finding, related_name="attackflow_finding", blank=True
    )
    title = models.CharField(blank=False, max_length=200)
    description = MartorField(blank=True)
    attackflow_afb = models.TextField()
    attackflow_image = models.TextField()

    def get_label(self):
        return self.title
    
    def get_id_for_section(self):
        return get_id_for_section(self)


# ---------- Custom Field ------------


class DB_Custom_field(models.Model):
    # finding = models.ManyToManyField(DB_Finding, related_name='custom_field_finding', blank=True)
    finding = models.ForeignKey(
        DB_Finding,
        related_name="custom_field_finding",
        blank=True,
        on_delete=models.CASCADE,
    )
    title = models.CharField(blank=False, max_length=200)
    description = MartorField(blank=True)
    fts_enabled = True
    fts_excluded_fields = ["finding"]

    def get_label(self):
        return self.title


# ---------- FTS Model ------------


class DB_FTSModel(models.Model):
    model_name = models.CharField(max_length=64)
    fts_fields = models.CharField(max_length=1024)

    def get_label(self):
        return f"{self.model_name.replace('DB_', '', 1)}"

    def __str__(self):
        return f"{self.model_name.replace('DB_', '', 1)} ({self.fts_fields})"
