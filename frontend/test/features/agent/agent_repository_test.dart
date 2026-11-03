import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nxtrep/core/config/api_config.dart';
import 'package:nxtrep/core/network/api_client.dart';
import 'package:nxtrep/core/network/api_exception.dart';
import 'package:nxtrep/features/agent/data/agent_repository.dart';

void main() {
  test('loads all history pages including messages beyond 100', () async {
    final cursors = <String?>[];
    final api = ApiClient(
      config: ApiConfig(baseUri: Uri.parse('https://api.example.test/api/v1')),
      accessTokenProvider: () => 'access',
      httpClient: MockClient((request) async {
        final cursor = int.parse(
          request.url.queryParameters['after_sequence']!,
        );
        cursors.add('$cursor');
        final end = cursor == 0 ? 100 : 135;
        return http.Response(
          jsonEncode({
            'list': [
              for (var index = cursor + 1; index <= end; index++)
                {
                  'id': 'message-$index',
                  'role': index.isOdd ? 'user' : 'assistant',
                  'content': '第 $index 条消息',
                  'sequence': index,
                  'created_at': '2026-10-08T00:00:00Z',
                },
            ],
            'has_more': end == 100,
            'next_sequence': end == 100 ? 100 : null,
          }),
          200,
          headers: {'content-type': 'application/json; charset=utf-8'},
        );
      }),
    );
    addTearDown(api.close);
    final messages = await AgentRepository(api).listMessages('conversation');
    expect(messages, hasLength(135));
    expect(messages.last.content, '第 135 条消息');
    expect(cursors, ['0', '100']);
  });

  for (final next in [0, 2, null]) {
    test(
      'rejects invalid cursor $next instead of endlessly fetching',
      () async {
        var calls = 0;
        final api = ApiClient(
          config: ApiConfig(
            baseUri: Uri.parse('https://api.example.test/api/v1'),
          ),
          accessTokenProvider: () => 'access',
          httpClient: MockClient((request) async {
            calls++;
            return http.Response(
              jsonEncode({
                'list': [
                  {
                    'id': 'message',
                    'role': 'user',
                    'content': '继续',
                    'sequence': 1,
                    'created_at': '2026-10-08T00:00:00Z',
                  },
                ],
                'has_more': true,
                'next_sequence': next,
              }),
              200,
              headers: {'content-type': 'application/json; charset=utf-8'},
            );
          }),
        );
        addTearDown(api.close);
        await expectLater(
          AgentRepository(api).listMessages('conversation'),
          throwsA(
            isA<ApiException>().having(
              (error) => error.code,
              'code',
              'INVALID_SUCCESS_RESPONSE',
            ),
          ),
        );
        expect(calls, 1);
      },
    );
  }

  test('rejects a repeated page even if next_sequence advances', () async {
    var calls = 0;
    final api = ApiClient(
      config: ApiConfig(baseUri: Uri.parse('https://api.example.test/api/v1')),
      accessTokenProvider: () => 'access',
      httpClient: MockClient((request) async {
        calls++;
        return http.Response(
          jsonEncode({
            'list': [
              {
                'id': 'message',
                'role': 'user',
                'content': '继续',
                'sequence': 1,
                'created_at': '2026-10-08T00:00:00Z',
              },
            ],
            'has_more': true,
            'next_sequence': calls,
          }),
          200,
          headers: {'content-type': 'application/json; charset=utf-8'},
        );
      }),
    );
    addTearDown(api.close);
    await expectLater(
      AgentRepository(api).listMessages('conversation'),
      throwsA(isA<ApiException>()),
    );
    expect(calls, 2);
  });

  test('preserves a supplied turn identity and context in SSE body', () async {
    late Map<String, dynamic> body;
    final api = ApiClient(
      config: ApiConfig(baseUri: Uri.parse('https://api.example.test/api/v1')),
      accessTokenProvider: () => 'access',
      httpClient: MockClient((request) async {
        body = jsonDecode(request.body) as Map<String, dynamic>;
        return http.Response(
          'event: failed\ndata: {"event":"failed"}\n\n',
          200,
          headers: {'content-type': 'text/event-stream; charset=utf-8'},
        );
      }),
    );
    addTearDown(api.close);
    await AgentRepository(api)
        .sendMessage(
          conversationId: 'conversation',
          message: '记录午饭',
          clientTurnId: '00000000-0000-4000-8000-000000000001',
          contextHints: const {'occurred_at': '2026-10-08T12:00:00+08:00'},
        )
        .toList();
    expect(body['client_turn_id'], '00000000-0000-4000-8000-000000000001');
    expect(body['context_hints'], {'occurred_at': '2026-10-08T12:00:00+08:00'});
  });

  for (final payload in [
    {'id': 'other', 'conversation_id': 'conversation', 'status': 'running'},
    {'id': 'run', 'conversation_id': 'conversation', 'status': 'unknown'},
    {
      'id': 'run',
      'conversation_id': 'conversation',
      'status': 'succeeded',
      'result_payload': 'success',
    },
  ]) {
    test('rejects mismatched or incomplete run $payload', () async {
      final api = ApiClient(
        config: ApiConfig(
          baseUri: Uri.parse('https://api.example.test/api/v1'),
        ),
        accessTokenProvider: () => 'access',
        httpClient: MockClient(
          (request) async => http.Response(jsonEncode(payload), 200),
        ),
      );
      addTearDown(api.close);
      await expectLater(
        AgentRepository(api).getRun('run'),
        throwsA(isA<ApiException>()),
      );
    });
  }

  test(
    'creates a conversation and requests chunk-granularity POST SSE',
    () async {
      late http.Request streamedRequest;
      final httpClient = MockClient((request) async {
        if (request.method == 'POST' &&
            request.url.path == '/api/v1/agent/conversations') {
          expect(jsonDecode(request.body), {'title': null});
          return http.Response(
            jsonEncode({
              'id': '00000000-0000-0000-0000-000000000031',
              'version': 1,
            }),
            201,
          );
        }
        if (request.method == 'POST' &&
            request.url.path.endsWith('/messages')) {
          streamedRequest = request;
          return http.Response(
            'event: message_delta\n'
            'data: {"event":"message_delta","delta":"你好"}\n\n'
            'event: completed\n'
            'data: {"event":"completed","response":{"message":"你好"}}\n\n',
            200,
            headers: {'content-type': 'text/event-stream; charset=utf-8'},
          );
        }
        throw StateError('Unexpected request ${request.method} ${request.url}');
      });
      final api = ApiClient(
        config: ApiConfig(
          baseUri: Uri.parse('https://api.example.test/api/v1'),
        ),
        accessTokenProvider: () => 'access',
        httpClient: httpClient,
      );
      final repository = AgentRepository(api);

      final conversation = await repository.createConversation();
      final events = await repository
          .sendMessage(
            conversationId: conversation.id,
            message: '分析这张图片',
            imageAssetIds: const ['00000000-0000-0000-0000-000000000032'],
          )
          .toList();

      expect(streamedRequest.method, 'POST');
      expect(streamedRequest.url.queryParameters['granularity'], 'chunk');
      expect(jsonDecode(streamedRequest.body), {
        'message': '分析这张图片',
        'image_asset_ids': <String>['00000000-0000-0000-0000-000000000032'],
        'context_hints': <String, Object>{},
      });
      expect(events.map((event) => event.event), [
        'message_delta',
        'completed',
      ]);
    },
  );
}
