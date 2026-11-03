import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nxtrep/core/config/api_config.dart';
import 'package:nxtrep/core/network/api_client.dart';
import 'package:nxtrep/features/training/data/training_repository.dart';
import 'package:nxtrep/features/training/presentation/calendar_event_detail_page.dart';
import 'package:nxtrep/features/training/presentation/plan_controller.dart';

void main() {
  testWidgets(
    'calendar detail retries a failed read and explicitly reports missing snapshot',
    (tester) async {
      var requests = 0;
      final api = ApiClient(
        config: ApiConfig(baseUri: Uri.parse('https://example.test/api/v1')),
        accessTokenProvider: () => 'test',
        httpClient: MockClient((request) async {
          expect(request.method, 'GET');
          expect(request.url.path, '/api/v1/calendar/events/old-event');
          requests++;
          final body = requests == 1
              ? {
                  'error': {
                    'code': 'DEPENDENCY_UNAVAILABLE',
                    'message': '训练安排暂时无法读取',
                  },
                }
              : {
                  'id': 'old-event',
                  'scheduled_date': '2024-02-29',
                  'status': 'skipped',
                  'title': '旧的安排',
                  'estimated_minutes': 30,
                  'content_snapshot': null,
                };
          return http.Response.bytes(
            utf8.encode(jsonEncode(body)),
            requests == 1 ? 503 : 200,
            headers: {'content-type': 'application/json'},
          );
        }),
      );
      final controller = PlanController(TrainingRepository(api));
      addTearDown(controller.dispose);
      addTearDown(api.close);
      await tester.pumpWidget(
        MaterialApp(
          home: CalendarEventDetailPage(
            controller: controller,
            eventId: 'old-event',
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('训练安排暂时无法读取'), findsOneWidget);
      expect(find.text('这项安排没有保存动作明细'), findsNothing);
      await tester.tap(find.text('重新加载'));
      await tester.pumpAndSettle();
      expect(find.text('旧的安排'), findsOneWidget);
      expect(find.textContaining('2024年2月29日 · 已跳过'), findsOneWidget);
      expect(find.text('这项安排没有保存动作明细'), findsOneWidget);
      expect(requests, 2);
      expect(tester.takeException(), isNull);
    },
  );
}
