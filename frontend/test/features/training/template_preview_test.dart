import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nxtrep/core/config/api_config.dart';
import 'package:nxtrep/core/network/api_client.dart';
import 'package:nxtrep/features/training/data/training_repository.dart';
import 'package:nxtrep/features/training/domain/training_models.dart';
import 'package:nxtrep/features/training/presentation/plan_controller.dart';
import 'package:nxtrep/features/training/presentation/template_catalog_page.dart';

void main() {
  testWidgets(
    'template preview shows day and exercise details before activation',
    (tester) async {
      final requests = <String>[];
      final api = ApiClient(
        config: ApiConfig(
          baseUri: Uri.parse('https://api.example.test/api/v1'),
        ),
        accessTokenProvider: () => 'access',
        httpClient: MockClient((request) async {
          requests.add('${request.method} ${request.url.path}');
          return http.Response(
            jsonEncode({
              'id': 'template-1',
              'name': '哑铃 · 3 天力量基础',
              'goal_types': ['strength'],
              'days_per_week': 3,
              'duration_minutes': 40,
              'equipment': ['dumbbell', 'bodyweight'],
              'days': [
                {
                  'id': 'day-1',
                  'day_index': 1,
                  'name': '哑铃 · 全身 A',
                  'estimated_minutes': 40,
                  'exercises': [
                    {
                      'exercise_id': 'exercise-1',
                      'exercise_name': '哑铃地板卧推',
                      'target_sets': 3,
                      'rep_min': 5,
                      'rep_max': 8,
                      'target_rir': 3,
                    },
                  ],
                },
              ],
            }),
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
          home: TemplateDetailPage(
            controller: controller,
            template: const TrainingTemplate(
              id: 'template-1',
              name: '哑铃 · 3 天力量基础',
              goalTypes: ['strength'],
              daysPerWeek: 3,
              durationMinutes: 40,
              equipment: ['dumbbell', 'bodyweight'],
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();

      expect(find.textContaining('第 1 天'), findsOneWidget);
      expect(find.textContaining('哑铃地板卧推'), findsOneWidget);
      expect(find.text('启用这套计划'), findsOneWidget);
      expect(requests, ['GET /api/v1/training/templates/template-1']);
    },
  );
}
