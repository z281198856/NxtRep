enum ProfileTrainingMode {
  bodyweight,
  gymEquipment;

  List<String> get equipmentCodes => switch (this) {
    ProfileTrainingMode.bodyweight => const ['bodyweight'],
    ProfileTrainingMode.gymEquipment => const [
      'barbell',
      'dumbbell',
      'cable',
      'rack',
    ],
  };

  static ProfileTrainingMode fromEquipment(List<String> equipment) {
    return equipment.length == 1 && equipment.single == 'bodyweight'
        ? ProfileTrainingMode.bodyweight
        : ProfileTrainingMode.gymEquipment;
  }
}

class UserProfile {
  const UserProfile({
    required this.displayName,
    required this.sex,
    required this.birthDate,
    required this.heightCm,
    required this.experienceLevel,
    required this.weeklyTrainingDays,
    required this.sessionDurationMinutes,
    required this.timezone,
    required this.version,
  });

  factory UserProfile.fromJson(Map<String, dynamic> json) => UserProfile(
    displayName: json['display_name'] as String?,
    sex: json['sex'] as String? ?? 'unspecified',
    birthDate: _date(json['birth_date']),
    heightCm: _number(json['height_cm']),
    experienceLevel: json['experience_level'] as String?,
    weeklyTrainingDays: json['weekly_training_days'] as int?,
    sessionDurationMinutes: json['session_duration_minutes'] as int?,
    timezone: json['timezone'] as String? ?? 'Asia/Shanghai',
    version: json['version'] as int,
  );

  final String? displayName;
  final String sex;
  final DateTime? birthDate;
  final double? heightCm;
  final String? experienceLevel;
  final int? weeklyTrainingDays;
  final int? sessionDurationMinutes;
  final String timezone;
  final int version;
}

class PainOrInjury {
  const PainOrInjury({
    required this.kind,
    required this.bodyPart,
    required this.severity,
    required this.notes,
  });

  factory PainOrInjury.fromJson(Map<String, dynamic> json) => PainOrInjury(
    kind: json['kind'] as String,
    bodyPart: json['body_part'] as String,
    severity: json['severity'] as int?,
    notes: json['notes'] as String?,
  );

  final String kind;
  final String bodyPart;
  final int? severity;
  final String? notes;

  Map<String, Object?> toJson() => {
    'kind': kind,
    'body_part': bodyPart,
    'severity': severity,
    'notes': notes,
  };
}

class TrainingPreferences {
  const TrainingPreferences({
    required this.version,
    required this.goalType,
    required this.targetDate,
    required this.targetWeightKg,
    required this.equipment,
    required this.preferredExercises,
    required this.dislikedExercises,
    required this.painOrInjuries,
    required this.allergies,
    required this.dietaryPreferences,
    required this.warnings,
  });

  factory TrainingPreferences.fromJson(Map<String, dynamic> json) {
    final goal = json['goal'] as Map<String, dynamic>;
    final constraints = json['constraints'] as Map<String, dynamic>;
    return TrainingPreferences(
      version: json['version'] as int,
      goalType: goal['goal_type'] as String,
      targetDate: _date(goal['target_date']),
      targetWeightKg: _number(goal['target_weight_kg']),
      equipment: _strings(constraints['equipment']),
      preferredExercises: _strings(constraints['preferred_exercises']),
      dislikedExercises: _strings(constraints['disliked_exercises']),
      painOrInjuries:
          (constraints['pain_or_injuries'] as List<dynamic>? ?? const [])
              .map(
                (item) => PainOrInjury.fromJson(item as Map<String, dynamic>),
              )
              .toList(growable: false),
      allergies: _strings(constraints['allergies']),
      dietaryPreferences: _strings(constraints['dietary_preferences']),
      warnings: _strings(json['warnings']),
    );
  }

  final int version;
  final String goalType;
  final DateTime? targetDate;
  final double? targetWeightKg;
  final List<String> equipment;
  final List<String> preferredExercises;
  final List<String> dislikedExercises;
  final List<PainOrInjury> painOrInjuries;
  final List<String> allergies;
  final List<String> dietaryPreferences;
  final List<String> warnings;

  ProfileTrainingMode get trainingMode =>
      ProfileTrainingMode.fromEquipment(equipment);
}

class AppSettings {
  const AppSettings({
    required this.unitSystem,
    required this.timezone,
    required this.privacyMode,
    required this.shareAnonymousAnalytics,
    required this.version,
  });

  factory AppSettings.fromJson(Map<String, dynamic> json) => AppSettings(
    unitSystem: json['unit_system'] as String,
    timezone: json['timezone'] as String,
    privacyMode: json['privacy_mode'] as String,
    shareAnonymousAnalytics: json['share_anonymous_analytics'] as bool,
    version: json['version'] as int,
  );

  final String unitSystem;
  final String timezone;
  final String privacyMode;
  final bool shareAnonymousAnalytics;
  final int version;
}

class PersonalProfileInput {
  const PersonalProfileInput({
    required this.displayName,
    required this.sex,
    required this.birthDate,
    required this.heightCm,
    required this.experienceLevel,
    required this.sessionDurationMinutes,
  });

  final String? displayName;
  final String sex;
  final DateTime? birthDate;
  final double? heightCm;
  final String? experienceLevel;
  final int? sessionDurationMinutes;
}

class TrainingPreferencesInput {
  const TrainingPreferencesInput({
    required this.goalType,
    required this.weeklyTrainingDays,
    required this.trainingMode,
  });

  final String goalType;
  final int weeklyTrainingDays;
  final ProfileTrainingMode trainingMode;
}

class AppSettingsInput {
  const AppSettingsInput({
    required this.unitSystem,
    required this.privacyMode,
    required this.shareAnonymousAnalytics,
  });

  final String unitSystem;
  final String privacyMode;
  final bool shareAnonymousAnalytics;
}

double? _number(Object? value) => switch (value) {
  num number => number.toDouble(),
  String text => double.tryParse(text),
  _ => null,
};

DateTime? _date(Object? value) =>
    value is String ? DateTime.tryParse(value) : null;

List<String> _strings(Object? value) => (value as List<dynamic>? ?? const [])
    .map((item) => item.toString())
    .toList(growable: false);
