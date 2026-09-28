import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nxtrep/core/config/api_config.dart';
import 'package:nxtrep/core/network/api_client.dart';
import 'package:nxtrep/features/training/data/training_repository.dart';
import 'package:nxtrep/features/training/presentation/plan_controller.dart';
import 'package:nxtrep/features/training/presentation/plan_page.dart';

void main() {
  testWidgets('active plan opens full day and exercise details', (
    tester,
  ) async {
    final api = ApiClient(
      config: ApiConfig(baseUri: Uri.parse('https://api.example.test/api/v1')),
      accessTokenProvider: () => 'access',
      httpClient: MockClient((request) async {
        final body = switch (request.url.path) {
          '/api/v1/training/plans/active' => {
            'id': 'active-1',
            'plan_id': 'plan-1',
            'name': '我的三日力量计划',
            'version': 1,
            'weekly_frequency': 3,
            'days': [
              {
                'id': 'day-1',
                'day_index': 1,
                'name': '全身 A',
                'estimated_minutes': 45,
                'exercises': [
                  {
                    'exercise_id': 'exercise-1',
                    'exercise_name': '哑铃卧推',
                    'target_sets': 3,
                    'rep_min': 8,
                    'rep_max': 10,
                    'target_load_kg': '12',
                    'target_rir': 2,
                    'rest_seconds': 90,
                  },
                ],
              },
            ],
          },
          '/api/v1/calendar' || '/api/v1/training/templates' => [],
          '/api/v1/workouts' => {'list': [], 'total': 0, 'has_more': false},
          _ => throw StateError('Unexpected ${request.url.path}'),
        };
        return http.Response(
          jsonEncode(body),
          200,
          headers: {'content-type': 'application/json; charset=utf-8'},
        );
      }),
    );
    final controller = PlanController(TrainingRepository(api));
    addTearDown(() {
      controller.dispose();
      api.close();
    });

    await tester.pumpWidget(
      MaterialApp(
        home: PlanPage(
          controller: controller,
          onAskCoach: (_) async {},
          onOpenExerciseLibrary: () {},
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('我的三日力量计划'), findsOneWidget);
    await tester.tap(find.text('查看完整计划'));
    await tester.pumpAndSettle();

    expect(find.text('当前训练计划'), findsOneWidget);
    expect(find.text('第 1 天 · 全身 A'), findsOneWidget);
    expect(find.text('哑铃卧推'), findsOneWidget);
    expect(find.textContaining('3 组 × 8–10 次'), findsOneWidget);
    expect(find.textContaining('每组做完还能再做约 2 次'), findsOneWidget);
    expect(find.textContaining('组间休息 90 秒'), findsOneWidget);
    expect(find.textContaining('RIR'), findsNothing);
    expect(tester.takeException(), isNull);
  });
}
