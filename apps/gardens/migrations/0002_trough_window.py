# 新增萎凋槽允许窗字段 windowStart/windowEnd
import datetime

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("gardens", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="trough",
            name="windowStart",
            field=models.DateTimeField(
                default=datetime.datetime(
                    2026, 1, 1, 0, 0, tzinfo=datetime.timezone.utc
                ),
                verbose_name="允许窗开始",
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="trough",
            name="windowEnd",
            field=models.DateTimeField(
                default=datetime.datetime(
                    2027, 12, 31, 23, 59, tzinfo=datetime.timezone.utc
                ),
                verbose_name="允许窗结束",
            ),
            preserve_default=False,
        ),
    ]
