double _decimal(Object? value) => switch (value) {
  num number => number.toDouble(),
  String text => double.tryParse(text) ?? 0,
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

class FoodItem {
  const FoodItem({
    required this.id,
    required this.foodVersionId,
    required this.name,
    required this.basisAmountG,
    required this.kcal,
    required this.proteinG,
    required this.carbsG,
    required this.fatG,
    required this.source,
    required this.confidence,
    this.brand,
    this.barcode,
    this.state,
  });

  factory FoodItem.fromJson(Map<String, dynamic> json) => FoodItem(
    id: json['id'] as String,
    foodVersionId: json['food_version_id'] as String,
    name: json['name'] as String,
    brand: json['brand'] as String?,
    barcode: json['barcode'] as String?,
    state: json['state'] as String?,
    basisAmountG: _decimal(json['basis_amount_g']),
    kcal: _decimal(json['kcal']),
    proteinG: _decimal(json['protein_g']),
    carbsG: _decimal(json['carbs_g']),
    fatG: _decimal(json['fat_g']),
    source: json['source'] as String? ?? 'catalog',
    confidence: json['confidence'] as String? ?? 'confirmed',
  );

  final String id;
  final String foodVersionId;
  final String name;
  final String? brand;
  final String? barcode;
  final String? state;
  final double basisAmountG;
  final double kcal;
  final double proteinG;
  final double carbsG;
  final double fatG;
  final String source;
  final String confidence;
}

class FrequentFood {
  const FrequentFood({required this.food, required this.useCount});

  factory FrequentFood.fromJson(Map<String, dynamic> json) => FrequentFood(
    food: FoodItem.fromJson(json),
    useCount: json['use_count'] as int,
  );

  final FoodItem food;
  final int useCount;
}

class FoodSearchResult {
  const FoodSearchResult({
    required this.items,
    required this.total,
    required this.hasMore,
  });

  factory FoodSearchResult.fromJson(Map<String, dynamic> json) =>
      FoodSearchResult(
        items: (json['list'] as List<dynamic>)
            .map(
              (item) =>
                  FoodItem.fromJson(Map<String, dynamic>.from(item as Map)),
            )
            .toList(growable: false),
        total: json['total'] as int,
        hasMore: json['has_more'] as bool? ?? false,
      );

  final List<FoodItem> items;
  final int total;
  final bool hasMore;
}

class NutritionEntryItem {
  const NutritionEntryItem({
    required this.name,
    required this.amountG,
    required this.basisAmountG,
    required this.kcal,
    required this.proteinG,
    required this.carbsG,
    required this.fatG,
    required this.source,
    required this.confidence,
    this.foodVersionId,
  });

  factory NutritionEntryItem.fromJson(Map<String, dynamic> json) =>
      NutritionEntryItem(
        foodVersionId: json['food_version_id'] as String?,
        name: json['name'] as String? ?? '未命名食物',
        amountG: _decimal(json['amount_g']),
        basisAmountG: _decimal(json['basis_amount_g']),
        kcal: _decimal(json['kcal']),
        proteinG: _decimal(json['protein_g']),
        carbsG: _decimal(json['carbs_g']),
        fatG: _decimal(json['fat_g']),
        source: json['source'] as String? ?? 'user',
        confidence: json['confidence'] as String? ?? 'confirmed',
      );

  factory NutritionEntryItem.fromFood(FoodItem food, double amountG) =>
      NutritionEntryItem(
        foodVersionId: food.foodVersionId,
        name: food.name,
        amountG: amountG,
        basisAmountG: food.basisAmountG,
        kcal: food.kcal,
        proteinG: food.proteinG,
        carbsG: food.carbsG,
        fatG: food.fatG,
        source: food.source,
        confidence: food.confidence,
      );

  final String? foodVersionId;
  final String name;
  final double amountG;
  final double basisAmountG;
  final double kcal;
  final double proteinG;
  final double carbsG;
  final double fatG;
  final String source;
  final String confidence;

  NutritionEntryItem withAmount(double value) => NutritionEntryItem(
    foodVersionId: foodVersionId,
    name: name,
    amountG: value,
    basisAmountG: basisAmountG,
    kcal: kcal,
    proteinG: proteinG,
    carbsG: carbsG,
    fatG: fatG,
    source: source,
    confidence: confidence,
  );

  Map<String, dynamic> toInputJson() {
    if (foodVersionId case final id?) {
      return {'food_version_id': id, 'amount_g': amountG};
    }
    return {
      'food_version_id': null,
      'amount_g': amountG,
      'name': name,
      'basis_amount_g': basisAmountG,
      'kcal': kcal,
      'protein_g': proteinG,
      'carbs_g': carbsG,
      'fat_g': fatG,
      'source': source,
      'confidence': confidence,
    };
  }
}

class NutritionEntry {
  const NutritionEntry({
    required this.id,
    required this.mealType,
    required this.eatenAt,
    required this.items,
    required this.totals,
    required this.isFlexibleMeal,
    required this.version,
    this.notes,
  });

  factory NutritionEntry.fromJson(Map<String, dynamic> json) => NutritionEntry(
    id: json['id'] as String,
    mealType: json['meal_type'] as String,
    eatenAt: DateTime.parse(json['eaten_at'] as String),
    items: (json['items'] as List<dynamic>)
        .map(
          (item) => NutritionEntryItem.fromJson(
            Map<String, dynamic>.from(item as Map),
          ),
        )
        .toList(growable: false),
    totals: NutritionTotals.fromJson(
      Map<String, dynamic>.from(json['totals'] as Map),
    ),
    isFlexibleMeal: json['is_flexible_meal'] as bool? ?? false,
    notes: json['notes'] as String?,
    version: json['version'] as int,
  );

  final String id;
  final String mealType;
  final DateTime eatenAt;
  final List<NutritionEntryItem> items;
  final NutritionTotals totals;
  final bool isFlexibleMeal;
  final String? notes;
  final int version;

  String get displayName {
    final names = items
        .map((item) => item.name)
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
          Map<String, dynamic>.from(json['consumed'] as Map),
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

class WeeklyNutritionSummary {
  const WeeklyNutritionSummary({
    required this.startDate,
    required this.endDate,
    required this.dailyAverage,
    required this.totalEntries,
    required this.recordedDays,
    required this.flexibleMeals,
    required this.completeness,
  });

  factory WeeklyNutritionSummary.fromJson(Map<String, dynamic> json) =>
      WeeklyNutritionSummary(
        startDate: DateTime.parse(json['start_date'] as String),
        endDate: DateTime.parse(json['end_date'] as String),
        dailyAverage: NutritionTotals.fromJson(
          Map<String, dynamic>.from(json['daily_average'] as Map),
        ),
        totalEntries: json['total_entries'] as int,
        recordedDays: json['recorded_days'] as int,
        flexibleMeals: json['flexible_meals'] as int,
        completeness: _decimal(json['record_completeness']),
      );

  final DateTime startDate;
  final DateTime endDate;
  final NutritionTotals dailyAverage;
  final int totalEntries;
  final int recordedDays;
  final int flexibleMeals;
  final double completeness;
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
    this.isFlexibleMeal = false,
    this.notes,
  });

  final String name;
  final String mealType;
  final double amountG;
  final double kcal;
  final double proteinG;
  final double carbsG;
  final double fatG;
  final bool isFlexibleMeal;
  final String? notes;
}

class FoodServingInput {
  const FoodServingInput({
    required this.food,
    required this.amountG,
    required this.mealType,
    this.isFlexibleMeal = false,
    this.notes,
  });

  final FoodItem food;
  final double amountG;
  final String mealType;
  final bool isFlexibleMeal;
  final String? notes;
}

class NutritionEntryEditInput {
  const NutritionEntryEditInput({
    required this.mealType,
    required this.items,
    required this.isFlexibleMeal,
    this.notes,
  });

  final String mealType;
  final List<NutritionEntryItem> items;
  final bool isFlexibleMeal;
  final String? notes;
}

class CustomFoodInput {
  const CustomFoodInput({
    required this.name,
    required this.basisAmountG,
    required this.kcal,
    required this.proteinG,
    required this.carbsG,
    required this.fatG,
    this.brand,
  });

  final String name;
  final String? brand;
  final double basisAmountG;
  final double kcal;
  final double proteinG;
  final double carbsG;
  final double fatG;

  Map<String, dynamic> toJson() => {
    'name': name,
    'brand': brand,
    'barcode': null,
    'basis_amount_g': basisAmountG,
    'kcal': kcal,
    'protein_g': proteinG,
    'carbs_g': carbsG,
    'fat_g': fatG,
  };
}

class NutritionAdvice {
  const NutritionAdvice({
    required this.foodName,
    required this.recommendation,
    required this.cautions,
  });

  factory NutritionAdvice.fromJson(Map<String, dynamic> json) =>
      NutritionAdvice(
        foodName: json['food_name'] as String,
        recommendation: json['recommendation'] as String,
        cautions: (json['cautions'] as List<dynamic>? ?? const [])
            .whereType<String>()
            .toList(growable: false),
      );

  final String foodName;
  final String recommendation;
  final List<String> cautions;
}

class FlexibleMeal {
  const FlexibleMeal({
    required this.id,
    required this.scheduledDate,
    required this.label,
    required this.version,
    this.notes,
  });

  factory FlexibleMeal.fromJson(Map<String, dynamic> json) => FlexibleMeal(
    id: json['id'] as String,
    scheduledDate: DateTime.parse(json['scheduled_date'] as String),
    label: json['label'] as String,
    notes: json['notes'] as String?,
    version: json['version'] as int,
  );

  final String id;
  final DateTime scheduledDate;
  final String label;
  final String? notes;
  final int version;
}

class NutritionTextDraft {
  const NutritionTextDraft({
    required this.id,
    required this.mealType,
    required this.totals,
    required this.missingItems,
    required this.questions,
    required this.version,
  });

  factory NutritionTextDraft.fromJson(Map<String, dynamic> json) =>
      NutritionTextDraft(
        id: json['id'] as String,
        mealType: json['meal_type'] as String,
        totals: NutritionTotals.fromJson(
          Map<String, dynamic>.from(json['totals'] as Map),
        ),
        missingItems: (json['missing_items'] as List<dynamic>? ?? const [])
            .whereType<String>()
            .toList(growable: false),
        questions: (json['questions'] as List<dynamic>? ?? const [])
            .whereType<String>()
            .toList(growable: false),
        version: json['version'] as int,
      );

  final String id;
  final String mealType;
  final NutritionTotals totals;
  final List<String> missingItems;
  final List<String> questions;
  final int version;
}

class RecipeSummary {
  const RecipeSummary({
    required this.id,
    required this.name,
    required this.servings,
    required this.totals,
    required this.version,
  });

  factory RecipeSummary.fromJson(Map<String, dynamic> json) => RecipeSummary(
    id: json['id'] as String,
    name: json['name'] as String,
    servings: _decimal(json['servings']),
    totals: NutritionTotals.fromJson(
      Map<String, dynamic>.from(json['totals'] as Map),
    ),
    version: json['version'] as int,
  );

  final String id;
  final String name;
  final double servings;
  final NutritionTotals totals;
  final int version;
}
