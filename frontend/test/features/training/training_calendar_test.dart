import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nxtrep/core/config/api_config.dart';
import 'package:nxtrep/core/network/api_client.dart';
import 'package:nxtrep/core/theme/app_theme.dart';
import 'package:nxtrep/features/training/data/training_repository.dart';
import 'package:nxtrep/features/training/domain/training_models.dart';
import 'package:nxtrep/features/training/presentation/plan_controller.dart';
import 'package:nxtrep/features/training/presentation/plan_page.dart';
import 'package:nxtrep/features/training/presentation/training_calendar.dart';

http.Response _json(Object value, [int status = 200]) => http.Response(
  jsonEncode(value),
  status,
  headers: {'content-type': 'application/json; charset=utf-8'},
);

ApiClient _api(Future<http.Response> Function(http.Request) handler) =>
    ApiClient(
      config: ApiConfig(baseUri: Uri.parse('https://example.test/api/v1')),
      accessTokenProvider: () => 'test',
      httpClient: MockClient(handler),
    );

void main() {
  testWidgets('month grid includes leap day and selects the actual date', (
    tester,
  ) async {
    DateTime? selected;
    DateTime? navigated;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: TrainingMonthCalendar(
            month: DateTime(2024, 2),
            selectedDate: DateTime(2024, 2, 1),
            loading: false,
            events: [
              CalendarEvent(
                id: 'planned',
                scheduledDate: DateTime(2024, 2, 1),
                status: 'planned',
                title: '待训练',
                estimatedMinutes: 30,
              ),
              CalendarEvent(
                id: 'missed',
                scheduledDate: DateTime(2024, 2, 2),
                status: 'missed',
                title: '未完成',
                estimatedMinutes: 30,
              ),
              CalendarEvent(
                id: 'leap',
                scheduledDate: DateTime(2024, 2, 29),
                status: 'completed',
                title: '训练',
                estimatedMinutes: 30,
              ),
            ],
            onSelected: (date) => selected = date,
            onMonthChanged: (date) => navigated = date,
          ),
        ),
      ),
    );
    expect(find.text('2024 年 2 月'), findsOneWidget);
    for (final entry in {
      1: AppColors.primary,
      2: AppColors.amber,
      29: AppColors.mint,
    }.entries) {
      final marker = tester.widget<Container>(
        find.byKey(ValueKey('calendar-marker-2024-2-${entry.key}')),
      );
      expect((marker.decoration as BoxDecoration).color, entry.value);
    }
    expect(find.byKey(const ValueKey('calendar-day-2024-2-30')), findsNothing);
    await tester.tap(find.byKey(const ValueKey('calendar-day-2024-2-29')));
    expect(selected, DateTime(2024, 2, 29));
    await tester.tap(find.byTooltip('上个月'));
    expect(navigated, DateTime(2024, 1));
    await tester.tap(find.text('今天'));
    expect(navigated, DateUtils.dateOnly(DateTime.now()));
    expect(tester.takeException(), isNull);
  });

  test(
    'month requests cover the full month, cross year and stay on refresh',
    () async {
      final requests = <Uri>[];
      final api = _api((request) async {
        if (request.url.path.endsWith('/calendar')) {
          requests.add(request.url);
          return _json([]);
        }
        if (request.url.path.endsWith('/active')) {
          return _json({
            'error': {'code': 'ACTIVE_PLAN_NOT_FOUND', 'message': '暂无计划'},
          }, 404);
        }
        if (request.url.path.endsWith('/templates')) return _json([]);
        if (request.url.path.endsWith('/workouts')) {
          return _json({
            'list': [],
            'page': 1,
            'page_size': 20,
            'total': 0,
            'has_more': false,
          });
        }
        throw StateError('Unexpected request');
      });
      final controller = PlanController(TrainingRepository(api));
      addTearDown(controller.dispose);
      addTearDown(api.close);
      await controller.showCalendarMonth(DateTime(2024, 2));
      expect(requests.last.queryParameters, {
        'start_date': '2024-02-01',
        'end_date': '2024-02-29',
      });
      await controller.showCalendarMonth(DateTime(2024, 12));
      await controller.showCalendarMonth(DateTime(2025, 1));
      await controller.refresh();
      expect(controller.errorMessage, isNull);
      expect(requests.last.queryParameters, {
        'start_date': '2025-01-01',
        'end_date': '2025-01-31',
      });
      expect(controller.calendarMonth, DateTime(2025, 1));
    },
  );

  test(
    'slow older month response cannot overwrite a newly selected month',
    () async {
      final older = Completer<http.Response>();
      final api = _api((request) async {
        if (request.url.queryParameters['start_date'] == '2024-02-01') {
          return older.future;
        }
        return _json([
          {
            'id': 'march',
            'scheduled_date': '2024-03-01',
            'status': 'planned',
            'title': '三月训练',
            'estimated_minutes': 30,
          },
        ]);
      });
      final controller = PlanController(TrainingRepository(api));
      addTearDown(controller.dispose);
      addTearDown(api.close);
      final pending = controller.showCalendarMonth(DateTime(2024, 2));
      await controller.showCalendarMonth(DateTime(2024, 3));
      older.complete(_json([]));
      await pending;
      expect(controller.calendarMonth, DateTime(2024, 3));
      expect(controller.events.single.id, 'march');
      expect(controller.calendarLoading, isFalse);
    },
  );

  testWidgets(
    'calendar is above plan browsing and shows every selected-day event',
    (tester) async {
      final api = _api((request) async {
        if (request.url.path.endsWith('/calendar')) {
          return _json([
            for (final title in ['上午力量', '晚间恢复'])
              {
                'id': title,
                'scheduled_date': '2024-02-29',
                'status': 'planned',
                'title': title,
                'estimated_minutes': 30,
              },
          ]);
        }
        if (request.url.path.endsWith('/active')) {
          return _json({
            'error': {'code': 'ACTIVE_PLAN_NOT_FOUND', 'message': '暂无计划'},
          }, 404);
        }
        if (request.url.path.endsWith('/templates')) return _json([]);
        return _json({
          'list': [],
          'page': 1,
          'page_size': 20,
          'total': 0,
          'has_more': false,
        });
      });
      final controller = PlanController(TrainingRepository(api))
        ..calendarMonth = DateTime(2024, 2);
      addTearDown(controller.dispose);
      addTearDown(api.close);
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
      expect(controller.errorMessage, isNull);
      expect(tester.getTopLeft(find.text('训练日历')).dy, lessThan(200));
      await tester.ensureVisible(
        find.byKey(const ValueKey('calendar-day-2024-2-29')),
      );
      await tester.tap(find.byKey(const ValueKey('calendar-day-2024-2-29')));
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.text('晚间恢复'));
      expect(find.text('上午力量'), findsOneWidget);
      expect(find.text('晚间恢复'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );
}
