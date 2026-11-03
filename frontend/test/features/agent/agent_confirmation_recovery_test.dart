import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nxtrep/core/config/api_config.dart';
import 'package:nxtrep/core/network/api_client.dart';
import 'package:nxtrep/features/agent/data/agent_repository.dart';
import 'package:nxtrep/features/agent/domain/agent_models.dart';
import 'package:nxtrep/features/agent/presentation/agent_controller.dart';

const card = AgentConfirmationCard(
  id: 'meal',
  operationType: 'nutrition_entry_create',
  status: 'pending',
  impact: '确认后记录',
  version: 1,
);

AgentController controllerFor(
  Future<http.Response> Function(http.Request) handler,
) {
  final controller = AgentController(
    AgentRepository(
      ApiClient(
        config: ApiConfig(
          baseUri: Uri.parse('https://api.example.test/api/v1'),
        ),
        accessTokenProvider: () => 'access',
        httpClient: MockClient(handler),
      ),
    ),
  );
  controller.confirmations = [card];
  return controller;
}

void main() {
  const conversation = AgentConversation(id: 'history', version: 1);
  final recoveredCard = {
    'confirmation_id': 'latest',
    'operation_type': 'nutrition_entry_create',
    'status': 'pending',
    'version': 2,
    'impact': '确认后保存',
    'after': {
      'preview': {
        'totals': {'kcal': '57.5'},
      },
    },
    'draft': {'name': '重新恢复的草稿'},
  };

  test(
    'fresh controller restores latest cards and confirmed state from server',
    () async {
      final controller = controllerFor((request) async {
        if (request.url.path.endsWith('/messages')) {
          return http.Response(
            jsonEncode({
              'list': [
                {
                  'id': 'message',
                  'role': 'assistant',
                  'content': '旧回复说草稿待确认',
                  'sequence': 1,
                  'created_at': '2026-10-06T00:00:00Z',
                },
              ],
            }),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }
        return http.Response(
          jsonEncode({
            'confirmation_cards': [recoveredCard],
            'resolved_counts': {'succeeded': 1, 'cancelled': 1, 'expired': 1},
          }),
          200,
          headers: {'content-type': 'application/json; charset=utf-8'},
        );
      });
      addTearDown(controller.dispose);
      expect(await controller.openConversation(conversation), isTrue);
      expect(controller.confirmations.single.id, 'latest');
      expect(controller.confirmations.single.version, 2);
      expect(controller.confirmations.single.draft!['name'], '重新恢复的草稿');
      expect(controller.statusMessage, contains('已确认生效'));
      expect(controller.statusMessage, contains('已过期'));
      expect(controller.messages.single.content, '旧回复说草稿待确认');
    },
  );

  test(
    'unverified recovery retains history but never revives cached card',
    () async {
      final controller = controllerFor((request) async {
        if (request.url.path.endsWith('/messages')) {
          return http.Response('{"list":[]}', 200);
        }
        throw const SocketException('offline');
      });
      addTearDown(controller.dispose);
      expect(await controller.openConversation(conversation), isTrue);
      expect(controller.conversationId, 'history');
      expect(controller.confirmations, isEmpty);
      expect(controller.errorMessage, contains('草稿状态暂时无法核实'));
      expect(controller.statusMessage, isNull);
    },
  );

  test(
    'incomplete snapshot does not pretend there are no pending drafts',
    () async {
      final controller = controllerFor(
        (request) async => http.Response(
          request.url.path.endsWith('/messages') ? '{"list":[]}' : '{}',
          200,
        ),
      );
      addTearDown(controller.dispose);
      await controller.openConversation(conversation);
      expect(controller.confirmations, isEmpty);
      expect(controller.errorMessage, contains('返回不完整'));
    },
  );

  test(
    'new conversation is not overwritten by a late recovery response',
    () async {
      final response = Completer<http.Response>();
      final started = Completer<void>();
      final controller = controllerFor((request) async {
        if (request.url.path.endsWith('/messages')) {
          return http.Response('{"list":[]}', 200);
        }
        started.complete();
        return response.future;
      });
      addTearDown(controller.dispose);
      final loading = controller.openConversation(conversation);
      await started.future;
      controller.startNewConversation();
      response.complete(
        http.Response(
          jsonEncode({
            'confirmation_cards': [recoveredCard],
            'resolved_counts': {},
          }),
          200,
          headers: {'content-type': 'application/json; charset=utf-8'},
        ),
      );
      expect(await loading, isFalse);
      expect(controller.conversationId, isNull);
      expect(controller.confirmations, isEmpty);
    },
  );

  test('approval key survives repository recreation', () async {
    final keys = <String?>[];
    final api = ApiClient(
      config: ApiConfig(baseUri: Uri.parse('https://api.example.test/api/v1')),
      accessTokenProvider: () => 'access',
      httpClient: MockClient((request) async {
        keys.add(request.headers['Idempotency-Key']);
        return http.Response(
          '{"id":"meal","status":"succeeded","version":2}',
          200,
        );
      }),
    );
    addTearDown(api.close);
    await AgentRepository(api).approve(card);
    await AgentRepository(api).approve(card);
    expect(keys.first, isNotEmpty);
    expect(keys.last, keys.first);
  });

  for (final statusCode in [200, 503]) {
    test(
      'ambiguous HTTP $statusCode decision is verified instead of assumed',
      () async {
        final controller = controllerFor((request) async {
          if (request.method == 'POST') return http.Response('{}', statusCode);
          return http.Response(
            '{"id":"meal","status":"succeeded","version":2}',
            200,
          );
        });
        addTearDown(controller.dispose);
        await controller.decide(card, approve: true);
        expect(controller.confirmations, isEmpty);
        expect(controller.errorMessage, isNull);
        expect(controller.statusMessage, contains('已核实'));
      },
    );
  }
  test(
    'expired approval removes old card and explains how to continue',
    () async {
      var writes = 0;
      final controller = controllerFor((request) async {
        if (request.method == 'POST') {
          writes++;
          return http.Response(
            '{"error":{"code":"CONFIRMATION_CONFLICT","message":"Confirmation has expired"}}',
            409,
          );
        }
        return http.Response(
          '{"id":"meal","status":"expired","version":2}',
          200,
        );
      });
      addTearDown(controller.dispose);
      await controller.decide(card, approve: true);
      expect(writes, 1);
      expect(controller.confirmations, isEmpty);
      expect(controller.errorMessage, isNull);
      expect(controller.statusMessage, contains('已过期'));
      expect(controller.statusMessage, contains('未执行修改'));
      expect(controller.statusMessage, contains('重新提出修改'));
    },
  );
  test(
    'lost approval response is resolved only after reading succeeded status',
    () async {
      var writes = 0;
      final controller = controllerFor((request) async {
        if (request.method == 'POST') {
          writes++;
          throw const SocketException('response lost after commit');
        }
        return http.Response(
          '{"id":"meal","status":"succeeded","version":2}',
          200,
        );
      });
      addTearDown(controller.dispose);
      await controller.decide(card, approve: true);
      expect(writes, 1);
      expect(controller.confirmations, isEmpty);
      expect(controller.errorMessage, isNull);
      expect(controller.statusMessage, contains('已核实'));
      expect(controller.statusMessage, contains('已保存'));
    },
  );

  test(
    'unknown outcome keeps card and retry uses exactly the same approval key',
    () async {
      final keys = <String?>[];
      var writes = 0;
      final controller = controllerFor((request) async {
        if (request.method == 'GET') throw const SocketException('offline');
        keys.add(request.headers['Idempotency-Key']);
        writes++;
        if (writes == 1) throw const SocketException('unknown outcome');
        return http.Response(
          '{"id":"meal","status":"succeeded","version":2}',
          200,
        );
      });
      addTearDown(controller.dispose);
      await controller.decide(card, approve: true);
      expect(controller.confirmations, [card]);
      expect(controller.errorMessage, contains('无法核实'));
      await controller.decide(card, approve: true);
      expect(keys, hasLength(2));
      expect(keys.first, isNotEmpty);
      expect(keys[1], keys.first);
      expect(controller.confirmations, isEmpty);
      expect(controller.errorMessage, isNull);
    },
  );

  test('double tap sends a single decision while buttons are busy', () async {
    final response = Completer<http.Response>();
    var writes = 0;
    final controller = controllerFor((request) {
      writes++;
      return response.future;
    });
    addTearDown(controller.dispose);
    final first = controller.decide(card, approve: true);
    await Future<void>.delayed(Duration.zero);
    await controller.decide(card, approve: false);
    expect(controller.isDeciding(card), isTrue);
    expect(writes, 1);
    response.complete(
      http.Response('{"id":"meal","status":"succeeded","version":2}', 200),
    );
    await first;
    expect(controller.isDeciding(card), isFalse);
    expect(controller.confirmations, isEmpty);
  });

  test('incomplete status cannot be treated as successful approval', () async {
    final controller = controllerFor((request) async {
      if (request.method == 'POST') throw const SocketException('offline');
      return http.Response('{}', 200);
    });
    addTearDown(controller.dispose);
    await controller.decide(card, approve: true);
    expect(controller.confirmations, [card]);
    expect(controller.errorMessage, contains('无法核实'));
  });
}
