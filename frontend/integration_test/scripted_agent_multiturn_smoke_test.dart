import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:integration_test/integration_test.dart';
import 'package:nxtrep/core/config/api_config.dart';
import 'package:nxtrep/core/network/api_client.dart';
import 'package:nxtrep/features/agent/data/agent_repository.dart';
import 'package:nxtrep/features/agent/presentation/agent_controller.dart';
import 'package:nxtrep/features/agent/presentation/agent_page.dart';

// This smoke exercises the real chat UI and repository with a scripted HTTP
// backend. It never logs in, calls a real service, or changes a user's records.
void main() {
  final binding = IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  binding.framePolicy = LiveTestWidgetsFlutterBindingFramePolicy.onlyPumps;

  testWidgets('scripted backend: collect, verify, confirm, correct and undo', (
    tester,
  ) async {
    final backend = _ScriptedBackend();
    final api = ApiClient(
      config: ApiConfig(baseUri: Uri.parse('https://scripted.invalid/api/v1')),
      accessTokenProvider: () => 'scripted-test-token',
      httpClient: MockClient(backend.handle),
    );
    final controller = AgentController(AgentRepository(api));
    addTearDown(controller.dispose);
    addTearDown(api.close);
    await tester.pumpWidget(
      MaterialApp(home: AgentPage(controller: controller)),
    );
    await tester.pumpAndSettle();

    await _send(tester, controller, '帮我记录今天杠铃卧推。');
    expect(controller.messages.last.content, '今天卧推多少公斤？');
    expect(find.text('今天卧推多少公斤？', findRichText: true), findsOneWidget);
    expect(controller.confirmations, isEmpty);
    await _send(tester, controller, '60kg。');
    expect(controller.messages.last.content, '做了几组，每组多少次？');
    expect(find.text('做了几组，每组多少次？', findRichText: true), findsOneWidget);
    expect(controller.confirmations, isEmpty);
    expect(backend.creates, 0);

    // The scripted backend saved the draft but lost the response before the
    // run ID arrived. The visible verification action must reuse the request.
    await _send(tester, controller, '四组，每组8次。', expectError: true);
    expect(controller.lastRunId, isNull);
    expect(controller.canRetryLastTurn, isTrue);
    expect(find.text('核实上次结果'), findsOneWidget);
    expect(backend.drafts, 1);
    expect(backend.creates, 0);
    await tester.tap(find.text('核实上次结果'));
    await _idle(tester, controller);
    expect(backend.posts[3], backend.posts[2]);
    expect(backend.history, hasLength(6));
    expect(backend.drafts, 1);
    expect(find.text('核实上次结果'), findsNothing);
    expect(
      controller.confirmations.single.operationType,
      'workout_record_create',
    );
    await _reveal(tester, find.text('记录训练动作'));
    expect(find.text('60 公斤 · 4 组 · 每组 8 次'), findsOneWidget);
    await _approve(tester, controller, '确认记录');
    expect(backend.creates, 1);
    expect(backend.weight, 60);
    expect(backend.active, isTrue);

    await _send(tester, controller, '不对，重量是55kg。');
    expect(
      controller.confirmations.single.operationType,
      'workout_record_update',
    );
    expect(controller.confirmations.single.after!['workout_id'], _workoutId);
    expect(
      backend.weight,
      60,
      reason: 'A correction draft must not change records',
    );
    await _reveal(tester, find.text('更正动作训练记录'));
    expect(find.text('第 1 组：60 公斤 × 8 次 → 55 公斤 × 8 次'), findsOneWidget);
    await _approve(tester, controller, '确认更正');
    expect(backend.weight, 55);
    expect(
      backend.creates,
      1,
      reason: 'Correction must target the existing workout',
    );
    expect(backend.updates, 1);

    await _send(tester, controller, '算了，刚才那条不要了。');
    expect(
      controller.confirmations.single.operationType,
      'workout_record_void',
    );
    expect(controller.confirmations.single.after!['workout_id'], _workoutId);
    expect(backend.active, isTrue, reason: 'Undo requires card approval');
    await _reveal(tester, find.text('撤销误记动作'));
    expect(find.text('撤销第 1 组：55 公斤 × 8 次'), findsOneWidget);
    await _approve(tester, controller, '确认撤销');
    expect(backend.active, isFalse);
    expect(backend.voids, 1);
    expect(backend.creates, 1);
    expect(controller.confirmations, isEmpty);
    expect(backend.history, hasLength(10));
    expect(controller.messages, hasLength(10));

    final keys = backend.posts.map((body) => body['client_turn_id']).toSet();
    expect(
      keys,
      hasLength(5),
      reason: 'Each new input needs its own request identity',
    );
    for (final key in keys) {
      expect(
        key,
        matches(
          RegExp(
            r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$',
          ),
        ),
      );
    }
    expect(backend.approvalKeys, hasLength(3));
    expect(backend.approvalKeys.every((key) => key.isNotEmpty), isTrue);
    expect(controller.errorMessage, isNull);
    expect(tester.takeException(), isNull);
    debugPrint(
      'Scripted smoke: visible chat collection, same-key verification, '
      'create/update/void card approval passed; no real backend or user data.',
    );
  });
}

Future<void> _send(
  WidgetTester tester,
  AgentController controller,
  String message, {
  bool expectError = false,
}) async {
  final input = find.byType(TextField).last;
  // Sending unfocuses and clears the composer. On a device, settle that input
  // connection and explicitly focus the rebuilt field before entering again.
  await tester.pumpAndSettle();
  await tester.ensureVisible(input);
  await tester.tap(input);
  await tester.pumpAndSettle();
  await tester.enterText(input, message);
  await tester.pumpAndSettle();
  expect(tester.widget<TextField>(input).controller!.text, message);
  await tester.tap(find.byTooltip('发送'));
  await _idle(tester, controller, expectError: expectError);
  expect(
    controller.messages.where((item) => item.role == 'user').last.content,
    message,
  );
}

Future<void> _idle(
  WidgetTester tester,
  AgentController controller, {
  bool expectError = false,
}) async {
  for (var i = 0; i < 100; i++) {
    await tester.pump(const Duration(milliseconds: 100));
    if (!controller.sending) {
      await tester.pumpAndSettle();
      expect(controller.errorMessage, expectError ? isNotNull : isNull);
      return;
    }
  }
  fail('Scripted chat did not finish within ten seconds');
}

Future<void> _reveal(WidgetTester tester, Finder finder) async {
  if (finder.evaluate().isEmpty) {
    await tester.scrollUntilVisible(
      finder,
      250,
      scrollable: find
          .descendant(
            of: find.byType(ListView),
            matching: find.byType(Scrollable),
          )
          .first,
      maxScrolls: 20,
    );
  }
  await tester.ensureVisible(finder);
  await tester.pumpAndSettle();
}

Future<void> _approve(
  WidgetTester tester,
  AgentController controller,
  String label,
) async {
  final card = controller.confirmations.single;
  final button = find.widgetWithText(FilledButton, label);
  await _reveal(tester, button);
  await tester.tap(button);
  for (var i = 0; i < 100 && controller.isDeciding(card); i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
  await tester.pumpAndSettle();
  expect(controller.isDeciding(card), isFalse);
  expect(controller.errorMessage, isNull);
  expect(controller.confirmations, isEmpty);
  expect(find.text(label), findsNothing);
}

const _workoutId = 'scripted-workout';

class _ScriptedBackend {
  final posts = <Map<String, dynamic>>[];
  final history = <Map<String, Object?>>[];
  final approvalKeys = <String>[];
  final _responses = <String, Map<String, Object?>>{};
  Map<String, Object?>? _pending;
  int drafts = 0;
  int creates = 0;
  int updates = 0;
  int voids = 0;
  int weight = 0;
  bool active = false;

  Future<http.Response> handle(http.Request request) async {
    final path = request.url.path;
    if (request.method == 'POST' && path.endsWith('/agent/conversations')) {
      return _json({
        'id': 'scripted-conversation',
        'version': 1,
        'title': '多轮验收（脚本后端）',
      });
    }
    if (request.method == 'GET' && path.endsWith('/messages')) {
      return _json({'list': history, 'has_more': false, 'next_sequence': null});
    }
    if (request.method == 'GET' && path.endsWith('/confirmations')) {
      return _json({
        'confirmation_cards': [if (_pending != null) _pending],
        'resolved_counts': {'succeeded': creates + updates + voids},
      });
    }
    if (request.method == 'POST' && path.endsWith('/approve')) {
      final card = _pending!;
      expect(
        path,
        endsWith('/confirmations/${card['confirmation_id']}/approve'),
      );
      expect(jsonDecode(request.body), {'expected_version': 1});
      approvalKeys.add(request.headers['Idempotency-Key']!);
      switch (card['operation_type']) {
        case 'workout_record_create':
          creates++;
          weight = 60;
          active = true;
        case 'workout_record_update':
          updates++;
          weight = 55;
        case 'workout_record_void':
          voids++;
          active = false;
      }
      _pending = null;
      return _json({
        'id': card['confirmation_id'],
        'status': 'succeeded',
        'version': 2,
      });
    }
    if (request.method == 'POST' && path.endsWith('/messages')) {
      final body = jsonDecode(request.body) as Map<String, dynamic>;
      posts.add(body);
      final key = body['client_turn_id'] as String;
      final replay = _responses[key];
      if (replay != null) return _events(key, replay);
      final message = body['message'] as String;
      final turn = _responses.length;
      final (status, answer, operation) = switch (turn) {
        0 => ('needs_input', '今天卧推多少公斤？', null),
        1 => ('needs_input', '做了几组，每组多少次？', null),
        2 => ('completed', '卧推60公斤，4组，每组8次，请确认草稿。', 'workout_record_create'),
        3 => ('completed', '已按原记录生成55公斤的更正草稿，请确认。', 'workout_record_update'),
        4 => ('completed', '已生成撤销刚才卧推记录的草稿，请确认。', 'workout_record_void'),
        _ => throw StateError('Unexpected scripted turn'),
      };
      if (operation != null) {
        _pending = _card(operation);
        drafts++;
      }
      final response = <String, Object?>{
        'status': status,
        'message': answer,
        'confirmation_cards': [if (_pending != null) _pending],
      };
      _responses[key] = response;
      for (final (role, content) in [
        ('user', message),
        ('assistant', answer),
      ]) {
        history.add({
          'id': 'scripted-message-${history.length + 1}',
          'role': role,
          'content': content,
          'sequence': history.length + 1,
          'created_at': '2026-10-08T00:00:00Z',
        });
      }
      if (turn == 2) throw const SocketException('scripted lost response');
      return _events(key, response);
    }
    throw StateError('Unexpected scripted request: ${request.method} $path');
  }

  Map<String, Object?> _card(String operation) {
    final before = [
      for (var i = 1; i <= 4; i++)
        {
          'set_id': 'scripted-set-$i',
          'set_index': i,
          'weight_kg': '$weight',
          'reps': 8,
        },
    ];
    return {
      'confirmation_id': 'scripted-$operation',
      'operation_type': operation,
      'status': 'pending',
      'version': 1,
      'impact': '确认后生效，其他训练记录保留',
      'after': {
        if (operation != 'workout_record_create') 'workout_id': _workoutId,
        if (operation == 'workout_record_create')
          'request': {
            'exercise_name': '杠铃卧推',
            'weight_kg': '60',
            'sets': 4,
            'reps': 8,
          },
        'preview': {
          'date': '2026-10-08',
          'exercise_name': '杠铃卧推',
          if (operation == 'workout_record_create') ...{
            'weight_kg': '60',
            'sets': 4,
            'reps': 8,
          } else ...{
            'before_sets': before,
            'after_sets': operation == 'workout_record_void'
                ? []
                : [
                    for (final item in before) {...item, 'weight_kg': '55'},
                  ],
          },
        },
      },
    };
  }
}

http.Response _json(Object body) => http.Response(
  jsonEncode(body),
  200,
  headers: {'content-type': 'application/json; charset=utf-8'},
);

http.Response _events(
  String runId,
  Map<String, Object?> response,
) => http.Response(
  'event: run_started\ndata: ${jsonEncode({'event': 'run_started', 'run_id': runId})}\n\n'
  'event: completed\ndata: ${jsonEncode({'event': 'completed', 'response': response})}\n\n',
  200,
  headers: {'content-type': 'text/event-stream; charset=utf-8'},
);
