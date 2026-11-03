import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nxtrep/core/config/api_config.dart';
import 'package:nxtrep/core/network/api_client.dart';
import 'package:nxtrep/core/storage/refresh_token_store.dart';
import 'package:nxtrep/core/widgets/day_selector.dart';
import 'package:nxtrep/features/auth/data/auth_repository.dart';
import 'package:nxtrep/features/auth/domain/session_tokens.dart';
import 'package:nxtrep/features/auth/presentation/session_controller.dart';
import 'package:nxtrep/features/nutrition/data/nutrition_repository.dart';
import 'package:nxtrep/features/nutrition/presentation/nutrition_controller.dart';
import 'package:nxtrep/features/nutrition/presentation/nutrition_page.dart';
import 'package:nxtrep/features/onboarding/data/onboarding_repository.dart';
import 'package:nxtrep/features/shell/presentation/home_shell.dart';

http.Response _json(Object value, [int status = 200]) => http.Response.bytes(
  utf8.encode(jsonEncode(value)),
  status,
  headers: {'content-type': 'application/json'},
);

Map<String, Object> _totals([int kcal = 500]) => {
  'kcal': kcal,
  'protein_g': 30,
  'carbs_g': 60,
  'fat_g': 15,
};

Map<String, Object> _meal(String date) => {
  'id': 'meal-$date',
  'meal_type': 'lunch',
  'eaten_at': '${date}T04:00:00Z',
  'items': [
    {'name': '午饭-$date', 'amount_g': 200},
  ],
  'totals': _totals(),
  'version': 1,
};

http.Response _nutritionResponse(http.Request request) {
  final date = request.url.queryParameters['date'] ?? '2024-02-29';
  if (request.url.path.endsWith('/daily-summary')) {
    return _json({
      'date': date,
      'consumed': _totals(),
      'record_completeness': 0.33,
    });
  }
  if (request.url.path.endsWith('/entries')) return _json([_meal(date)]);
  if (request.url.path.endsWith('/weekly-summary')) {
    return _json({
      'start_date': request.url.queryParameters['start_date']!,
      'end_date': request.url.queryParameters['start_date']!,
      'daily_average': _totals(),
      'total_entries': 1,
      'recorded_days': 1,
      'flexible_meals': 0,
      'record_completeness': 0.14,
    });
  }
  if (request.url.path.endsWith('/foods/frequent')) return _json([]);
  throw StateError('Unexpected request ${request.method} ${request.url}');
}

ApiClient _api(Future<http.Response> Function(http.Request) handler) =>
    ApiClient(
      config: ApiConfig(baseUri: Uri.parse('https://example.test/api/v1')),
      accessTokenProvider: () => 'test',
      httpClient: MockClient(handler),
    );

class _TokenStore implements RefreshTokenStore {
  @override
  Future<void> delete() async {}
  @override
  Future<String?> read() async => null;
  @override
  Future<void> write(String token) async {}
}

void main() {
  test(
    'date queries retain the selected day on refresh and use its week',
    () async {
      final requests = <http.Request>[];
      final api = _api((request) async {
        requests.add(request);
        return _nutritionResponse(request);
      });
      final controller = NutritionController(NutritionRepository(api));
      addTearDown(controller.dispose);
      addTearDown(api.close);
      for (final date in [DateTime(2024, 2, 29), DateTime(2025, 1, 1)]) {
        await controller.selectDate(date);
        await controller.refresh();
        expect(controller.summary!.date, date);
      }
      final dayQueries = requests.where((r) => r.url.path.endsWith('/entries'));
      expect(dayQueries.map((r) => r.url.queryParameters['date']), [
        '2024-02-29',
        '2024-02-29',
        '2025-01-01',
        '2025-01-01',
      ]);
      expect(
        requests
            .where((r) => r.url.path.endsWith('/weekly-summary'))
            .last
            .url
            .queryParameters['start_date'],
        '2024-12-30',
      );
      expect(requests.every((request) => request.method == 'GET'), isTrue);
    },
  );

  for (final oldRequestFails in [false, true]) {
    test(
      'older date ${oldRequestFails ? 'failure' : 'response'} cannot replace newer day',
      () async {
        final older = Completer<http.Response>();
        final api = _api((request) async {
          if (request.url.path.endsWith('/daily-summary') &&
              request.url.queryParameters['date'] == '2024-02-29') {
            return older.future;
          }
          return _nutritionResponse(request);
        });
        final controller = NutritionController(NutritionRepository(api));
        addTearDown(controller.dispose);
        addTearDown(api.close);
        final pending = controller.selectDate(DateTime(2024, 2, 29));
        await controller.selectDate(DateTime(2024, 3, 1));
        older.complete(
          oldRequestFails
              ? _json({
                  'error': {
                    'code': 'DEPENDENCY_UNAVAILABLE',
                    'message': '旧请求失败',
                  },
                }, 503)
              : _json({
                  'date': '2024-02-29',
                  'consumed': _totals(999),
                  'record_completeness': 1,
                }),
        );
        await pending;
        expect(controller.summary!.date, DateTime(2024, 3, 1));
        expect(controller.entries.single.id, 'meal-2024-03-01');
        expect(controller.errorMessage, isNull);
        expect(controller.loading, isFalse);
      },
    );
  }

  testWidgets(
    'changing day clears stale meals; failure offers retry instead of empty state',
    (tester) async {
      tester.view.physicalSize = const Size(450, 1100);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      var fail = false;
      var empty = false;
      final api = _api((request) async {
        if (request.url.path.endsWith('/entries') && fail) {
          return _json({
            'error': {
              'code': 'DEPENDENCY_UNAVAILABLE',
              'message': '饮食记录暂时无法读取',
            },
          }, 503);
        }
        if (request.url.path.endsWith('/entries') && empty) return _json([]);
        return _nutritionResponse(request);
      });
      final controller = NutritionController(NutritionRepository(api));
      addTearDown(controller.dispose);
      addTearDown(api.close);
      await controller.selectDate(DateTime(2024, 2, 29));
      await tester.pumpWidget(
        MaterialApp(home: NutritionPage(controller: controller)),
      );
      await tester.pumpAndSettle();
      expect(find.text('午饭-2024-02-29'), findsOneWidget);
      expect(find.textContaining('当天摄入'), findsOneWidget);
      expect(find.text('添加食品'), findsNothing);
      expect(find.text('补记食品'), findsOneWidget);
      expect(
        find.byKey(const ValueKey('nutrition-quick-entries')),
        findsOneWidget,
      );
      await tester.drag(find.byType(ListView), const Offset(0, -500));
      await tester.pumpAndSettle();
      fail = true;
      // Also covers a date changed by the other tab while this list was scrolled.
      await controller.selectDate(DateTime(2024, 3, 1));
      await tester.pumpAndSettle();
      expect(
        find.byKey(const ValueKey('day-selector-calendar')).hitTestable(),
        findsOneWidget,
      );
      expect(find.text('午饭-2024-02-29'), findsNothing);
      expect(find.text('饮食记录暂时无法读取'), findsOneWidget);
      expect(find.text('这一天没有已保存的饮食记录'), findsNothing);
      fail = false;
      empty = true;
      await tester.tap(find.text('重新加载'));
      await tester.pumpAndSettle();
      expect(find.text('这一天没有已保存的饮食记录'), findsOneWidget);
      expect(find.text('饮食记录暂时无法读取'), findsNothing);
      await tester.tap(find.text('返回今天'));
      await tester.pumpAndSettle();
      expect(
        DateUtils.isSameDay(controller.selectedDate, DateTime.now()),
        isTrue,
      );
      expect(find.text('添加食品'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'shared shell date flows from plan to meals and back across a month boundary',
    (tester) async {
      tester.view.physicalSize = const Size(450, 1000);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final requests = <http.Request>[];
      final api = _api((request) async {
        requests.add(request);
        final path = request.url.path;
        if (path.contains('/nutrition/') || path.endsWith('/foods/frequent')) {
          return _nutritionResponse(request);
        }
        if (path == '/api/v1/calendar') {
          return _json([
            {
              'id': 'event-leap',
              'scheduled_date': '2024-02-29',
              'status': 'planned',
              'title': '历史胸部训练',
              'estimated_minutes': 45,
            },
          ]);
        }
        if (path == '/api/v1/calendar/events/event-leap') {
          return _json({
            'id': 'event-leap',
            'scheduled_date': '2024-02-29',
            'status': 'planned',
            'title': '历史胸部训练',
            'estimated_minutes': 45,
            'content_snapshot': {
              'exercises': [
                {
                  'exercise_name': '历史杠铃卧推',
                  'target_sets': 4,
                  'rep_min': 8,
                  'rep_max': 8,
                  'target_load_kg': 55,
                },
              ],
            },
          });
        }
        if (path.endsWith('/training/templates')) return _json([]);
        if (path.endsWith('/workouts')) {
          return _json({'list': [], 'total': 0, 'has_more': false});
        }
        if (path.endsWith('/training/plans/active')) {
          return _json({
            'error': {'code': 'ACTIVE_PLAN_NOT_FOUND', 'message': '无当前计划'},
          }, 404);
        }
        // Unrelated tabs deliberately have no backend fixture in this navigation test.
        return _json({
          'error': {'code': 'UNAVAILABLE', 'message': '此测试未加载此页面'},
        }, 503);
      });
      addTearDown(api.close);
      final session = SessionController(
        authRepository: AuthRepository(
          apiClient: api,
          tokens: SessionTokens(_TokenStore()),
        ),
        onboardingRepository: OnboardingRepository(api),
      );
      addTearDown(session.dispose);
      await tester.pumpWidget(
        MaterialApp(home: HomeShell(controller: session)),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.text('饮食').last);
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const ValueKey('day-selector-calendar')));
      await tester.pumpAndSettle();
      await tester.tap(find.byTooltip('Switch to input'));
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextField).last, '02/29/2024');
      await tester.tap(find.text('确定'));
      await tester.pumpAndSettle();
      expect(
        tester.widget<DaySelector>(find.byType(DaySelector)).date,
        DateTime(2024, 2, 29),
      );
      expect(find.text('午饭-2024-02-29'), findsOneWidget);
      await tester.tap(find.text('查看当天训练'));
      await tester.pumpAndSettle();
      expect(find.text('2024 年 2 月'), findsOneWidget);
      await tester.ensureVisible(find.text('历史胸部训练'));
      await tester.tap(find.text('历史胸部训练'));
      await tester.pumpAndSettle();
      expect(find.text('历史杠铃卧推'), findsOneWidget);
      expect(find.textContaining('4 组 × 8 次'), findsOneWidget);
      expect(find.textContaining('55.0 kg'), findsOneWidget);
      await tester.pageBack();
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.text('查看当天饮食'));
      await tester.tap(find.text('查看当天饮食'));
      await tester.pumpAndSettle();
      expect(find.text('午饭-2024-02-29'), findsOneWidget);
      await tester.tap(find.byTooltip('后一天'));
      await tester.pumpAndSettle();
      expect(find.text('午饭-2024-03-01'), findsOneWidget);
      await tester.tap(find.text('查看当天训练'));
      await tester.pumpAndSettle();
      expect(find.text('2024 年 3 月'), findsOneWidget);
      await tester.ensureVisible(
        find.byKey(const ValueKey('calendar-day-2024-3-2')),
      );
      await tester.tap(find.byKey(const ValueKey('calendar-day-2024-3-2')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('饮食').last);
      await tester.pumpAndSettle();
      expect(find.text('午饭-2024-03-02'), findsOneWidget);
      expect(requests.every((request) => request.method == 'GET'), isTrue);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pumpAndSettle();
    },
  );
}
