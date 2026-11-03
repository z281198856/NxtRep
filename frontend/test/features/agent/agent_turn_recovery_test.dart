import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nxtrep/core/config/api_config.dart';
import 'package:nxtrep/core/media/image_upload.dart';
import 'package:nxtrep/core/network/api_client.dart';
import 'package:nxtrep/features/agent/data/agent_repository.dart';
import 'package:nxtrep/features/agent/presentation/agent_controller.dart';
import 'package:nxtrep/features/agent/presentation/agent_page.dart';

void main() {
  testWidgets(
    'verification button reads the old run and disappears at completion',
    (tester) async {
      final fixture = _Fixture();
      addTearDown(fixture.close);
      fixture.runStatus = 'running';
      fixture.onPost = (_) async => _sse([
        {'event': 'run_started', 'run_id': 'run'},
      ]);
      await tester.runAsync(() => fixture.controller.send('记录午饭'));
      await tester.pumpWidget(
        MaterialApp(home: AgentPage(controller: fixture.controller)),
      );
      expect(find.text('核实上次结果'), findsOneWidget);
      fixture.runStatus = 'succeeded';
      await tester.runAsync(() async {
        await tester.tap(find.text('核实上次结果'));
        await Future<void>.delayed(const Duration(milliseconds: 20));
      });
      await tester.pumpAndSettle();
      expect(find.text('核实上次结果'), findsNothing);
      expect(find.text('草稿已经生成，请确认。'), findsOneWidget);
      expect(fixture.posts, hasLength(1));
      expect(tester.takeException(), isNull);
    },
  );

  test(
    'disconnect restores a finished run without posting another turn',
    () async {
      final fixture = _Fixture();
      final controller = fixture.controller;
      addTearDown(fixture.close);
      fixture.onPost = (_) async => _sse([
        {'event': 'run_started', 'run_id': 'run'},
      ]);
      await controller.send('记录午饭');
      expect(controller.lastRunId, 'run');
      expect(controller.messages.last.content, '草稿已经生成，请确认。');
      expect(controller.confirmations.single.id, 'card');
      expect(controller.errorMessage, isNull);
      expect(controller.statusMessage, contains('已核实'));
      expect(controller.canRetryLastTurn, isFalse);
      expect(fixture.posts, hasLength(1));
      expect(fixture.runReads, 1);
    },
  );

  test('running run is read again rather than posted again', () async {
    final fixture = _Fixture();
    addTearDown(fixture.close);
    fixture.runStatus = 'running';
    fixture.onPost = (_) async => _sse([
      {'event': 'run_started', 'run_id': 'run'},
    ]);
    await fixture.controller.send('记录午饭');
    expect(fixture.controller.canRetryLastTurn, isTrue);
    expect(fixture.controller.errorMessage, contains('仍在处理中'));
    expect(fixture.posts, hasLength(1));
    fixture.runStatus = 'succeeded';
    await fixture.controller.retryLastTurn();
    expect(fixture.posts, hasLength(1));
    expect(fixture.runReads, 2);
    expect(fixture.controller.errorMessage, isNull);
    expect(fixture.controller.canRetryLastTurn, isFalse);
  });

  test(
    'missing run id replays the exact original body including images',
    () async {
      final fixture = _Fixture();
      addTearDown(fixture.close);
      fixture.onPost = (_) async {
        if (fixture.posts.length == 1) {
          throw const SocketException('lost response');
        }
        return _sse([
          {'event': 'run_started', 'run_id': 'run'},
          {'event': 'completed', 'response': _response},
        ]);
      };
      await fixture.controller.addImageBytes(Uint8List.fromList([1, 2, 3]));
      await fixture.controller.send('看看这餐');
      expect(fixture.controller.canRetryLastTurn, isTrue);
      expect(fixture.controller.lastRunId, isNull);
      await fixture.controller.retryLastTurn();
      expect(fixture.posts, hasLength(2));
      expect(fixture.posts[1], fixture.posts.first);
      expect(
        fixture.posts.first['client_turn_id'],
        matches(
          RegExp(
            r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$',
          ),
        ),
      );
      expect(fixture.posts.first['image_asset_ids'], ['image']);
      expect(
        (fixture.posts.first['context_hints'] as Map)['occurred_at'],
        isNotEmpty,
      );
      expect(fixture.controller.messages, hasLength(2));
      expect(fixture.controller.canRetryLastTurn, isFalse);
    },
  );

  test(
    'terminal failed run restores drafts but is never executed again',
    () async {
      final fixture = _Fixture();
      addTearDown(fixture.close);
      fixture.runStatus = 'failed';
      fixture.resultPayload = null;
      fixture.onPost = (_) async => _sse([
        {'event': 'run_started', 'run_id': 'run'},
        {
          'event': 'failed',
          'error_code': 'AGENT_TIMEOUT',
          'message': '处理超时，请核对草稿。',
        },
      ]);
      await fixture.controller.send('记录午饭');
      expect(fixture.controller.errorMessage, contains('处理超时'));
      expect(fixture.controller.confirmations.single.id, 'card');
      expect(fixture.controller.statusMessage, isNull);
      expect(fixture.controller.canRetryLastTurn, isFalse);
      await fixture.controller.retryLastTurn();
      expect(fixture.posts, hasLength(1));
      await fixture.controller.send('重新尝试记录午饭');
      expect(fixture.posts, hasLength(2));
      expect(
        fixture.posts.last['client_turn_id'],
        isNot(fixture.posts.first['client_turn_id']),
      );
    },
  );

  test(
    'failed status lookup never falls back to a POST for a known run',
    () async {
      final fixture = _Fixture();
      addTearDown(fixture.close);
      fixture.failRunRead = true;
      fixture.onPost = (_) async => _sse([
        {'event': 'run_started', 'run_id': 'run'},
      ]);
      await fixture.controller.send('记录午饭');
      expect(fixture.controller.canRetryLastTurn, isTrue);
      await fixture.controller.retryLastTurn();
      expect(fixture.posts, hasLength(1));
      expect(fixture.controller.errorMessage, contains('无法核实'));
      expect(fixture.controller.statusMessage, isNull);
    },
  );

  test(
    'in-progress replay resolves the existing run without cancelling it',
    () async {
      final fixture = _Fixture();
      addTearDown(fixture.close);
      fixture.runStatus = 'running';
      fixture.onPost = (_) async {
        if (fixture.posts.length == 1) {
          throw const SocketException('lost run id');
        }
        return _sse([
          {'event': 'run_started', 'run_id': 'run'},
          {
            'event': 'failed',
            'error_code': 'AGENT_TURN_IN_PROGRESS',
            'message': '上一条仍在处理。',
          },
        ]);
      };
      await fixture.controller.send('记录午饭');
      await fixture.controller.retryLastTurn();
      expect(fixture.posts, hasLength(2));
      expect(fixture.posts.last, fixture.posts.first);
      expect(fixture.controller.lastRunId, 'run');
      expect(fixture.controller.errorMessage, contains('仍在处理中'));
      await fixture.controller.retryLastTurn();
      expect(fixture.posts, hasLength(2));
      expect(fixture.runReads, 2);
    },
  );

  test('incomplete terminal payload is not presented as success', () async {
    final fixture = _Fixture();
    addTearDown(fixture.close);
    fixture.resultPayload = {'status': 'completed'};
    fixture.onPost = (_) async => _sse([
      {'event': 'run_started', 'run_id': 'run'},
    ]);
    await fixture.controller.send('记录午饭');
    expect(fixture.controller.errorMessage, contains('返回不完整'));
    expect(fixture.controller.statusMessage, isNull);
    expect(fixture.controller.canRetryLastTurn, isTrue);
    expect(fixture.posts, hasLength(1));
  });

  test('conflicting turn body is rejected without offering replay', () async {
    final fixture = _Fixture();
    addTearDown(fixture.close);
    fixture.onPost = (_) async => _json({
      'error': {'code': 'AGENT_TURN_CONFLICT', 'message': '请求标识与原始内容不一致。'},
    }, status: 409);
    await fixture.controller.send('记录午饭');
    expect(fixture.controller.errorMessage, contains('不一致'));
    expect(fixture.controller.canRetryLastTurn, isFalse);
    await fixture.controller.retryLastTurn();
    expect(fixture.posts, hasLength(1));
  });
}

const _card = {
  'confirmation_id': 'card',
  'operation_type': 'nutrition_entry_create',
  'status': 'pending',
  'impact': '确认后保存',
  'version': 1,
};
const _response = {
  'status': 'completed',
  'message': '草稿已经生成，请确认。',
  'confirmation_cards': [_card],
};

http.Response _json(Object body, {int status = 200}) => http.Response(
  jsonEncode(body),
  status,
  headers: {'content-type': 'application/json; charset=utf-8'},
);

http.Response _sse(List<Map<String, Object>> events) => http.Response(
  events
      .map(
        (event) => 'event: ${event['event']}\ndata: ${jsonEncode(event)}\n\n',
      )
      .join(),
  200,
  headers: {'content-type': 'text/event-stream; charset=utf-8'},
);

class _Fixture {
  _Fixture() {
    api = ApiClient(
      config: ApiConfig(baseUri: Uri.parse('https://api.example.test/api/v1')),
      accessTokenProvider: () => 'access',
      httpClient: MockClient((request) async {
        if (request.url.path.endsWith('/conversations')) {
          return _json({'id': 'conversation', 'version': 1});
        }
        if (request.method == 'POST') {
          posts.add(jsonDecode(request.body) as Map<String, dynamic>);
          return onPost(request);
        }
        if (request.url.path.endsWith('/runs/run')) {
          runReads++;
          if (failRunRead) throw const SocketException('offline');
          return _json({
            'id': 'run',
            'conversation_id': 'conversation',
            'status': runStatus,
            'result_payload': resultPayload,
            'error_code': runStatus == 'failed' ? 'AGENT_TIMEOUT' : null,
            'error_message': runStatus == 'failed' ? '处理超时，请核对草稿。' : null,
          });
        }
        if (request.url.path.endsWith('/confirmations')) {
          return _json({
            'confirmation_cards': [_card],
            'resolved_counts': {},
          });
        }
        if (request.url.path.endsWith('/messages')) {
          return _json({
            'list': [
              {
                'id': 'user',
                'role': 'user',
                'content': '记录午饭',
                'sequence': 1,
                'created_at': '2026-10-08T00:00:00Z',
                'image_asset_ids': ['image'],
              },
              {
                'id': 'assistant',
                'role': 'assistant',
                'content': _response['message'],
                'sequence': 2,
                'created_at': '2026-10-08T00:00:01Z',
              },
            ],
            'has_more': false,
            'next_sequence': null,
          });
        }
        throw StateError('Unexpected request ${request.method} ${request.url}');
      }),
    );
    controller = AgentController(
      AgentRepository(api),
      imageUploader: (bytes) async => UploadedImage(
        assetId: 'image',
        bytes: bytes,
        contentType: 'image/jpeg',
      ),
    );
  }

  late final ApiClient api;
  late final AgentController controller;
  final posts = <Map<String, dynamic>>[];
  int runReads = 0;
  String runStatus = 'succeeded';
  Map<String, Object>? resultPayload = _response;
  bool failRunRead = false;
  late Future<http.Response> Function(http.Request) onPost;

  void close() {
    controller.dispose();
    api.close();
  }
}
