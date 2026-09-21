import '../../../core/network/api_client.dart';
import '../../../core/network/api_exception.dart';
import '../domain/profile_models.dart';

abstract interface class ProfileDataSource {
  Future<UserProfile> getProfile();

  Future<TrainingPreferences> getTrainingPreferences();

  Future<AppSettings> getSettings();

  Future<UserProfile> updatePersonalProfile(
    UserProfile current,
    PersonalProfileInput input,
  );

  Future<({UserProfile profile, TrainingPreferences preferences})>
  updateTrainingPreferences(
    UserProfile profile,
    TrainingPreferences current,
    TrainingPreferencesInput input,
  );

  Future<AppSettings> updateSettings(
    AppSettings current,
    AppSettingsInput input,
  );
}

class ProfileRepository implements ProfileDataSource {
  ProfileRepository(this._apiClient);

  final ApiClient _apiClient;

  @override
  Future<UserProfile> getProfile() async {
    final json = expectJsonObject(
      await _apiClient.get('/profile'),
      context: '个人资料接口',
    );
    return UserProfile.fromJson(json);
  }

  @override
  Future<TrainingPreferences> getTrainingPreferences() async {
    final json = expectJsonObject(
      await _apiClient.get('/profile/goals-and-constraints'),
      context: '训练偏好接口',
    );
    return TrainingPreferences.fromJson(json);
  }

  @override
  Future<AppSettings> getSettings() async {
    final json = expectJsonObject(
      await _apiClient.get('/settings'),
      context: '应用设置接口',
    );
    return AppSettings.fromJson(json);
  }

  @override
  Future<UserProfile> updatePersonalProfile(
    UserProfile current,
    PersonalProfileInput input,
  ) async {
    final json = expectJsonObject(
      await _apiClient.patch(
        '/profile',
        body: {
          'display_name': input.displayName,
          'sex': input.sex,
          'birth_date': _dateOnly(input.birthDate),
          'height_cm': input.heightCm,
          'experience_level': input.experienceLevel,
          'session_duration_minutes': input.sessionDurationMinutes,
          'expected_version': current.version,
        },
      ),
      context: '更新个人资料接口',
    );
    return UserProfile.fromJson(json);
  }

  @override
  Future<({UserProfile profile, TrainingPreferences preferences})>
  updateTrainingPreferences(
    UserProfile profile,
    TrainingPreferences current,
    TrainingPreferencesInput input,
  ) async {
    final body = <String, Object?>{
      'goal_type': input.goalType,
      'target_date': _dateOnly(current.targetDate),
      'target_weight_kg': current.targetWeightKg,
      'equipment': input.trainingMode.equipmentCodes,
      'preferred_exercises': current.preferredExercises,
      'disliked_exercises': current.dislikedExercises,
      'pain_or_injuries': current.painOrInjuries
          .map((item) => item.toJson())
          .toList(growable: false),
      'allergies': current.allergies,
      'dietary_preferences': current.dietaryPreferences,
      'expected_version': current.version,
    };

    final check = expectJsonObject(
      await _apiClient.post('/profile/goal-check', body: body),
      context: '目标检查接口',
    );
    if (check['valid'] != true) {
      throw const ApiException(
        code: 'GOAL_CHECK_FAILED',
        message: '当前目标与训练条件存在冲突，请调整后重试',
      );
    }

    final preferencesJson = expectJsonObject(
      await _apiClient.put('/profile/goals-and-constraints', body: body),
      context: '更新训练偏好接口',
    );
    final profileJson = expectJsonObject(
      await _apiClient.patch(
        '/profile',
        body: {
          'weekly_training_days': input.weeklyTrainingDays,
          'expected_version': profile.version,
        },
      ),
      context: '更新训练频率接口',
    );
    return (
      profile: UserProfile.fromJson(profileJson),
      preferences: TrainingPreferences.fromJson(preferencesJson),
    );
  }

  @override
  Future<AppSettings> updateSettings(
    AppSettings current,
    AppSettingsInput input,
  ) async {
    final json = expectJsonObject(
      await _apiClient.patch(
        '/settings',
        body: {
          'unit_system': input.unitSystem,
          'privacy_mode': input.privacyMode,
          'share_anonymous_analytics': input.shareAnonymousAnalytics,
          'expected_version': current.version,
        },
      ),
      context: '更新应用设置接口',
    );
    return AppSettings.fromJson(json);
  }
}

String? _dateOnly(DateTime? value) {
  if (value == null) return null;
  final month = value.month.toString().padLeft(2, '0');
  final day = value.day.toString().padLeft(2, '0');
  return '${value.year}-$month-$day';
}
