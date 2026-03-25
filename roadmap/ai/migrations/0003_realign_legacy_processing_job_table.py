from django.db import migrations


def realign_legacy_processing_job_table(apps, schema_editor):
    connection = schema_editor.connection
    existing_tables = set(connection.introspection.table_names())
    legacy_table = "ai_aiprocessingjob"
    current_table = "ai_processing_jobs"

    if legacy_table in existing_tables and current_table not in existing_tables:
        with connection.cursor() as cursor:
            cursor.execute(
                f'ALTER TABLE "{legacy_table}" RENAME TO "{current_table}"'
            )


class Migration(migrations.Migration):

    dependencies = [
        ("ai", "0002_initial"),
    ]

    operations = [
        migrations.RunPython(
            realign_legacy_processing_job_table,
            migrations.RunPython.noop,
        ),
    ]
