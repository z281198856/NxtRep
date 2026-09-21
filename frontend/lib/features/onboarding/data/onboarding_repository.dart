import '../../../core/network/api_client.dart';
import '../../../core/network/api_exception.dart';
import '../domain/onboarding_models.dart';

class OnboardingRepository {
  OnboardingRepository(this._apiClient);

  final ApiClient _apiClient;

  Future<ProfileData> getProfile() async {
    final json = expectJsonObject(
      await _apiClient.get('/profile'),
      context: '个人资料接口',
    );
    return ProfileData.fromJson(json);
  }

  Future<int?> _getExistingGoalsVersion() async {
    try {
      final json = expectJsonObject(
        await _apiClient.get('/profile/goals-and-constraints'),
        context: '目标接口',
      );
      return json['version'] as int;
    } on ApiException catch (error) {
      if (error.code == 'GOALS_NOT_FOUND') {
        return null;
      }
      rethrow;
    }
  }

  Future<void> complete(OnboardingSubmission submission) async {
    final profile = await getProfile();
    final goalsVersion = await _getExistingGoalsVersion();

    final goalsBody = <String, Object?>{
      'goal_type': submission.goalType,
      'target_date': null,
      'target_weight_kg': null,
      'equipment': submission.equipment,
      'preferred_exercises': const <String>[],
      'disliked_exercises': const <String>[],
      'pain_or_injuries': [
        if (submission.painBodyPart case final bodyPart?)
          {
            'kind': 'current_pain',
            'body_part': bodyPart,
            'severity': null,
            'notes': null,
          },
      ],
      'allergies': const <String>[],
      'dietary_preferences': const <String>[],
    };
    if (goalsVersion != null) {
      goalsBody['expected_version'] = goalsVersion;
    }

    await _apiClient.put('/profile/goals-and-constraints', body: goalsBody);

    await _apiClient.patch(
      '/profile',
      body: {
        'weekly_training_days': submission.weeklyTrainingDays,
        // /me currently defines initialization as both experience and weekly
        // frequency being non-null. The four-question product flow does not ask
        // experience, so preserve an existing value or use an editable fallback.
        'experience_level': profile.experienceLevel ?? 'beginner',
        'expected_version': profile.version,
      },
    );
  }
}
