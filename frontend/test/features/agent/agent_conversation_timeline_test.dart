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

void main() {
  testWidgets('opening long history follows the latest reply without a drag', (
    tester,
  ) async {
    final api = ApiClient(
      config: ApiConfig(baseUri: Uri.parse('https://example.test/api/v1')),
      accessTokenProvider: () => null,
      httpClient: MockClient(
        (request) async => http.Response(
          jsonEncode(
            request.url.path.endsWith('/messages')
                ? {
                    'list': [
                      for (var sequence = 1; sequence <= 30; sequence++)
                        {
                          'id': 'message-$sequence',
                          'role': sequence.isOdd ? 'user' : 'assistant',
                          'content': sequence == 30
                              ? '最新回复：史密斯上斜推胸30kg，4组，每组12次。'
                              : '这是第$sequence条历史消息。\n${'训练记录的详细说明。' * (sequence % 5 + 1)}',
                          'sequence': sequence,
                          'created_at': '2026-10-18T00:00:00Z',
                        },
                    ],
                  }
                : {
                    'confirmation_cards': [],
                    'completed_cards': [
                      for (final sequence in [2, 4])
                        {
                          'confirmation_id': 'card-$sequence',
                          'operation_type': 'body_measurement_create',
                          'status': 'succeeded',
                          'impact': '',
                          'version': 2,
                          'message_sequence': sequence,
                          'after': {
                            'measurement': {'weight_kg': 70},
                          },
                        },
                    ],
                    'resolved_counts': {'succeeded': 2},
                  },
          ),
          200,
          headers: {'content-type': 'application/json'},
        ),
      ),
    );
    final controller = AgentController(AgentRepository(api));
    addTearDown(controller.dispose);
    addTearDown(api.close);
    await tester.pumpWidget(
      MaterialApp(home: AgentPage(controller: controller)),
    );
    expect(
      await controller.openConversation(
        const AgentConversation(id: 'history', version: 1),
      ),
      isTrue,
    );
    await tester.pumpAndSettle();
    expect(
      find.text('最新回复：史密斯上斜推胸30kg，4组，每组12次。').hitTestable(),
      findsOneWidget,
    );

    // Reading older history must stop automatic following, including when the
    // controller sends a notification unrelated to a new message.
    await tester.drag(find.byType(ListView).first, const Offset(0, 1500));
    await tester.pumpAndSettle();
    final scrollable = tester.state<ScrollableState>(
      find.byType(Scrollable).first,
    );
    final olderPosition = scrollable.position.pixels;
    controller.reportImagePickerError();
    await tester.pumpAndSettle();
    expect(scrollable.position.pixels, closeTo(olderPosition, 1));
    // Opening a conversation again resets the user's old scroll position.
    await controller.openConversation(
      const AgentConversation(id: 'history', version: 1),
    );
    await tester.pumpAndSettle();
    expect(olderPosition, greaterThan(0));
    expect(
      find.text('最新回复：史密斯上斜推胸30kg，4组，每组12次。').hitTestable(),
      findsOneWidget,
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets('old saved cards do not bury later conversation at the bottom', (
    tester,
  ) async {
    final api = ApiClient(
      config: ApiConfig(baseUri: Uri.parse('https://example.test/api/v1')),
      accessTokenProvider: () => null,
      httpClient: MockClient(
        (_) async => throw StateError('unexpected request'),
      ),
    );
    final controller = AgentController(AgentRepository(api));
    addTearDown(controller.dispose);
    addTearDown(api.close);
    controller.messages = [
      for (var sequence = 1; sequence <= 6; sequence++)
        AgentMessage(
          id: 'message-$sequence',
          role: sequence.isOdd ? 'user' : 'assistant',
          content: sequence == 5
              ? '之后的训练安排呢？'
              : sequence == 6
              ? '先休息，再按体力安排下一组。'
              : '这是第$sequence条聊天正文。',
          sequence: sequence,
          createdAt: DateTime.utc(2026, 10, 18),
        ),
    ];
    controller.completedConfirmations = [
      for (final sequence in [2, 4])
        AgentConfirmationCard(
          id: 'card-$sequence',
          operationType: 'body_measurement_create',
          status: 'succeeded',
          impact: '',
          version: 2,
          messageSequence: sequence,
          after: {
            'measurement': {'weight_kg': 70},
          },
        ),
    ];
    expect(
      controller.conversationItems.map(
        (item) => switch (item) {
          AgentMessage message => message.id,
          AgentConfirmationCard card => card.id,
          _ => throw StateError('unexpected item'),
        },
      ),
      [
        'message-1',
        'message-2',
        'card-2',
        'message-3',
        'message-4',
        'card-4',
        'message-5',
        'message-6',
      ],
    );
    await tester.pumpWidget(
      MaterialApp(home: AgentPage(controller: controller)),
    );
    await tester.pumpAndSettle();
    await tester.drag(find.byType(ListView).first, const Offset(0, -2000));
    await tester.pumpAndSettle();
    expect(find.text('之后的训练安排呢？'), findsOneWidget);
    expect(find.text('先休息，再按体力安排下一组。'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  test('saving a card retains its original message association', () async {
    final api = ApiClient(
      config: ApiConfig(baseUri: Uri.parse('https://example.test/api/v1')),
      accessTokenProvider: () => null,
      httpClient: MockClient(
        (_) async => http.Response(
          '{"id":"card","status":"succeeded","version":2}',
          200,
        ),
      ),
    );
    final controller = AgentController(AgentRepository(api));
    addTearDown(controller.dispose);
    addTearDown(api.close);
    controller.messages = [
      for (final sequence in [1, 2, 3, 4])
        AgentMessage(
          id: 'm$sequence',
          role: sequence.isOdd ? 'user' : 'assistant',
          content: '聊天$sequence',
          sequence: sequence,
          createdAt: DateTime.utc(2026),
        ),
    ];
    const card = AgentConfirmationCard(
      id: 'card',
      operationType: 'nutrition_entry_create',
      status: 'pending',
      impact: '',
      version: 1,
      messageSequence: 2,
    );
    controller.confirmations = [card];
    await controller.decide(card, approve: true);
    expect(controller.completedConfirmations.single.messageSequence, 2);
    expect(controller.conversationItems.last, controller.messages.last);
    expect(controller.conversationItems[2], isA<AgentConfirmationCard>());
  });
}
