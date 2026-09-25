import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nxtrep/core/config/api_config.dart';
import 'package:nxtrep/core/network/api_client.dart';
import 'package:nxtrep/features/agent/data/proactive_repository.dart';
import 'package:nxtrep/features/agent/domain/proactive_models.dart';
import 'package:nxtrep/features/agent/presentation/proactive_controller.dart';
import 'package:nxtrep/features/exercises/data/exercise_repository.dart';
import 'package:nxtrep/features/training/data/training_repository.dart';
import 'package:nxtrep/features/training/presentation/today_page.dart';
import 'package:nxtrep/features/training/presentation/training_controller.dart';

void main() {
  test('important-only scope filters routine nutrition notices', () async {
    var frequency = 'daily';
    var version = 2;
    final api = ApiClient(
      config: ApiConfig(baseUri: Uri.parse('https://api.example.test/api/v1')),
      accessTokenProvider: () => 'access',
      httpClient: MockClient((request) async {
        final path = request.url.path;
        if (path == '/api/v1/notification-settings') {
          if (request.method == 'PATCH') {
            final body = jsonDecode(request.body) as Map<String, dynamic>;
            expect(body['expected_version'], version);
            frequency = body['frequency'] as String;
            version += 1;
          }
          return http.Response(
            jsonEncode({
              'enabled': true,
              'categories': {'proactive_coach': true},
              'frequency': frequency,
              'version': version,
            }),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }
        if (path == '/api/v1/agent/proactive/review') {
          return http.Response('[]', 200);
        }
        if (path == '/api/v1/notifications') {
          return http.Response(
            jsonEncode({
              'list': [
                {
                  'id': 'training',
                  'category': 'proactive_coach',
                  'title': '训练安排',
                  'body': '查看日历',
                  'data': {'kind': 'missed_workout', 'route': 'plan'},
                },
                {
                  'id': 'nutrition',
                  'category': 'proactive_coach',
                  'title': '饮食记录',
                  'body': '可补记',
                  'data': {'kind': 'nutrition_log_gap', 'route': 'nutrition'},
                },
              ],
            }),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }
        throw StateError('Unexpected request: ${request.method} $path');
      }),
    );
    final controller = ProactiveController(ProactiveRepository(api));
    addTearDown(() {
      controller.dispose();
      api.close();
    });

    await controller.refresh();
    expect(controller.notices.map((item) => item.kind).toSet(), {
      'missed_workout',
      'nutrition_log_gap',
    });
    await controller.setFrequency('important_only');
    expect(controller.settings?.frequency, 'important_only');
    expect(controller.notices.map((item) => item.kind), ['missed_workout']);
  });

  testWidgets(
    'opt-in daily coach shows a fact-based suggestion and opens plan',
    (tester) async {
      final requests = <String>[];
      var planOpened = false;
      var discussed = false;
      var notificationsEnabled = false;
      var coachCategoryEnabled = false;
      var version = 1;
      var frequency = 'important_only';
      var preservedScopeOnReenable = false;
      String? feedbackRating;
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
              expect(body['expected_version'], version);
              version += 1;
              if (body['enabled'] case final bool value) {
                notificationsEnabled = value;
              }
              if (body['categories'] case final Map categories) {
                coachCategoryEnabled = categories['proactive_coach'] == true;
                if (coachCategoryEnabled && version > 3) {
                  preservedScopeOnReenable = !body.containsKey('frequency');
                }
              }
              if (body['frequency'] case final String selected) {
                frequency = selected;
              }
            }
            return http.Response(
              jsonEncode({
                'enabled': notificationsEnabled,
                'categories': {'proactive_coach': coachCategoryEnabled},
                'frequency': frequency,
                'quiet_hours': null,
                'version': version,
              }),
              200,
              headers: {'content-type': 'application/json; charset=utf-8'},
            );
          }
          if (path == '/api/v1/agent/proactive/review') {
            expect(notificationsEnabled && coachCategoryEnabled, true);
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
                    'data': {
                      'kind': 'missed_workout',
                      'route': 'plan',
                      if (feedbackRating != null)
                        'feedback': {'rating': feedbackRating},
                    },
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
          if (path == '/api/v1/agent/proactive/notices/notice-1/feedback') {
            expect(request.method, 'PUT');
            feedbackRating =
                (jsonDecode(request.body) as Map<String, dynamic>)['rating']
                    as String;
            return http.Response(
              jsonEncode({
                'id': 'notice-1',
                'title': '昨天日历中的训练尚未标记完成',
                'body': '如果已经训练，请核对记录；否则可以查看日历并调整安排。',
                'data': {
                  'kind': 'missed_workout',
                  'route': 'plan',
                  'feedback': {'rating': feedbackRating},
                },
              }),
              200,
              headers: {'content-type': 'application/json; charset=utf-8'},
            );
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
            onDiscussNotice: (_) => discussed = true,
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
      expect(proactive.settings?.frequency, 'daily');
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

      await tester.scrollUntilVisible(
        find.text('有帮助'),
        160,
        scrollable: find.byType(Scrollable).first,
      );
      await tester.drag(find.byType(Scrollable).first, const Offset(0, -180));
      await tester.pumpAndSettle();
      await tester.tap(find.text('有帮助'));
      await tester.pumpAndSettle();
      expect(feedbackRating, 'helpful');
      expect(proactive.notices.single.feedbackRating, 'helpful');
      await tester.tap(find.text('和教练讨论'));
      await tester.pumpAndSettle();
      expect(discussed, true);

      await tester.drag(find.byType(Scrollable).first, const Offset(0, -180));
      await tester.pumpAndSettle();
      await tester.tap(find.text('昨天日历中的训练尚未标记完成'));
      await tester.pumpAndSettle();
      expect(planOpened, true);
      expect(requests, contains('POST /api/v1/notifications/notice-1/read'));
      expect(proactive.notices, isEmpty);

      await tester.ensureVisible(find.byType(DropdownButton<String>));
      await tester.tap(find.byType(DropdownButton<String>));
      await tester.pumpAndSettle();
      await tester.tap(find.text('仅训练与恢复').last);
      await tester.pumpAndSettle();
      expect(proactive.settings?.frequency, 'important_only');
      expect(frequency, 'important_only');
      await tester.ensureVisible(find.byType(Switch));
      await tester.tap(find.byType(Switch));
      await tester.pumpAndSettle();
      expect(proactive.enabled, false);
      await tester.tap(find.byType(Switch));
      await tester.pumpAndSettle();
      expect(proactive.enabled, true);
      expect(proactive.settings?.frequency, 'important_only');
      expect(preservedScopeOnReenable, true);

      proactive.notices = const [
        ProactiveNotice(
          id: 'nutrition-notice',
          title: '昨天没有饮食记录',
          body: '没有记录不代表没有进食。',
          route: 'nutrition',
          kind: 'nutrition_log_gap',
          feedbackRating: 'not_relevant',
        ),
      ];
      proactive.notifyListeners();
      await tester.pumpAndSettle();
      expect(find.text('这类饮食记录提醒会暂停 7 天；改为“有帮助”可恢复。'), findsOneWidget);
    },
  );
}
