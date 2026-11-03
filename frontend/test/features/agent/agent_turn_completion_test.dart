import 'dart:async';
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nxtrep/core/config/api_config.dart';
import 'package:nxtrep/core/network/api_client.dart';
import 'package:nxtrep/core/network/sse_event.dart';
import 'package:nxtrep/features/agent/data/agent_repository.dart';
import 'package:nxtrep/features/agent/domain/agent_models.dart';
import 'package:nxtrep/features/agent/presentation/agent_controller.dart';

const _card = AgentConfirmationCard(
  id: 'meal-card',
  operationType: 'nutrition_entry_create',
  status: 'pending',
  impact: '确认后保存这餐',
  version: 1,
);
const _reply = '这餐的草稿已准备好，等你确认。';
const _response = <String, dynamic>{
  'status': 'completed',
  'message': _reply,
  'confirmation_cards': [
    {
      'confirmation_id': 'meal-card',
      'operation_type': 'nutrition_entry_create',
      'status': 'pending',
      'impact': '确认后保存这餐',
      'version': 1,
    },
  ],
};

void main() {
  testWidgets('terminal result is not trapped behind a stalled typing timer', (
    tester,
  ) async {
    final fixture = _Fixture(typingInterval: const Duration(minutes: 1));
    addTearDown(fixture.dispose);
    var finished = false;
    final send = fixture.controller.send('记录这餐').then((_) => finished = true);
    await tester.pump();
    fixture.events.add(_event('message_delta', {'delta': _reply}));
    fixture.events.add(_event('completed', {'response': _response}));
    await tester.pump();
    expect(fixture.controller.sending, isTrue);
    await tester.pump(const Duration(seconds: 13));
    await tester.pump();
    expect(finished, isTrue);
    await send;
    expect(fixture.controller.messages.last.content, _reply);
    expect(fixture.controller.messages.last.pending, isFalse);
    expect(fixture.controller.confirmations.single.id, _card.id);
    expect(fixture.controller.activityLabel, isNull);
    expect(fixture.posts, 1);
  });

  testWidgets('history refresh cannot keep a completed turn in sending state', (
    tester,
  ) async {
    final fixture = _Fixture();
    addTearDown(fixture.dispose);
    fixture.history = Completer<List<AgentMessage>>();
    var finished = false;
    final send = fixture.controller.send('记录这餐').then((_) => finished = true);
    await tester.pump();
    fixture.events.add(_event('completed', {'response': _response}));
    await tester.pump();
    await tester.pump(const Duration(seconds: 9));
    await tester.pump();
    expect(finished, isTrue);
    await send;
    expect(fixture.controller.messages.last.content, _reply);
    expect(fixture.controller.errorMessage, isNull);
    expect(fixture.controller.canRetryLastTurn, isFalse);
    expect(fixture.controller.sending, isFalse);
    expect(fixture.controller.confirmations.single.id, _card.id);
    fixture.history!.complete([]);
    await tester.pump();
    expect(fixture.controller.messages.last.content, _reply);
    expect(fixture.posts, 1);
  });

  testWidgets(
    'missing terminal event recovers the existing run while SSE stays open',
    (tester) async {
      final fixture = _Fixture();
      addTearDown(fixture.dispose);
      var finished = false;
      final send = fixture.controller.send('记录这餐').then((_) => finished = true);
      await tester.pump();
      fixture.events.add(_event('run_started', {'run_id': 'run'}));
      fixture.events.add(_event('message_delta', {'delta': '这餐的草稿'}));
      await tester.pump();
      await tester.pump(const Duration(seconds: 13));
      await tester.pump();
      expect(finished, isTrue);
      await send;
      expect(fixture.runReads, 1);
      expect(fixture.posts, 1);
      expect(fixture.controller.messages.last.content, _reply);
      expect(fixture.controller.confirmations.single.id, _card.id);
      expect(fixture.controller.sending, isFalse);
      expect(fixture.controller.canRetryLastTurn, isFalse);
      expect(fixture.controller.errorMessage, isNull);
      await tester.pump(const Duration(seconds: 30));
      expect(fixture.runReads, 1);
    },
  );

  testWidgets('a still-running request is not presented as completed', (
    tester,
  ) async {
    final fixture = _Fixture();
    addTearDown(fixture.dispose);
    fixture.runStatus = 'running';
    final send = fixture.controller.send('记录这餐');
    await tester.pump();
    fixture.events.add(_event('run_started', {'run_id': 'run'}));
    await tester.pump();
    await tester.pump(const Duration(seconds: 13));
    await tester.pump();
    expect(fixture.runReads, 1);
    expect(fixture.controller.sending, isTrue);
    expect(fixture.controller.confirmations, isEmpty);
    expect(fixture.controller.errorMessage, isNull);
    fixture.events.add(_event('completed', {'response': _response}));
    await tester.pump();
    await send;
    expect(fixture.posts, 1);
    expect(fixture.controller.sending, isFalse);
    await tester.pump(const Duration(seconds: 30));
    expect(fixture.runReads, 1);
  });

  testWidgets(
    'unrelated or unavailable run status does not replace the active reply',
    (tester) async {
      for (final unrelated in [true, false]) {
        final fixture = _Fixture();
        addTearDown(fixture.dispose);
        fixture.runConversation = unrelated
            ? 'another-conversation'
            : 'conversation';
        fixture.failRunRead = !unrelated;
        final send = fixture.controller.send('记录这餐');
        await tester.pump();
        fixture.events.add(_event('run_started', {'run_id': 'run'}));
        await tester.pump();
        await tester.pump(const Duration(seconds: 13));
        await tester.pump();
        expect(fixture.runReads, 1);
        expect(fixture.controller.sending, isTrue);
        expect(fixture.controller.confirmations, isEmpty);
        fixture.events.add(_event('completed', {'response': _response}));
        await tester.pump();
        await send;
        expect(fixture.posts, 1);
        expect(fixture.controller.messages.last.content, _reply);
      }
    },
  );
}

SseEvent _event(String event, Map<String, Object> payload) =>
    SseEvent(event: event, data: jsonEncode({'event': event, ...payload}));

class _Fixture extends AgentRepository {
  _Fixture({Duration typingInterval = const Duration(milliseconds: 40)})
    : super(
        ApiClient(
          config: ApiConfig(
            baseUri: Uri.parse('https://api.example.test/api/v1'),
          ),
          accessTokenProvider: () => 'test',
          httpClient: MockClient((_) async => http.Response('unused', 500)),
        ),
      ) {
    controller = AgentController(this, typingInterval: typingInterval);
  }

  late final AgentController controller;
  final events = StreamController<SseEvent>();
  Completer<List<AgentMessage>>? history;
  int posts = 0;
  int runReads = 0;
  String runStatus = 'succeeded';
  String runConversation = 'conversation';
  bool failRunRead = false;

  @override
  Future<AgentConversation> createConversation() async =>
      const AgentConversation(id: 'conversation', version: 1);

  @override
  Stream<SseEvent> sendMessage({
    required String conversationId,
    required String message,
    List<String> imageAssetIds = const [],
    String? clientTurnId,
    Map<String, Object> contextHints = const {},
  }) {
    posts++;
    return events.stream;
  }

  @override
  Future<AgentRun> getRun(String runId) async {
    runReads++;
    if (failRunRead) throw const FormatException('unavailable run');
    return AgentRun(
      id: runId,
      conversationId: runConversation,
      status: runStatus,
      resultPayload: runStatus == 'succeeded' ? _response : null,
    );
  }

  @override
  Future<List<AgentMessage>> listMessages(String conversationId) async =>
      history?.future ??
      [
        AgentMessage(
          id: 'assistant',
          role: 'assistant',
          content: _reply,
          sequence: 2,
          createdAt: DateTime.utc(2026, 10, 18),
        ),
      ];

  @override
  Future<ConversationConfirmations> restoreConfirmations(
    String conversationId,
  ) async =>
      const ConversationConfirmations(cards: [_card], resolvedCounts: {});

  void dispose() {
    controller.dispose();
    unawaited(events.close());
  }
}
