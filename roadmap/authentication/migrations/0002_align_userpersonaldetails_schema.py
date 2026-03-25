from django.db import migrations


FORWARDS_SQL = """
ALTER TABLE authentication_userpersonaldetails
ADD COLUMN IF NOT EXISTS date_of_birth date;

UPDATE authentication_userpersonaldetails
SET date_of_birth = make_date(
    GREATEST(
        EXTRACT(YEAR FROM CURRENT_DATE)::int - LEAST(GREATEST(current_age, 13), 100),
        1900
    ),
    1,
    1
)
WHERE date_of_birth IS NULL
  AND current_age BETWEEN 13 AND 100;

ALTER TABLE authentication_userpersonaldetails
DROP COLUMN IF EXISTS target_age;
"""


REVERSE_SQL = """
ALTER TABLE authentication_userpersonaldetails
ADD COLUMN IF NOT EXISTS target_age integer;

ALTER TABLE authentication_userpersonaldetails
DROP COLUMN IF EXISTS date_of_birth;
"""


class Migration(migrations.Migration):

    dependencies = [
        ("authentication", "0001_initial"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql=FORWARDS_SQL,
                    reverse_sql=REVERSE_SQL,
                )
            ],
            state_operations=[],
        )
    ]
