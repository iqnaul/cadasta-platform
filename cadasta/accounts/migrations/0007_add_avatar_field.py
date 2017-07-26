# -*- coding: utf-8 -*-
# Generated by Django 1.10.7 on 2017-07-14 20:34
from __future__ import unicode_literals

import buckets.fields
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0006_add_measurement_field'),
    ]

    operations = [
        migrations.AddField(
            model_name='historicaluser',
            name='avatar',
            field=buckets.fields.S3FileField(blank=True, upload_to='avatars'),
        ),
        migrations.AddField(
            model_name='user',
            name='avatar',
            field=buckets.fields.S3FileField(blank=True, upload_to='avatars'),
        ),
    ]
