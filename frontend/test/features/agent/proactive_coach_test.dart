import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nxtrep/core/config/api_config.dart';
import 'package:nxtrep/core/network/api_client.dart';
import 'package:nxtrep/features/agent/data/proactive_repository.dart';
import 'package:nxtrep/features/agent/presentation/proactive_controller.dart';
import 'package:nxtrep/features/exercises/data/exercise_repository.dart';
import 'package:nxtrep/features/training/data/training_repository.dart';
import 'package:nxtrep/features/training/presentation/today_page.dart';
import 'package:nxtrep/features/training/presentation/training_controller.dart';

void main() {
  testWidgets(
    'opt-in daily coach shows a fact-based suggestion and opens plan',
    (tester) async {
      final requests = <String>[];
      var planOpened = false;
      var enabled = false;
      String? notificationCategory;
      final api = ApiClient(
        config: ApiConfig(
          baseUri: Uri.parse('https://api.example.test/api/v1'),
        ),
        accessTokenProvider: () => 'access',
        httpClient: MockClient((request) async {
          requests.add('${request.method} ${request.url.path}');
          final path = request.url.path;
          if (path == '/api/v1/calendar') return http.Response('[]', 200);
          if (path == '/api/v1/workouts/active') {
            return http.Response(
              jsonEncode({
                'error': {'code': 'WORKOUT_NOT_FOUND', 'message': 'none'},
              }),
              404,
            );
          }
          if (path == '/api/v1/notification-settings') {
            if (request.method == 'PATCH') {
              final body = jsonDecode(request.body) as Map<String, dynamic>;
              expect(body['expected_version'], 1);
              expect((body['categories'] as Map)['proactive_coach'], true);
              enabled = true;
            }
            return http.Response(
              jsonEncode({
                'enabled': enabled,
                'categories': enabled ? {'proactive_coach': true} : {},
                'frequency': enabled ? 'daily' : 'important_only',
                'quiet_hours': null,
                'version': enabled ? 2 : 1,
              }),
              200,
              headers: {'content-type': 'application/json; charset=utf-8'},
            );
          }
          if (path == '/api/v1/agent/proactive/review') {
            expect(enabled, true);
            return http.Response('[]', 200);
          }
          if (path == '/api/v1/notifications') {
            notificationCategory = request.url.queryParameters['category'];
            return http.Response(
              jsonEncode({
                'list': [
                  {
                    'id': 'notice-1',
                    'category': 'proactive_coach',
                    'title': '昨天日历中的训练尚未标记完成',
                    'body': '如果已经训练，请核对记录；否则可以查看日历并调整安排。',
                    'data': {'kind': 'missed_workout', 'route': 'plan'},
                    'read_at': null,
                    'created_at': '2026-09-25T08:00:00+08:00',
                  },
                ],
                'total': 1,
                'page': 1,
                'page_size': 20,
                'has_more': false,
              }),
              200,
              headers: {'content-type': 'application/json; charset=utf-8'},
            );
          }
          if (path == '/api/v1/notifications/notice-1/read') {
            return http.Response('{}', 200);
          }
          throw StateError('Unexpected request: ${request.method} $path');
        }),
      );
      final training = TrainingController(TrainingRepository(api));
      final proactive = ProactiveController(ProactiveRepository(api));
      addTearDown(() {
        training.dispose();
        proactive.dispose();
        api.close();
      });

      await tester.pumpWidget(
        MaterialApp(
          home: TodayPage(
            username: '测试用户',
            controller: training,
            proactiveController: proactive,
            exerciseRepository: ExerciseRepository(api),
            onOpenNutrition: () {},
            onOpenPlan: () => planOpened = true,
            onOpenProgress: () {},
            onOpenAgent: () {},
          ),
        ),
      );
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(
        find.text('主动教练'),
        250,
        scrollable: find.byType(Scrollable).first,
      );
      expect(proactive.enabled, false);
      await tester.tap(find.byType(Switch));
      await tester.pumpAndSettle();
      expect(proactive.enabled, true);
      expect(requests, contains('POST /api/v1/agent/proactive/review'));
      expect(proactive.errorMessage, isNull, reason: requests.join(', '));
      expect(notificationCategory, 'proactive_coach');
      expect(proactive.notices.length, 1);
      await tester.scrollUntilVisible(
        find.text('昨天日历中的训练尚未标记完成'),
        160,
        scrollable: find.byType(Scrollable).first,
      );
      expect(find.text('昨天日历中的训练尚未标记完成'), findsOneWidget);

      await tester.drag(find.byType(Scrollable).first, const Offset(0, -180));
      await tester.pumpAndSettle();
      await tester.tap(find.text('昨天日历中的训练尚未标记完成'));
      await tester.pumpAndSettle();
      expect(planOpened, true);
      expect(requests, contains('POST /api/v1/notifications/notice-1/read'));
      expect(proactive.notices, isEmpty);
    },
  );
}
