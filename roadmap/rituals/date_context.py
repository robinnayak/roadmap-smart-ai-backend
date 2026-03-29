from django.utils import timezone


def get_season(month):
    if month in (12, 1, 2):
        return "winter"
    if month in (3, 4, 5):
        return "spring"
    if month in (6, 7, 8):
        return "summer"
    return "autumn"


def is_birthday(user_profile, current_date=None):
    if not user_profile or not user_profile.date_of_birth:
        return False
    current_date = current_date or timezone.localdate()
    dob = user_profile.date_of_birth
    return dob.month == current_date.month and dob.day == current_date.day


def get_date_context(current_date=None):
    current_date = current_date or timezone.localdate()
    weekday = current_date.weekday()
    return {
        "date": current_date,
        "is_monday": weekday == 0,
        "is_friday": weekday == 4,
        "is_sunday": weekday == 6,
        "is_weekend": weekday >= 5,
        "is_jan_1": current_date.month == 1 and current_date.day == 1,
        "is_dec_31": current_date.month == 12 and current_date.day == 31,
        "season": get_season(current_date.month),
        "day_of_year": current_date.timetuple().tm_yday,
    }
