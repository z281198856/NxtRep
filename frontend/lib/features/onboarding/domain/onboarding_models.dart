class ProfileData {
  const ProfileData({
    required this.experienceLevel,
    required this.weeklyTrainingDays,
    required this.version,
  });

  factory ProfileData.fromJson(Map<String, dynamic> json) => ProfileData(
    experienceLevel: json['experience_level'] as String?,
    weeklyTrainingDays: json['weekly_training_days'] as int?,
    version: json['version'] as int,
  );

  final String? experienceLevel;
  final int? weeklyTrainingDays;
  final int version;
}

/// The two training environments exposed during first-run onboarding.
///
/// The API stores concrete equipment codes rather than a generic environment
/// name. Keeping that mapping here lets the onboarding UI stay simple without
/// breaking exercise and template matching on the backend.
enum TrainingMode {
  bodyweight,
  gymEquipment;

  List<String> get equipmentCodes => switch (this) {
    TrainingMode.bodyweight => const ['bodyweight'],
    TrainingMode.gymEquipment => const ['barbell', 'dumbbell', 'cable', 'rack'],
  };
}

class OnboardingSubmission {
  const OnboardingSubmission({
    required this.goalType,
    required this.weeklyTrainingDays,
    required this.equipment,
    this.painBodyPart,
  });

  final String goalType;
  final int weeklyTrainingDays;
  final List<String> equipment;
  final String? painBodyPart;
}
