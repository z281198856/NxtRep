import 'package:flutter_test/flutter_test.dart';
import 'package:http/testing.dart';
import 'package:nxtrep/core/config/api_config.dart';
import 'package:nxtrep/core/network/api_client.dart';
import 'package:nxtrep/features/training/data/training_repository.dart';
import 'package:nxtrep/features/training/domain/training_models.dart';
import 'package:nxtrep/features/training/presentation/plan_controller.dart';

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

  test(
    'expanded catalog keeps recommendations bounded and equipment-specific',
    () {
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
            for (final goal in ['muscle_gain', 'maintain', 'strength'])
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
      expect(shown, hasLength(4));
      expect(
        shown.map((item) => item.id),
        containsAll([
          'bodyweight-3-muscle_gain',
          'dumbbell-3-muscle_gain',
          'barbell-3-muscle_gain',
          'cable-3-muscle_gain',
        ]),
      );
      expect(shown.any((item) => item.id == 'mixed'), isFalse);
    },
  );

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
}
