import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nxtrep/core/config/api_config.dart';
import 'package:nxtrep/core/network/api_client.dart';
import 'package:nxtrep/features/agent/data/agent_repository.dart';
import 'package:nxtrep/features/agent/domain/agent_models.dart';
import 'package:nxtrep/features/agent/presentation/agent_controller.dart';
import 'package:nxtrep/features/agent/presentation/agent_page.dart';

const _meal = AgentConfirmationCard(
  id: 'meal',
  operationType: 'nutrition_entry_create',
  status: 'pending',
  impact: '确认后保存这餐',
  version: 1,
  after: {
    'entry': {'meal_type': 'lunch'},
    'preview': {
      'items': [
        {'name': '米饭', 'amount_g': '200', 'source': 'model_estimated'},
      ],
      'totals': {
        'kcal': '230',
        'protein_g': '5',
        'carbs_g': '50',
        'fat_g': '1',
      },
    },
  },
);

void main() {
  test('a late save cannot place the old card in a new conversation', () async {
    final response = Completer<http.Response>();
    final api = _api((_) => response.future);
    final controller = AgentController(AgentRepository(api));
    addTearDown(controller.dispose);
    addTearDown(api.close);
    controller.conversationId = 'old';
    controller.confirmations = [_meal];
    final deciding = controller.decide(_meal, approve: true);
    controller.startNewConversation();
    response.complete(
      http.Response('{"id":"meal","status":"succeeded","version":2}', 200),
    );
    await deciding;
    expect(controller.conversationCards, isEmpty);
    expect(controller.conversationId, isNull);
  });

  testWidgets('saving keeps the meal visible and removes all card actions', (
    tester,
  ) async {
    var writes = 0;
    final api = _api((request) async {
      writes++;
      return http.Response(
        '{"id":"meal","status":"succeeded","version":2}',
        200,
      );
    });
    final controller = AgentController(AgentRepository(api));
    addTearDown(controller.dispose);
    addTearDown(api.close);
    controller.messages = [_message];
    controller.confirmations = [_meal];
    await tester.pumpWidget(
      MaterialApp(home: AgentPage(controller: controller)),
    );
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.text('确认保存'));
    await tester.tap(find.text('确认保存'));
    await tester.pumpAndSettle();
    expect(find.text('已保存'), findsOneWidget);
    expect(find.text('午餐记录'), findsOneWidget);
    expect(find.textContaining('米饭 200 克'), findsOneWidget);
    expect(find.text('确认保存'), findsNothing);
    expect(find.text('调整份量'), findsNothing);
    expect(find.text('取消'), findsNothing);
    expect(find.text('只有你确认后才会生效'), findsNothing);
    expect(controller.confirmations, isEmpty);
    expect(controller.completedConfirmations.single.status, 'succeeded');
    // Both a retained callback and the read-only snapshot must refuse another write.
    await controller.decide(_meal, approve: true);
    await controller.decide(
      controller.completedConfirmations.single,
      approve: true,
    );
    expect(await controller.reviseMealPortions(_meal, []), isFalse);
    expect(writes, 1);
    expect(tester.takeException(), isNull);
  });

  testWidgets('a fresh controller restores a saved meal as a read-only card', (
    tester,
  ) async {
    var writes = 0;
    final api = _api((request) async {
      if (request.method != 'GET') writes++;
      return _json(
        request.url.path.endsWith('/messages')
            ? {
                'list': [
                  {
                    'id': 'reply',
                    'role': 'assistant',
                    'content': '按米饭200克估算。',
                    'sequence': 1,
                    'created_at': '2026-10-18T00:00:00Z',
                  },
                ],
              }
            : {
                'confirmation_cards': [],
                'completed_cards': [
                  {
                    'confirmation_id': _meal.id,
                    'operation_type': _meal.operationType,
                    'status': 'succeeded',
                    'impact': _meal.impact,
                    'version': 2,
                    'after': _meal.after,
                  },
                ],
                'resolved_counts': {'succeeded': 1},
              },
      );
    });
    final controller = AgentController(AgentRepository(api));
    addTearDown(controller.dispose);
    addTearDown(api.close);
    expect(
      await controller.openConversation(
        const AgentConversation(id: 'history', version: 1),
      ),
      isTrue,
    );
    await tester.pumpWidget(
      MaterialApp(home: AgentPage(controller: controller)),
    );
    await tester.pumpAndSettle();
    expect(find.text('已保存'), findsOneWidget);
    expect(find.textContaining('米饭 200 克'), findsOneWidget);
    expect(find.text('确认保存'), findsNothing);
    expect(find.text('调整份量'), findsNothing);
    expect(writes, 0);
  });

  test(
    'saved cards retain their position and do not leak to another conversation',
    () async {
      final api = _api(
        (request) async => http.Response(
          '{"id":"meal","status":"succeeded","version":2}',
          200,
        ),
      );
      final controller = AgentController(AgentRepository(api));
      addTearDown(controller.dispose);
      addTearDown(api.close);
      const earlier = AgentConfirmationCard(
        id: 'earlier',
        operationType: 'food_create',
        status: 'pending',
        impact: '',
        version: 1,
      );
      controller.confirmations = [earlier, _meal];
      expect(controller.conversationCards.map((card) => card.id), [
        'earlier',
        'meal',
      ]);
      await controller.decide(_meal, approve: true);
      expect(controller.conversationCards.map((card) => card.id), [
        'earlier',
        'meal',
      ]);
      controller.startNewConversation();
      expect(controller.conversationCards, isEmpty);
    },
  );

  test('an unverified save does not become a read-only success', () async {
    final api = _api(
      (_) async => http.Response(
        '{"error":{"code":"NETWORK_ERROR","message":"offline"}}',
        503,
      ),
    );
    final controller = AgentController(AgentRepository(api));
    addTearDown(controller.dispose);
    addTearDown(api.close);
    controller.confirmations = [_meal];
    await controller.decide(_meal, approve: true);
    expect(controller.completedConfirmations, isEmpty);
    expect(controller.confirmations, [_meal]);
    expect(controller.errorMessage, contains('无法核实'));
  });

  test(
    'pending or duplicated saved snapshots are rejected during restoration',
    () async {
      for (final status in ['pending', 'succeeded']) {
        final api = _api(
          (_) async => _json({
            'confirmation_cards': status == 'succeeded'
                ? [
                    {
                      'confirmation_id': 'meal',
                      'operation_type': 'nutrition_entry_create',
                      'status': 'pending',
                      'impact': '',
                      'version': 1,
                    },
                  ]
                : [],
            'completed_cards': [
              {
                'confirmation_id': 'meal',
                'operation_type': 'nutrition_entry_create',
                'status': status,
                'impact': '',
                'version': 2,
              },
            ],
            'resolved_counts': {},
          }),
        );
        addTearDown(api.close);
        await expectLater(
          AgentRepository(api).restoreConfirmations('history'),
          throwsA(isA<Exception>()),
        );
      }
    },
  );
}

final _message = AgentMessage(
  id: 'reply',
  role: 'assistant',
  content: '按米饭200克估算。',
  sequence: 1,
  createdAt: DateTime.utc(2026, 10, 18),
);

ApiClient _api(Future<http.Response> Function(http.Request) handler) =>
    ApiClient(
      config: ApiConfig(baseUri: Uri.parse('https://api.example.test/api/v1')),
      accessTokenProvider: () => 'test',
      httpClient: MockClient(handler),
    );

http.Response _json(Map<String, Object?> value) => http.Response(
  jsonEncode(value),
  200,
  headers: {'content-type': 'application/json; charset=utf-8'},
);
