import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nxtrep/core/config/api_config.dart';
import 'package:nxtrep/core/network/api_client.dart';
import 'package:nxtrep/features/agent/data/agent_repository.dart';

void main() {
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
