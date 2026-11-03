import 'dart:typed_data';

class AgentConversation {
  const AgentConversation({
    required this.id,
    required this.version,
    this.title,
    this.status = 'active',
    this.summary,
    this.lastMessageAt,
    this.createdAt,
    this.titleSource = 'legacy',
  });

  factory AgentConversation.fromJson(Map<String, dynamic> json) =>
      AgentConversation(
        id: json['id'] as String,
        version: json['version'] as int,
        title: json['title'] as String?,
        status: json['status'] as String? ?? 'active',
        summary: json['summary'] as String?,
        titleSource: json['title_source'] as String? ?? 'legacy',
        createdAt: json['created_at'] == null
            ? null
            : DateTime.parse(json['created_at'] as String),
        lastMessageAt: json['last_message_at'] == null
            ? null
            : DateTime.parse(json['last_message_at'] as String),
      );

  final String id;
  final int version;
  final String? title;
  final String titleSource;
  final DateTime? createdAt;
  DateTime? get activityAt => lastMessageAt ?? createdAt;
  String get displayTitle =>
      title?.trim().isNotEmpty == true ? title!.trim() : '新对话';
  final String status;
  final String? summary;
  final DateTime? lastMessageAt;
}

class AgentMemory {
  const AgentMemory({
    required this.id,
    required this.category,
    required this.content,
    required this.source,
    required this.savedAt,
    required this.version,
  });

  factory AgentMemory.fromJson(Map<String, dynamic> json) => AgentMemory(
    id: json['id'] as String,
    category: json['category'] as String,
    content: json['content'] as String,
    source: json['source'] as String,
    savedAt: DateTime.parse(json['saved_at'] as String),
    version: json['version'] as int,
  );

  final String id;
  final String category;
  final String content;
  final String source;
  final DateTime savedAt;
  final int version;
}

class AgentMessage {
  const AgentMessage({
    required this.id,
    required this.role,
    required this.content,
    required this.sequence,
    required this.createdAt,
    this.imageAssetIds = const [],
    this.localImageBytes = const {},
    this.pending = false,
  });

  factory AgentMessage.fromJson(Map<String, dynamic> json) => AgentMessage(
    id: json['id'] as String,
    role: json['role'] as String,
    content: json['content'] as String,
    sequence: json['sequence'] as int,
    createdAt: DateTime.parse(json['created_at'] as String),
    imageAssetIds: (json['image_asset_ids'] as List<dynamic>? ?? const [])
        .cast<String>(),
  );

  final String id;
  final String role;
  final String content;
  final int sequence;
  final DateTime createdAt;
  final List<String> imageAssetIds;
  final Map<String, Uint8List> localImageBytes;
  final bool pending;

  AgentMessage copyWith({
    String? content,
    bool? pending,
    Map<String, Uint8List>? localImageBytes,
  }) => AgentMessage(
    id: id,
    role: role,
    content: content ?? this.content,
    sequence: sequence,
    createdAt: createdAt,
    imageAssetIds: imageAssetIds,
    localImageBytes: localImageBytes ?? this.localImageBytes,
    pending: pending ?? this.pending,
  );
}

class AgentRun {
  const AgentRun({
    required this.id,
    required this.conversationId,
    required this.status,
    this.resultPayload,
    this.errorCode,
    this.errorMessage,
  });

  factory AgentRun.fromJson(Map<String, dynamic> json) {
    final id = json['id'];
    final conversationId = json['conversation_id'];
    final status = json['status'];
    final result = json['result_payload'];
    if (id is! String ||
        id.isEmpty ||
        conversationId is! String ||
        conversationId.isEmpty ||
        status is! String ||
        !{
          'running',
          'cancel_requested',
          'succeeded',
          'failed',
          'cancelled',
        }.contains(status) ||
        (result != null && result is! Map) ||
        (json['error_code'] != null && json['error_code'] is! String) ||
        (json['error_message'] != null && json['error_message'] is! String)) {
      throw const FormatException('Invalid agent run');
    }
    return AgentRun(
      id: id,
      conversationId: conversationId,
      status: status,
      resultPayload: result == null ? null : Map<String, dynamic>.from(result),
      errorCode: json['error_code'] as String?,
      errorMessage: json['error_message'] as String?,
    );
  }

  final String id;
  final String conversationId;
  final String status;
  final Map<String, dynamic>? resultPayload;
  final String? errorCode;
  final String? errorMessage;

  bool get isRunning => status == 'running' || status == 'cancel_requested';
}

class AgentConfirmationCard {
  const AgentConfirmationCard({
    required this.id,
    required this.operationType,
    required this.status,
    required this.impact,
    required this.version,
    this.before,
    this.after,
    this.draft,
    this.messageSequence,
  });

  factory AgentConfirmationCard.fromJson(
    Map<String, dynamic> json, {
    Map<String, dynamic>? draft,
  }) => AgentConfirmationCard(
    id: json['confirmation_id'] as String,
    operationType: json['operation_type'] as String,
    status: json['status'] as String,
    impact: json['impact'] as String,
    version: json['version'] as int,
    messageSequence: json['message_sequence'] as int?,
    before: json['before'] is Map
        ? Map<String, dynamic>.from(json['before'] as Map)
        : null,
    after: json['after'] is Map
        ? Map<String, dynamic>.from(json['after'] as Map)
        : null,
    draft:
        draft ??
        (json['draft'] is Map
            ? Map<String, dynamic>.from(json['draft'] as Map)
            : null),
  );

  final String id;
  final String operationType;
  final String status;
  final String impact;
  final int version;
  final Map<String, dynamic>? after;
  final Map<String, dynamic>? before;
  final Map<String, dynamic>? draft;
  final int? messageSequence;

  AgentConfirmationCard copyWith({String? status, int? messageSequence}) =>
      AgentConfirmationCard(
        id: id,
        operationType: operationType,
        status: status ?? this.status,
        impact: impact,
        version: version,
        before: before,
        after: after,
        draft: draft,
        messageSequence: messageSequence ?? this.messageSequence,
      );
}

class ConversationConfirmations {
  const ConversationConfirmations({
    required this.cards,
    required this.resolvedCounts,
    this.completedCards = const [],
  });

  final List<AgentConfirmationCard> cards;
  final List<AgentConfirmationCard> completedCards;
  final Map<String, int> resolvedCounts;
}
