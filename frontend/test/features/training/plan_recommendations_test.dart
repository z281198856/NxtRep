import 'package:flutter_test/flutter_test.dart';
import 'package:http/testing.dart';
import 'package:nxtrep/core/config/api_config.dart';
import 'package:nxtrep/core/network/api_client.dart';
import 'package:nxtrep/features/profile/domain/profile_models.dart';
import 'package:nxtrep/features/training/data/training_repository.dart';
import 'package:nxtrep/features/training/domain/training_models.dart';
import 'package:nxtrep/features/training/presentation/plan_controller.dart';
import 'package:nxtrep/features/training/presentation/template_catalog_page.dart';

void main() {
  late ApiClient api;
  late PlanController controller;
  setUp(() {
    api = ApiClient(
      config: ApiConfig(baseUri: Uri.parse('https://api.example.test/api/v1')),
      accessTokenProvider: () => null,
      httpClient: MockClient(
        (_) async => throw StateError('Unexpected request'),
      ),
    );
    controller = PlanController(TrainingRepository(api));
  });
  tearDown(() {
    controller.dispose();
    api.close();
  });

  test('recommendations cover three goals and four equipment types', () {
    controller.templates = [
      const TrainingTemplate(
        id: 'mixed',
        name: '旧混合计划',
        goalTypes: ['muscle_gain'],
        daysPerWeek: 3,
        durationMinutes: 60,
        equipment: ['barbell', 'cable'],
      ),
      for (final gear in ['bodyweight', 'dumbbell', 'barbell', 'cable'])
        for (var days = 1; days <= 7; days++)
          for (final goal in ['muscle_gain', 'fat_loss_retain', 'strength'])
            TrainingTemplate(
              id: '$gear-$days-$goal',
              name: '$gear-$days-$goal',
              goalTypes: [goal],
              daysPerWeek: days,
              durationMinutes: 45,
              equipment: {gear, 'bodyweight'}.toList(),
            ),
    ];

    final shown = controller.recommendedTemplates;
    expect(shown, hasLength(12));
    expect(shown.take(3).map((item) => item.goalTypes.single), [
      'muscle_gain',
      'fat_loss_retain',
      'strength',
    ]);
    expect(
      shown.map((item) => item.id),
      containsAll([
        'bodyweight-3-muscle_gain',
        'dumbbell-3-muscle_gain',
        'barbell-3-muscle_gain',
        'cable-3-muscle_gain',
        'bodyweight-3-fat_loss_retain',
        'dumbbell-3-fat_loss_retain',
        'barbell-3-fat_loss_retain',
        'cable-3-fat_loss_retain',
        'bodyweight-3-strength',
        'dumbbell-3-strength',
        'barbell-3-strength',
        'cable-3-strength',
      ]),
    );
    expect(shown.any((item) => item.id == 'mixed'), isFalse);
  });

  test('older servers without equipment metadata still show a plan', () {
    controller.templates = [
      TrainingTemplate.fromJson({
        'id': 'legacy',
        'name': '三天全身训练',
        'goal_types': ['muscle_gain'],
        'days_per_week': 3,
        'duration_minutes': 60,
      }),
    ];
    expect(controller.recommendedTemplates.single.id, 'legacy');
  });

  test('strength and weekly frequency rank matching gym plans first', () {
    controller.recommendationProfile = _profile(days: 4, minutes: 45);
    controller.recommendationPreferences = _preferences(
      goal: 'strength',
      equipment: ['barbell', 'dumbbell', 'cable', 'rack'],
    );
    controller.templates = [
      _template('gain-4', 'muscle_gain', 'dumbbell', 4),
      _template('strength-3', 'strength', 'dumbbell', 3),
      _template('strength-4', 'strength', 'barbell', 4),
      _template('strength-5', 'strength', 'cable', 5),
    ];

    expect(controller.recommendedTemplates.map((item) => item.id), [
      'strength-4',
      'strength-3',
      'strength-5',
    ]);
    expect(controller.recommendationDescription, contains('每周 4 天'));
  });

  test('bodyweight preference does not recommend unavailable equipment', () {
    controller.recommendationProfile = _profile(days: 3);
    controller.recommendationPreferences = _preferences(
      goal: 'fat_loss_retain',
      equipment: ['bodyweight'],
    );
    controller.templates = [
      _template('cable-fat-loss', 'fat_loss_retain', 'cable', 3),
      _template('bodyweight-fat-loss', 'fat_loss_retain', 'bodyweight', 3),
      _template('bodyweight-gain', 'muscle_gain', 'bodyweight', 3),
    ];

    expect(controller.recommendedTemplates.map((item) => item.id), [
      'bodyweight-fat-loss',
    ]);
  });

  test('unavailable equipment is never recommended as a fallback', () {
    controller.recommendationPreferences = _preferences(
      goal: 'strength',
      equipment: ['bodyweight'],
    );
    controller.templates = [
      _template('cable-strength', 'strength', 'cable', 3),
    ];

    expect(controller.recommendedTemplates, isEmpty);
  });

  test('catalog filters by goal, equipment and frequency', () {
    controller.templates = [
      const TrainingTemplate(
        id: 'dumbbell-strength',
        name: '哑铃力量',
        goalTypes: ['strength'],
        daysPerWeek: 4,
        durationMinutes: 40,
        equipment: ['dumbbell', 'bodyweight'],
      ),
      const TrainingTemplate(
        id: 'mixed-strength',
        name: '混合力量',
        goalTypes: ['strength'],
        daysPerWeek: 4,
        durationMinutes: 40,
        equipment: ['dumbbell', 'barbell'],
      ),
      const TrainingTemplate(
        id: 'dumbbell-muscle',
        name: '哑铃增肌',
        goalTypes: ['muscle_gain'],
        daysPerWeek: 3,
        durationMinutes: 40,
        equipment: ['dumbbell', 'bodyweight'],
      ),
    ];
    expect(filterTrainingTemplates(controller.templates), hasLength(3));
    expect(
      filterTrainingTemplates(
        controller.templates,
        goal: 'strength',
        equipment: 'dumbbell',
        days: 4,
      ).single.id,
      'dumbbell-strength',
    );
  });
}

UserProfile _profile({required int days, int? minutes}) => UserProfile(
  displayName: null,
  sex: 'unspecified',
  birthDate: null,
  heightCm: null,
  experienceLevel: 'beginner',
  weeklyTrainingDays: days,
  sessionDurationMinutes: minutes,
  timezone: 'Asia/Shanghai',
  version: 1,
);

TrainingPreferences _preferences({
  required String goal,
  required List<String> equipment,
}) => TrainingPreferences(
  version: 1,
  goalType: goal,
  targetDate: null,
  targetWeightKg: null,
  equipment: equipment,
  preferredExercises: const [],
  dislikedExercises: const [],
  painOrInjuries: const [],
  allergies: const [],
  dietaryPreferences: const [],
  warnings: const [],
);

TrainingTemplate _template(String id, String goal, String gear, int days) =>
    TrainingTemplate(
      id: id,
      name: id,
      goalTypes: [goal],
      daysPerWeek: days,
      durationMinutes: 45,
      equipment: [gear],
    );
