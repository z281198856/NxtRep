// Nutrition records use the same Asia/Shanghai calendar day as the API.
DateTime nutritionToday({DateTime? now}) {
  final china = (now ?? DateTime.now()).toUtc().add(const Duration(hours: 8));
  return DateTime(china.year, china.month, china.day);
}

DateTime nutritionRecordedAt(DateTime day, String mealType, {DateTime? now}) {
  final current = now ?? DateTime.now();
  final today = nutritionToday(now: current);
  if (day.year == today.year &&
      day.month == today.month &&
      day.day == today.day) {
    return current.toUtc();
  }
  final hour = switch (mealType) {
    'breakfast' => 8,
    'dinner' => 18,
    'snack' => 15,
    _ => 12,
  };
  return DateTime.utc(day.year, day.month, day.day, hour - 8);
}

String nutritionDateLabel(DateTime day) =>
    '${day.year}年${day.month}月${day.day}日';
