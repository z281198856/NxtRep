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
}
