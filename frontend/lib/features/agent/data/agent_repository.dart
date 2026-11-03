import 'package:uuid/uuid.dart';

import '../../../core/network/api_client.dart';
import '../../../core/network/api_exception.dart';
import '../../../core/network/sse_event.dart';
import '../domain/agent_models.dart';

class AgentRepository {
  AgentRepository(this._apiClient, {Uuid? uuid}) : _uuid = uuid ?? const Uuid();

  final ApiClient _apiClient;
  final Uuid _uuid;

  Future<AgentConversation> createConversation() async {
    final json = expectJsonObject(
      await _apiClient.post('/agent/conversations', body: {'title': null}),
      context: 'AI 私人教练会话接口',
    );
    return AgentConversation.fromJson(json);
  }

  Future<List<AgentConversation>> listConversations({
    String status = 'active',
  }) async {
    final json = expectJsonObject(
      await _apiClient.get(
        '/agent/conversations',
        query: {'status': status, 'page': '1', 'page_size': '100'},
      ),
      context: 'AI 私人教练会话列表接口',
    );
    return (json['list'] as List<dynamic>? ?? const [])
        .map(
          (item) => AgentConversation.fromJson(
            Map<String, dynamic>.from(item as Map),
          ),
        )
        .toList(growable: false);
  }

  Future<AgentConversation> getConversation(String id) async {
    final json = expectJsonObject(
      await _apiClient.get('/agent/conversations/$id'),
      context: 'AI 私人教练会话详情接口',
    );
    return AgentConversation.fromJson(json);
  }

  Future<AgentConversation> updateConversation(
    AgentConversation conversation, {
    String? title,
    String? status,
  }) async {
    final json = expectJsonObject(
      await _apiClient.patch(
        '/agent/conversations/${conversation.id}',
        body: {
          'title': ?title?.trim(),
          'status': ?status,
          'expected_version': conversation.version,
        },
      ),
      context: '更新 AI 私人教练会话接口',
    );
    return AgentConversation.fromJson(json);
  }

  Future<void> deleteConversation(AgentConversation conversation) => _apiClient
      .delete(
        '/agent/conversations/${conversation.id}',
        body: {'expected_version': conversation.version},
      )
      .then((_) {});

  Future<List<AgentMessage>> listMessages(String conversationId) async {
    final messages = <AgentMessage>[];
    var afterSequence = 0;
    while (true) {
      final json = expectJsonObject(
        await _apiClient.get(
          '/agent/conversations/$conversationId/messages',
          query: {'after_sequence': '$afterSequence', 'limit': '100'},
        ),
        context: 'AI 私人教练消息接口',
      );
      try {
        final values = json['list'] as List<dynamic>;
        final page = values
            .map(
              (item) =>
                  AgentMessage.fromJson(Map<String, dynamic>.from(item as Map)),
            )
            .toList(growable: false);
        var previous = afterSequence;
        for (final message in page) {
          if (message.sequence <= previous) {
            throw const FormatException('Non-increasing message sequence');
          }
          previous = message.sequence;
        }
        messages.addAll(page);
        final hasMore = json['has_more'] ?? false;
        if (hasMore is! bool) throw const FormatException('Invalid pagination');
        if (!hasMore) return List.unmodifiable(messages);
        final next = json['next_sequence'];
        if (page.isEmpty ||
            next is! int ||
            next != page.last.sequence ||
            next <= afterSequence) {
          throw const FormatException('Non-increasing message cursor');
        }
        afterSequence = next;
      } on Object {
        throw const ApiException(
          code: 'INVALID_SUCCESS_RESPONSE',
          message: '聊天记录分页返回不完整，暂时无法恢复，请重新打开对话',
        );
      }
    }
  }

  Future<AgentRun> getRun(String runId) async {
    final json = expectJsonObject(
      await _apiClient.get('/agent/runs/$runId'),
      context: '核实 AI 处理结果接口',
    );
    try {
      final run = AgentRun.fromJson(json);
      if (run.id != runId) throw const FormatException('Mismatched run');
      return run;
    } on Object {
      throw const ApiException(
        code: 'INVALID_SUCCESS_RESPONSE',
        message: '处理状态返回不完整，暂时无法核实上次结果',
      );
    }
  }

  Stream<SseEvent> sendMessage({
    required String conversationId,
    required String message,
    List<String> imageAssetIds = const [],
    String? clientTurnId,
    Map<String, Object> contextHints = const {},
  }) => _apiClient.postSse(
    '/agent/conversations/$conversationId/messages',
    query: const {'granularity': 'chunk'},
    body: {
      'message': message,
      'image_asset_ids': imageAssetIds,
      'context_hints': contextHints,
      'client_turn_id': ?clientTurnId,
    },
  );

  Future<void> approve(AgentConfirmationCard card) async {
    final response = await _apiClient.post(
      '/confirmations/${card.id}/approve',
      // The same command keeps the same key after a process restart.
      idempotencyKey: _uuid.v5(
        Namespace.url.value,
        'nxtrep:confirmation:approve:${card.id}:${card.version}',
      ),
      body: {'expected_version': card.version},
    );
    _validateDecision(response, card, 'succeeded');
  }

  Future<ConversationConfirmations> restoreConfirmations(
    String conversationId,
  ) async {
    final json = expectJsonObject(
      await _apiClient.get(
        '/agent/conversations/$conversationId/confirmations',
      ),
      context: '恢复待确认草稿接口',
    );
    final values = json['confirmation_cards'];
    final completedValues = json['completed_cards'] ?? const <dynamic>[];
    final counts = json['resolved_counts'];
    if (values is! List || completedValues is! List || counts is! Map) {
      throw const ApiException(
        code: 'INVALID_SUCCESS_RESPONSE',
        message: '草稿状态返回不完整，暂时无法恢复，请重新打开对话',
      );
    }
    try {
      final cards = values
          .map(
            (item) => AgentConfirmationCard.fromJson(
              Map<String, dynamic>.from(item as Map),
            ),
          )
          .toList(growable: false);
      final resolvedCounts = Map<String, int>.from(counts);
      final completedCards = completedValues
          .map(
            (item) => AgentConfirmationCard.fromJson(
              Map<String, dynamic>.from(item as Map),
            ),
          )
          .toList(growable: false);
      if (cards.any((card) => card.status != 'pending' || card.version < 1) ||
          completedCards.any(
            (card) => card.status != 'succeeded' || card.version < 1,
          ) ||
          {
                ...cards.map((card) => card.id),
                ...completedCards.map((card) => card.id),
              }.length !=
              cards.length + completedCards.length ||
          resolvedCounts.entries.any(
            (entry) =>
                !{
                  'succeeded',
                  'rejected',
                  'cancelled',
                  'expired',
                  'failed',
                }.contains(entry.key) ||
                entry.value < 0,
          )) {
        throw const FormatException('Invalid confirmation state');
      }
      return ConversationConfirmations(
        cards: cards,
        completedCards: completedCards,
        resolvedCounts: resolvedCounts,
      );
    } on Object {
      throw const ApiException(
        code: 'INVALID_SUCCESS_RESPONSE',
        message: '草稿状态返回不完整，暂时无法恢复，请重新打开对话',
      );
    }
  }

  Future<AgentConfirmationCard> reviseMealPortions(
    AgentConfirmationCard card,
    List<Map<String, Object>> changes,
  ) async => AgentConfirmationCard.fromJson(
    expectJsonObject(
      await _apiClient.post(
        '/nutrition/pending-entries/${card.id}/portions',
        body: {'expected_version': card.version, 'changes': changes},
      ),
      context: '调整饮食草稿份量接口',
    ),
  );

  Future<String> confirmationStatus(AgentConfirmationCard card) async {
    final json = expectJsonObject(
      await _apiClient.get('/confirmations/${card.id}'),
      context: '核对确认结果接口',
    );
    final status = json['status'];
    if (json['id'] != card.id ||
        json['version'] is! int ||
        (json['version'] as int) < card.version ||
        status is! String ||
        !{
          'pending',
          'approved',
          'executing',
          'succeeded',
          'rejected',
          'cancelled',
          'expired',
          'failed',
        }.contains(status)) {
      throw const ApiException(
        code: 'INVALID_SUCCESS_RESPONSE',
        message: '确认状态返回不完整，暂时无法核实结果',
      );
    }
    return status;
  }

  Future<void> reject(AgentConfirmationCard card) async {
    final response = await _apiClient.post(
      '/confirmations/${card.id}/reject',
      body: {'expected_version': card.version, 'reason': '用户在移动端拒绝'},
    );
    _validateDecision(response, card, 'rejected');
  }

  static void _validateDecision(
    Object? response,
    AgentConfirmationCard card,
    String status,
  ) {
    final json = expectJsonObject(response, context: '确认结果接口');
    if (json['id'] != card.id ||
        json['status'] != status ||
        json['version'] is! int ||
        (json['version'] as int) <= card.version) {
      throw const ApiException(
        code: 'INVALID_SUCCESS_RESPONSE',
        message: '确认结果返回不完整，暂时无法核实是否已生效',
      );
    }
  }

  Future<List<AgentMemory>> listMemories() async {
    final json = expectJsonObject(
      await _apiClient.get('/memories', query: const {'limit': '50'}),
      context: 'AI 长期记忆列表接口',
    );
    return (json['list'] as List<dynamic>? ?? const [])
        .map(
          (item) =>
              AgentMemory.fromJson(Map<String, dynamic>.from(item as Map)),
        )
        .toList(growable: false);
  }

  Future<AgentMemory> createMemory({
    required String category,
    required String content,
  }) async {
    final json = expectJsonObject(
      await _apiClient.post(
        '/memories',
        body: {'category': category, 'content': content.trim()},
      ),
      context: '新增 AI 长期记忆接口',
    );
    return AgentMemory.fromJson(json);
  }

  Future<AgentMemory> updateMemory(
    AgentMemory memory, {
    required String category,
    required String content,
  }) async {
    final json = expectJsonObject(
      await _apiClient.patch(
        '/memories/${memory.id}',
        body: {
          'category': category,
          'content': content.trim(),
          'expected_version': memory.version,
        },
      ),
      context: '更新 AI 长期记忆接口',
    );
    return AgentMemory.fromJson(json);
  }

  Future<void> deleteMemory(AgentMemory memory) => _apiClient
      .delete(
        '/memories/${memory.id}',
        body: {'expected_version': memory.version},
      )
      .then((_) {});
}
