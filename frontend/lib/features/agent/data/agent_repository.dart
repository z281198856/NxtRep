import 'package:uuid/uuid.dart';

import '../../../core/network/api_client.dart';
import '../../../core/network/sse_event.dart';
import '../domain/agent_models.dart';

class AgentRepository {
  AgentRepository(this._apiClient, {Uuid? uuid}) : _uuid = uuid ?? const Uuid();

  final ApiClient _apiClient;
  final Uuid _uuid;

  Future<AgentConversation> createConversation() async {
    final json = expectJsonObject(
      await _apiClient.post('/agent/conversations', body: {'title': null}),
      context: 'AI 教练会话接口',
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
      context: 'AI 教练会话列表接口',
    );
    return (json['list'] as List<dynamic>? ?? const [])
        .map(
          (item) => AgentConversation.fromJson(
            Map<String, dynamic>.from(item as Map),
          ),
        )
        .toList(growable: false);
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
      context: '更新 AI 教练会话接口',
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
    final json = expectJsonObject(
      await _apiClient.get(
        '/agent/conversations/$conversationId/messages',
        query: {'after_sequence': '0', 'limit': '100'},
      ),
      context: 'AI 教练消息接口',
    );
    final values = json['list'] as List<dynamic>;
    return values
        .map((item) => AgentMessage.fromJson(item as Map<String, dynamic>))
        .toList(growable: false);
  }

  Stream<SseEvent> sendMessage({
    required String conversationId,
    required String message,
    List<String> imageAssetIds = const [],
  }) => _apiClient.postSse(
    '/agent/conversations/$conversationId/messages',
    query: const {'granularity': 'chunk'},
    body: {
      'message': message,
      'image_asset_ids': imageAssetIds,
      'context_hints': const <String, Object>{},
    },
  );

  Future<void> approve(AgentConfirmationCard card) async {
    await _apiClient.post(
      '/confirmations/${card.id}/approve',
      idempotencyKey: _uuid.v4(),
      body: {'expected_version': card.version},
    );
  }

  Future<void> reject(AgentConfirmationCard card) async {
    await _apiClient.post(
      '/confirmations/${card.id}/reject',
      body: {'expected_version': card.version, 'reason': '用户在移动端拒绝'},
    );
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
