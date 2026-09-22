double _decimal(Object? value) => switch (value) {
  num number => number.toDouble(),
  String text => double.tryParse(text) ?? 0,
  _ => 0,
};

List<String> _strings(Object? value) => value is List<dynamic>
    ? value.whereType<String>().toList(growable: false)
    : const <String>[];

class ExerciseListItem {
  const ExerciseListItem({
    required this.id,
    required this.name,
    required this.aliases,
    required this.equipment,
    required this.primaryMuscles,
    required this.isCustom,
  });

  factory ExerciseListItem.fromJson(Map<String, dynamic> json) =>
      ExerciseListItem(
        id: json['id'] as String,
        name: json['name_zh'] as String,
        aliases: _strings(json['aliases']),
        equipment: json['equipment'] as String,
        primaryMuscles: _strings(json['primary_muscles']),
        isCustom: json['is_custom'] as bool? ?? false,
      );

  final String id;
  final String name;
  final List<String> aliases;
  final String equipment;
  final List<String> primaryMuscles;
  final bool isCustom;
}

class ExercisePageData {
  const ExercisePageData({
    required this.items,
    required this.total,
    required this.hasMore,
  });

  factory ExercisePageData.fromJson(Map<String, dynamic> json) =>
      ExercisePageData(
        items: (json['list'] as List<dynamic>)
            .map(
              (item) => ExerciseListItem.fromJson(
                Map<String, dynamic>.from(item as Map),
              ),
            )
            .toList(growable: false),
        total: json['total'] as int,
        hasMore: json['has_more'] as bool? ?? false,
      );

  final List<ExerciseListItem> items;
  final int total;
  final bool hasMore;
}

class ExerciseSubstitution {
  const ExerciseSubstitution({
    required this.id,
    required this.name,
    required this.equipment,
    required this.reason,
  });

  factory ExerciseSubstitution.fromJson(Map<String, dynamic> json) =>
      ExerciseSubstitution(
        id: json['id'] as String,
        name: json['name_zh'] as String,
        equipment: json['equipment'] as String,
        reason: json['reason'] as String? ?? '',
      );

  final String id;
  final String name;
  final String equipment;
  final String reason;
}

class ExerciseDetail {
  const ExerciseDetail({
    required this.id,
    required this.name,
    required this.aliases,
    required this.equipment,
    required this.primaryMuscles,
    required this.secondaryMuscles,
    required this.instructions,
    required this.breathing,
    required this.commonErrors,
    required this.safetyNotes,
    required this.substitutions,
    required this.version,
    required this.isCustom,
    this.movementPattern,
    this.difficulty,
    this.notes,
  });

  factory ExerciseDetail.fromJson(Map<String, dynamic> json) => ExerciseDetail(
    id: json['id'] as String,
    name: json['name_zh'] as String,
    aliases: _strings(json['aliases']),
    movementPattern: json['movement_pattern'] as String?,
    equipment: json['equipment'] as String,
    difficulty: json['difficulty'] as String?,
    primaryMuscles: _strings(json['primary_muscles']),
    secondaryMuscles: _strings(json['secondary_muscles']),
    instructions: _strings(json['instructions']),
    breathing: _strings(json['breathing']),
    commonErrors: _strings(json['common_errors']),
    safetyNotes: _strings(json['safety_notes']),
    substitutions: (json['substitutions'] as List<dynamic>? ?? const [])
        .map(
          (item) => ExerciseSubstitution.fromJson(
            Map<String, dynamic>.from(item as Map),
          ),
        )
        .toList(growable: false),
    notes: json['notes'] as String?,
    version: json['version'] as int,
    isCustom: json['is_custom'] as bool? ?? false,
  );

  final String id;
  final String name;
  final List<String> aliases;
  final String? movementPattern;
  final String equipment;
  final String? difficulty;
  final List<String> primaryMuscles;
  final List<String> secondaryMuscles;
  final List<String> instructions;
  final List<String> breathing;
  final List<String> commonErrors;
  final List<String> safetyNotes;
  final List<ExerciseSubstitution> substitutions;
  final String? notes;
  final int version;
  final bool isCustom;
}

class ExerciseHistorySet {
  const ExerciseHistorySet({
    required this.index,
    required this.weightKg,
    required this.reps,
    this.rir,
    this.rpe,
  });

  factory ExerciseHistorySet.fromJson(Map<String, dynamic> json) =>
      ExerciseHistorySet(
        index: json['set_index'] as int,
        weightKg: _decimal(json['weight_kg']),
        reps: json['reps'] as int,
        rir: json['rir'] as int?,
        rpe: json['rpe'] == null ? null : _decimal(json['rpe']),
      );

  final int index;
  final double weightKg;
  final int reps;
  final int? rir;
  final double? rpe;
}

class ExerciseHistoryItem {
  const ExerciseHistoryItem({
    required this.workoutId,
    required this.startedAt,
    required this.status,
    required this.nameSnapshot,
    required this.sets,
  });

  factory ExerciseHistoryItem.fromJson(Map<String, dynamic> json) =>
      ExerciseHistoryItem(
        workoutId: json['workout_id'] as String,
        startedAt: DateTime.parse(json['started_at'] as String),
        status: json['status'] as String,
        nameSnapshot: json['name_snapshot'] as String,
        sets: (json['sets'] as List<dynamic>)
            .map(
              (item) => ExerciseHistorySet.fromJson(
                Map<String, dynamic>.from(item as Map),
              ),
            )
            .toList(growable: false),
      );

  final String workoutId;
  final DateTime startedAt;
  final String status;
  final String nameSnapshot;
  final List<ExerciseHistorySet> sets;
}

class CustomExerciseInput {
  const CustomExerciseInput({
    required this.name,
    required this.equipment,
    required this.primaryMuscles,
    required this.secondaryMuscles,
    this.notes,
  });

  final String name;
  final String equipment;
  final List<String> primaryMuscles;
  final List<String> secondaryMuscles;
  final String? notes;

  Map<String, dynamic> toJson() => {
    'name_zh': name,
    'equipment': equipment,
    'primary_muscles': primaryMuscles,
    'secondary_muscles': secondaryMuscles,
    'notes': notes,
  };
}

String equipmentLabel(String value) => switch (value) {
  'bodyweight' => '徒手',
  'barbell' => '杠铃',
  'dumbbell' => '哑铃',
  'machine' => '固定器械',
  'cable' => '绳索器械',
  'kettlebell' => '壶铃',
  'band' => '弹力带',
  'other' => '其他',
  _ => value,
};

String muscleLabel(String value) => switch (value) {
  'chest' => '胸部',
  'back' => '背部',
  'shoulders' => '肩部',
  'biceps' => '肱二头肌',
  'triceps' => '肱三头肌',
  'quadriceps' => '股四头肌',
  'hamstrings' => '腘绳肌',
  'gluteus' => '臀肌',
  'calves' => '小腿',
  'core' => '核心',
  'forearms' => '前臂',
  'trapezius' => '斜方肌',
  'hip_flexors' => '髋屈肌',
  'adductors' => '内收肌',
  _ => value,
};
