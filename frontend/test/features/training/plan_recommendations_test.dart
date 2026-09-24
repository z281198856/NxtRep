import 'package:flutter_test/flutter_test.dart';
import 'package:http/testing.dart';
import 'package:nxtrep/core/config/api_config.dart';
import 'package:nxtrep/core/network/api_client.dart';
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
