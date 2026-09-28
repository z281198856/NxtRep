double? _optionalDecimal(Object? value) => switch (value) {
  num number => number.toDouble(),
  String text => double.tryParse(text),
  _ => null,
};

double _decimal(Object? value) => _optionalDecimal(value) ?? 0;

enum BodyMetric {
  weight('weight', '体重', 'kg'),
  waist('waist', '腰围', 'cm'),
  bodyFat('body_fat', '体脂', '%');

  const BodyMetric(this.apiName, this.label, this.unit);

  final String apiName;
  final String label;
  final String unit;
}

class BodyMeasurement {
  const BodyMeasurement({
    required this.id,
    required this.measuredAt,
    required this.source,
    required this.version,
    this.weightKg,
    this.waistCm,
    this.neckCm,
    this.hipCm,
    this.bodyFatPercent,
    this.bodyFatMethod,
    this.conditions,
    this.notes,
  });

  factory BodyMeasurement.fromJson(Map<String, dynamic> json) =>
      BodyMeasurement(
        id: json['id'] as String,
        measuredAt: DateTime.parse(json['measured_at'] as String),
        source: json['source'] as String,
        version: json['version'] as int,
        weightKg: _optionalDecimal(json['weight_kg']),
        waistCm: _optionalDecimal(json['waist_cm']),
        neckCm: _optionalDecimal(json['neck_cm']),
        hipCm: _optionalDecimal(json['hip_cm']),
        bodyFatPercent: _optionalDecimal(json['body_fat_percent']),
        bodyFatMethod: json['body_fat_method'] as String?,
        conditions: json['conditions'] as String?,
        notes: json['notes'] as String?,
      );

  final String id;
  final DateTime measuredAt;
  final double? weightKg;
  final double? waistCm;
  final double? neckCm;
  final double? hipCm;
  final double? bodyFatPercent;
  final String? bodyFatMethod;
  final String source;
  final String? conditions;
  final String? notes;
  final int version;

  double? valueFor(BodyMetric metric) => switch (metric) {
    BodyMetric.weight => weightKg,
    BodyMetric.waist => waistCm,
    BodyMetric.bodyFat => bodyFatPercent,
  };
}

class BodyMeasurementInput {
  const BodyMeasurementInput({
    required this.measuredAt,
    this.weightKg,
    this.waistCm,
    this.neckCm,
    this.hipCm,
    this.bodyFatPercent,
    this.conditions,
    this.notes,
  });

  final DateTime measuredAt;
  final double? weightKg;
  final double? waistCm;
  final double? neckCm;
  final double? hipCm;
  final double? bodyFatPercent;
  final String? conditions;
  final String? notes;

  bool get hasValue =>
      weightKg != null ||
      waistCm != null ||
      neckCm != null ||
      hipCm != null ||
      bodyFatPercent != null;
}

class NavyProfileDefaults {
  const NavyProfileDefaults({this.sex, this.heightCm});

  final String? sex;
  final double? heightCm;
}

class NavyBodyFatInput {
  const NavyBodyFatInput({
    required this.sex,
    required this.heightCm,
    required this.waistCm,
    required this.neckCm,
    this.hipCm,
  });

  final String sex;
  final double heightCm;
  final double waistCm;
  final double neckCm;
  final double? hipCm;

  Map<String, Object?> toJson({required bool save}) => {
    'sex': sex,
    'height_cm': heightCm,
    'waist_cm': waistCm,
    'neck_cm': neckCm,
    'hip_cm': sex == 'female' ? hipCm : null,
    'save': save,
  };
}

class NavyBodyFatResult {
  const NavyBodyFatResult({
    required this.valuePercent,
    required this.rangeMinPercent,
    required this.rangeMaxPercent,
    required this.disclaimer,
  });

  factory NavyBodyFatResult.fromJson(Map<String, dynamic> json) =>
      NavyBodyFatResult(
        valuePercent: _decimal(json['value_percent']),
        rangeMinPercent: _decimal(json['range_min_percent']),
        rangeMaxPercent: _decimal(json['range_max_percent']),
        disclaimer: json['disclaimer'] as String? ?? '仅供观察趋势，不是医学测量',
      );

  final double valuePercent;
  final double rangeMinPercent;
  final double rangeMaxPercent;
  final String disclaimer;
}

class SavedBodyFatEstimate {
  const SavedBodyFatEstimate({
    required this.calculatedAt,
    required this.method,
    required this.result,
  });

  factory SavedBodyFatEstimate.fromJson(Map<String, dynamic> json) =>
      SavedBodyFatEstimate(
        calculatedAt: DateTime.parse(json['calculated_at'] as String),
        method: json['method'] as String,
        result: NavyBodyFatResult.fromJson(json),
      );

  final DateTime calculatedAt;
  final String method;
  final NavyBodyFatResult result;
}

class TrainingProgressSummary {
  const TrainingProgressSummary({
    required this.workoutCount,
    required this.completionRate,
    required this.totalDurationMinutes,
    required this.personalRecordCount,
  });

  factory TrainingProgressSummary.fromJson(Map<String, dynamic> json) =>
      TrainingProgressSummary(
        workoutCount: json['workout_count'] as int? ?? 0,
        completionRate: _decimal(json['completion_rate']),
        totalDurationMinutes: json['total_duration_minutes'] as int? ?? 0,
        personalRecordCount: json['pr_count'] as int? ?? 0,
      );

  final int workoutCount;
  final double completionRate;
  final int totalDurationMinutes;
  final int personalRecordCount;
}

class BodyProgressSummary {
  const BodyProgressSummary({
    this.startWeightKg,
    this.endWeightKg,
    this.smoothedChangeKg,
  });

  factory BodyProgressSummary.fromJson(Map<String, dynamic> json) =>
      BodyProgressSummary(
        startWeightKg: _optionalDecimal(json['weight_start_kg']),
        endWeightKg: _optionalDecimal(json['weight_end_kg']),
        smoothedChangeKg: _optionalDecimal(json['smoothed_change_kg']),
      );

  final double? startWeightKg;
  final double? endWeightKg;
  final double? smoothedChangeKg;
}

class ProgressOverview {
  const ProgressOverview({required this.training, required this.body});

  factory ProgressOverview.fromJson(Map<String, dynamic> json) =>
      ProgressOverview(
        training: TrainingProgressSummary.fromJson(
          json['training'] as Map<String, dynamic>? ?? const {},
        ),
        body: BodyProgressSummary.fromJson(
          json['body'] as Map<String, dynamic>? ?? const {},
        ),
      );

  final TrainingProgressSummary training;
  final BodyProgressSummary body;
}

class BodyTrendPoint {
  const BodyTrendPoint({
    required this.date,
    required this.rawValue,
    required this.smoothedValue,
  });

  factory BodyTrendPoint.fromJson(Map<String, dynamic> json) => BodyTrendPoint(
    date: DateTime.parse(json['date'] as String),
    rawValue: _decimal(json['raw_value']),
    smoothedValue: _decimal(json['smoothed_value']),
  );

  final DateTime date;
  final double rawValue;
  final double smoothedValue;
}

class PersonalRecord {
  const PersonalRecord({
    required this.id,
    required this.exerciseName,
    required this.recordType,
    required this.value,
    required this.occurredAt,
    required this.workoutId,
  });

  factory PersonalRecord.fromJson(Map<String, dynamic> json) => PersonalRecord(
    id: json['id'] as String,
    exerciseName: json['exercise_name'] as String,
    recordType: json['record_type'] as String,
    value: _decimal(json['value']),
    occurredAt: DateTime.parse(json['occurred_at'] as String),
    workoutId: json['workout_id'] as String,
  );

  final String id;
  final String exerciseName;
  final String recordType;
  final double value;
  final DateTime occurredAt;
  final String workoutId;
}
