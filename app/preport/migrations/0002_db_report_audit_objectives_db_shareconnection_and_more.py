# Generated by Django 4.2.2 on 2023-06-20 14:25

from django.db import migrations, models
import django.db.models.deletion
import martor.models
import taggit.managers


class Migration(migrations.Migration):

    dependencies = [
        ('taggit', '0005_auto_20220424_2025'),
        ('preport', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='db_report',
            name='audit_objectives',
            field=martor.models.MartorField(blank=True),
        ),
        migrations.CreateModel(
            name='DB_ShareConnection',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=255)),
                ('type', models.CharField(max_length=255)),
                ('func', models.CharField(max_length=255)),
                ('url', models.CharField(max_length=255)),
                ('credentials', models.CharField(max_length=255)),
                ('creation_date', models.DateTimeField(auto_now_add=True)),
                ('tags', taggit.managers.TaggableManager(blank=True, help_text='A comma-separated list of tags.', through='taggit.TaggedItem', to='taggit.Tag', verbose_name='Tags')),
            ],
            options={
                'verbose_name_plural': 'Connection',
            },
        ),
        migrations.AddField(
            model_name='db_report',
            name='share_deliverable',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='share_deliverable', to='preport.db_shareconnection'),
        ),
        migrations.AddField(
            model_name='db_report',
            name='share_finding',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='share_finding', to='preport.db_shareconnection'),
        ),
    ]
