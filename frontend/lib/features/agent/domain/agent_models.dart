import 'dart:typed_data';

class AgentConversation {
  const AgentConversation({required this.id, required this.version});

  factory AgentConversation.fromJson(Map<String, dynamic> json) =>
      AgentConversation(
        id: json['id'] as String,
        version: json['version'] as int,
      );

  final String id;
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

class AgentConfirmationCard {
  const AgentConfirmationCard({
    required this.id,
    required this.operationType,
    required this.status,
    required this.impact,
    required this.version,
  });

  factory AgentConfirmationCard.fromJson(Map<String, dynamic> json) =>
      AgentConfirmationCard(
        id: json['confirmation_id'] as String,
        operationType: json['operation_type'] as String,
        status: json['status'] as String,
        impact: json['impact'] as String,
        version: json['version'] as int,
      );

  final String id;
  final String operationType;
  final String status;
  final String impact;
  final int version;
}
