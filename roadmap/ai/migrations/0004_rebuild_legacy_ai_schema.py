from django.db import migrations


def reconcile_ai_schema(apps, schema_editor):
    connection = schema_editor.connection
    existing_tables = set(connection.introspection.table_names())

    AIModelUsageStats = apps.get_model("ai", "AIModelUsageStats")
    AIProcessingJob = apps.get_model("ai", "AIProcessingJob")
    AIPromptTemplate = apps.get_model("ai", "AIPromptTemplate")
    AIUserChurnState = apps.get_model("ai", "AIUserChurnState")
    AIReengagementAction = apps.get_model("ai", "AIReengagementAction")

    current_processing_table = AIProcessingJob._meta.db_table
    processing_columns = set()

    if current_processing_table in existing_tables:
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select column_name, udt_name
                    from information_schema.columns
                    where table_schema = current_schema()
                      and table_name = %s
                    """,
                    [current_processing_table],
                )
                postgres_columns = dict(cursor.fetchall())
            processing_columns = set(postgres_columns)
            is_legacy_processing_schema = (
                postgres_columns.get("id") != "uuid"
                or "row_data" in processing_columns
            )
        else:
            with connection.cursor() as cursor:
                processing_columns = {
                    column.name
                    for column in connection.introspection.get_table_description(
                        cursor,
                        current_processing_table,
                    )
                }
            is_legacy_processing_schema = "row_data" in processing_columns

        if is_legacy_processing_schema:
            with connection.cursor() as cursor:
                cursor.execute(f'SELECT COUNT(*) FROM "{current_processing_table}"')
                row_count = cursor.fetchone()[0]
            if row_count:
                raise RuntimeError(
                    "Legacy ai_processing_jobs rows exist with an incompatible schema. "
                    "Migrate or clear that data before applying this migration."
                )
            schema_editor.delete_model(AIProcessingJob)
            existing_tables.remove(current_processing_table)

    for model in (
        AIModelUsageStats,
        AIProcessingJob,
        AIPromptTemplate,
        AIUserChurnState,
        AIReengagementAction,
    ):
        table_name = model._meta.db_table
        if table_name not in existing_tables:
            schema_editor.create_model(model)
            existing_tables.add(table_name)


class Migration(migrations.Migration):

    dependencies = [
        ("ai", "0003_realign_legacy_processing_job_table"),
    ]

    operations = [
        migrations.RunPython(
            reconcile_ai_schema,
            migrations.RunPython.noop,
        ),
    ]
