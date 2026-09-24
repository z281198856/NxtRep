import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nxtrep/core/config/api_config.dart';
import 'package:nxtrep/core/network/api_client.dart';
import 'package:nxtrep/features/agent/data/agent_repository.dart';
import 'package:nxtrep/features/agent/presentation/agent_controller.dart';
import 'package:nxtrep/features/agent/presentation/agent_management_page.dart';

void main() {
  testWidgets('creates a long-term memory and closes the editor safely', (
    tester,
  ) async {
    var memoryCreated = false;
    final client = MockClient((request) async {
      if (request.method == 'GET' &&
          request.url.path == '/api/v1/agent/conversations') {
        return http.Response(jsonEncode({'list': const []}), 200);
      }
      if (request.method == 'GET' && request.url.path == '/api/v1/memories') {
        return http.Response(
          jsonEncode({
            'list': memoryCreated
                ? [
                    {
                      'id': '00000000-0000-4000-8000-000000000001',
                      'category': 'other',
                      'content': '更喜欢早晨训练',
                      'source': 'user',
                      'saved_at': '2026-09-24T00:00:00Z',
                      'version': 1,
                    },
                  ]
                : const [],
          }),
          200,
        );
      }
      if (request.method == 'POST' && request.url.path == '/api/v1/memories') {
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        expect(body, {'category': 'other', 'content': '更喜欢早晨训练'});
        memoryCreated = true;
        return http.Response(
          jsonEncode({
            'id': '00000000-0000-4000-8000-000000000001',
            'category': 'other',
            'content': '更喜欢早晨训练',
            'source': 'user',
            'saved_at': '2026-09-24T00:00:00Z',
            'version': 1,
          }),
          201,
        );
      }
      throw StateError('Unexpected request ${request.method} ${request.url}');
    });
    final api = ApiClient(
      config: ApiConfig(baseUri: Uri.parse('https://api.example.test/api/v1')),
      accessTokenProvider: () => 'access',
      httpClient: client,
    );
    final controller = AgentController(AgentRepository(api));
    addTearDown(controller.dispose);
    addTearDown(api.close);

    await tester.pumpWidget(
      MaterialApp(home: AgentManagementPage(controller: controller)),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('长期记忆'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('新增记忆'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField), '更喜欢早晨训练');
    await tester.tap(find.text('保存'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 500));
    await tester.pumpAndSettle();

    expect(tester.takeException(), isNull);
    expect(memoryCreated, isTrue);
  });
}
