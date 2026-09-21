import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:nxtrep/features/profile/data/profile_repository.dart';
import 'package:nxtrep/features/profile/domain/profile_models.dart';
import 'package:nxtrep/features/profile/presentation/profile_controller.dart';
import 'package:nxtrep/features/profile/presentation/profile_page.dart';

void main() {
  testWidgets('profile hub opens the two supported training modes', (
    tester,
  ) async {
    final controller = ProfileController(_FakeProfileDataSource());
    addTearDown(controller.dispose);

    await tester.pumpWidget(
      MaterialApp(
        home: ProfilePage(
          controller: controller,
          username: 'tester',
          loggingOut: false,
          onLogout: () async {},
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('个人资料'), findsOneWidget);
    expect(find.text('应用与隐私'), findsOneWidget);
    await tester.tap(find.text('训练偏好'));
    await tester.pumpAndSettle();

    expect(find.text('徒手训练'), findsOneWidget);
    expect(find.text('健身房器械训练'), findsOneWidget);
    expect(find.text('徒手'), findsNothing);
    expect(find.text('哑铃'), findsNothing);
    expect(find.text('杠铃'), findsNothing);
    expect(find.text('绳索器械'), findsNothing);
    expect(find.text('深蹲架'), findsNothing);
  });
}

class _FakeProfileDataSource implements ProfileDataSource {
  @override
  Future<UserProfile> getProfile() async => const UserProfile(
    displayName: '小齐',
    sex: 'male',
    birthDate: null,
    heightCm: 178,
    experienceLevel: 'beginner',
    weeklyTrainingDays: 3,
    sessionDurationMinutes: 60,
    timezone: 'Asia/Shanghai',
    version: 1,
  );

  @override
  Future<TrainingPreferences> getTrainingPreferences() async =>
      const TrainingPreferences(
        version: 1,
        goalType: 'muscle_gain',
        targetDate: null,
        targetWeightKg: null,
        equipment: ['bodyweight'],
        preferredExercises: [],
        dislikedExercises: [],
        painOrInjuries: [],
        allergies: [],
        dietaryPreferences: [],
        warnings: [],
      );

  @override
  Future<AppSettings> getSettings() async => const AppSettings(
    unitSystem: 'metric',
    timezone: 'Asia/Shanghai',
    privacyMode: 'private',
    shareAnonymousAnalytics: false,
    version: 1,
  );

  @override
  Future<UserProfile> updatePersonalProfile(
    UserProfile current,
    PersonalProfileInput input,
  ) async => current;

  @override
  Future<({UserProfile profile, TrainingPreferences preferences})>
  updateTrainingPreferences(
    UserProfile profile,
    TrainingPreferences current,
    TrainingPreferencesInput input,
  ) async => (profile: profile, preferences: current);

  @override
  Future<AppSettings> updateSettings(
    AppSettings current,
    AppSettingsInput input,
  ) async => current;
}
