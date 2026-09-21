double _decimal(Object? value) => switch (value) {
  num number => number.toDouble(),
  String text => double.parse(text),
  _ => 0,
};

class NutritionTotals {
  const NutritionTotals({
    required this.kcal,
    required this.proteinG,
    required this.carbsG,
    required this.fatG,
  });

  factory NutritionTotals.fromJson(Map<String, dynamic> json) =>
      NutritionTotals(
        kcal: _decimal(json['kcal']),
        proteinG: _decimal(json['protein_g']),
        carbsG: _decimal(json['carbs_g']),
        fatG: _decimal(json['fat_g']),
      );

  final double kcal;
  final double proteinG;
  final double carbsG;
  final double fatG;
}

class NutritionEntry {
  const NutritionEntry({
    required this.id,
    required this.mealType,
    required this.eatenAt,
    required this.items,
    required this.totals,
    required this.version,
  });

  factory NutritionEntry.fromJson(Map<String, dynamic> json) => NutritionEntry(
    id: json['id'] as String,
    mealType: json['meal_type'] as String,
    eatenAt: DateTime.parse(json['eaten_at'] as String),
    items: List<Map<String, dynamic>>.from(
      (json['items'] as List<dynamic>).map(
        (item) => Map<String, dynamic>.from(item as Map),
      ),
    ),
    totals: NutritionTotals.fromJson(json['totals'] as Map<String, dynamic>),
    version: json['version'] as int,
  );

  final String id;
  final String mealType;
  final DateTime eatenAt;
  final List<Map<String, dynamic>> items;
  final NutritionTotals totals;
  final int version;

  String get displayName {
    final names = items
        .map((item) => item['name'] as String?)
        .whereType<String>()
        .where((name) => name.isNotEmpty)
        .toList();
    return names.isEmpty ? '饮食记录' : names.join('、');
  }
}

class DailyNutritionSummary {
  const DailyNutritionSummary({
    required this.date,
    required this.consumed,
    required this.completeness,
    this.target,
    this.remaining,
  });

  factory DailyNutritionSummary.fromJson(Map<String, dynamic> json) =>
      DailyNutritionSummary(
        date: DateTime.parse(json['date'] as String),
        consumed: NutritionTotals.fromJson(
          json['consumed'] as Map<String, dynamic>,
        ),
        completeness: _decimal(json['record_completeness']),
        target: json['target'] == null
            ? null
            : Map<String, dynamic>.from(json['target'] as Map),
        remaining: json['remaining'] == null
            ? null
            : Map<String, dynamic>.from(json['remaining'] as Map),
      );

  final DateTime date;
  final NutritionTotals consumed;
  final double completeness;
  final Map<String, dynamic>? target;
  final Map<String, dynamic>? remaining;
}

class ManualNutritionInput {
  const ManualNutritionInput({
    required this.name,
    required this.mealType,
    required this.amountG,
    required this.kcal,
    required this.proteinG,
    required this.carbsG,
    required this.fatG,
  });

  final String name;
  final String mealType;
  final double amountG;
  final double kcal;
  final double proteinG;
  final double carbsG;
  final double fatG;
}
