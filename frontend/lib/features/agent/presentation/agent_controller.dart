import 'dart:async';
import 'dart:collection';
import 'dart:convert';

import 'package:characters/characters.dart';
import 'package:flutter/foundation.dart';
import 'package:uuid/uuid.dart';

import '../../../core/network/api_exception.dart';
import '../../../core/network/sse_event.dart';
import '../../../core/media/image_upload.dart';
import '../data/agent_repository.dart';
import '../domain/agent_models.dart';

typedef ImageUploadAction = Future<UploadedImage> Function(Uint8List bytes);

class AgentController extends ChangeNotifier {
  AgentController(
    this._repository, {
    this._imageUploader,
    Duration typingInterval = const Duration(milliseconds: 30),
    int maximumTypingBatchSize = 12,
  }) : assert(typingInterval > Duration.zero),
       assert(maximumTypingBatchSize > 0),
       _typingInterval = typingInterval,
       _maximumTypingBatchSize = maximumTypingBatchSize;

  final AgentRepository _repository;
  final ImageUploadAction? _imageUploader;
  final Duration _typingInterval;
  final int _maximumTypingBatchSize;
  final ListQueue<String> _assistantBuffer = ListQueue<String>();

  Timer? _typingTimer;
  Completer<void>? _bufferDrained;
  StreamIterator<SseEvent>? _streamIterator;
  bool _disposed = false;

  String? conversationId;
  AgentConversation? currentConversation;
  List<AgentMessage> messages = const [];
  List<AgentConfirmationCard> confirmations = const [];
  List<UploadedImage> attachedImages = const [];
  List<Uint8List> pendingImageBytes = const [];
  bool sending = false;
  bool uploadingImage = false;
  String? errorMessage;
  String? activityLabel;

  bool get canAttachImage =>
      !sending &&
      !uploadingImage &&
      attachedImages.length + pendingImageBytes.length < 4;

  Future<void> addImageBytes(Uint8List bytes) async {
    if (_disposed || !canAttachImage) return;
    final uploader = _imageUploader;
    if (uploader == null) {
      errorMessage = '当前版本暂不支持发送图片';
      _notifyListeners();
      return;
    }

    pendingImageBytes = [...pendingImageBytes, bytes];
    uploadingImage = true;
    errorMessage = null;
    _notifyListeners();
    try {
      final uploaded = await uploader(bytes);
      if (_disposed) return;
      attachedImages = [...attachedImages, uploaded];
    } on ApiException catch (error) {
      if (!_disposed) errorMessage = _friendlyImageError(error);
    } on Object {
      if (!_disposed) errorMessage = '图片处理失败，请重新选择';
    } finally {
      if (!_disposed) {
        pendingImageBytes = pendingImageBytes
            .where((item) => !identical(item, bytes))
            .toList(growable: false);
        uploadingImage = false;
        _notifyListeners();
      }
    }
  }

  void removeAttachedImage(String assetId) {
    if (_disposed || sending || uploadingImage) return;
    attachedImages = attachedImages
        .where((image) => image.assetId != assetId)
        .toList(growable: false);
    _notifyListeners();
  }

  void reportImagePickerError() {
    if (_disposed) return;
    errorMessage = '无法读取所选图片，请重新选择';
    _notifyListeners();
  }

  Future<void> send(String text) async {
    final trimmed = text.trim();
    if ((trimmed.isEmpty && attachedImages.isEmpty) ||
        sending ||
        uploadingImage ||
        _disposed) {
      return;
    }
    final outgoingText = trimmed.isEmpty ? '请分析这些图片' : trimmed;
    final outgoingImages = attachedImages;
    attachedImages = const [];
    sending = true;
    errorMessage = null;
    activityLabel = '正在准备对话';
    _resetTypingBuffer();

    final optimisticUser = AgentMessage(
      id: const Uuid().v4(),
      role: 'user',
      content: outgoingText,
      sequence: messages.length + 1,
      createdAt: DateTime.now(),
      imageAssetIds: outgoingImages
          .map((image) => image.assetId)
          .toList(growable: false),
      localImageBytes: {
        for (final image in outgoingImages) image.assetId: image.bytes,
      },
    );
    final optimisticAssistant = AgentMessage(
      id: const Uuid().v4(),
      role: 'assistant',
      content: '',
      sequence: messages.length + 2,
      createdAt: DateTime.now(),
      pending: true,
    );
    messages = [...messages, optimisticUser, optimisticAssistant];
    _notifyListeners();

    StreamIterator<SseEvent>? iterator;
    try {
      if (conversationId == null) {
        currentConversation = await _repository.createConversation();
        conversationId = currentConversation!.id;
      }
      if (_disposed) return;
      activityLabel = '正在理解你的问题';
      _notifyListeners();

      iterator = StreamIterator<SseEvent>(
        _repository.sendMessage(
          conversationId: conversationId!,
          message: outgoingText,
          imageAssetIds: outgoingImages
              .map((image) => image.assetId)
              .toList(growable: false),
        ),
      );
      _streamIterator = iterator;
      var receivedTerminalEvent = false;
      while (!_disposed && await iterator.moveNext()) {
        final event = iterator.current;
        final decoded = jsonDecode(event.data);
        if (decoded is! Map<String, dynamic>) continue;
        final payload = decoded;
        switch (payload['event'] ?? event.event) {
          case 'run_started':
            activityLabel = '正在分析训练数据';
            _notifyListeners();
          case 'node_completed':
            activityLabel = _activityForNode(payload['node'] as String?);
            _notifyListeners();
          case 'message_delta':
            final delta = payload['delta'] as String? ?? '';
            activityLabel = '正在回复';
            _enqueueAssistantDelta(delta);
          case 'completed':
            receivedTerminalEvent = true;
            await _drainAssistantBuffer();
            if (_disposed) return;
            activityLabel = null;
            _finishAssistantMessage();
            final response = payload['response'];
            if (response is Map<String, dynamic>) {
              _readConfirmations(response);
              final responseError = _friendlyResponseFailure(response);
              if (responseError != null) {
                errorMessage = responseError;
                if (outgoingImages.isNotEmpty) {
                  attachedImages = outgoingImages;
                }
              }
            }
          case 'cancelled':
            receivedTerminalEvent = true;
            await _drainAssistantBuffer();
            if (_disposed) return;
            activityLabel = null;
            _finishAssistantMessage();
            errorMessage = '本次回复已取消，已保留收到的内容';
          case 'failed':
            receivedTerminalEvent = true;
            await _drainAssistantBuffer();
            if (_disposed) return;
            activityLabel = null;
            _finishAssistantMessage();
            errorMessage = _friendlyFailureMessage(payload);
            if (outgoingImages.isNotEmpty) {
              attachedImages = outgoingImages;
            }
        }
        if (receivedTerminalEvent) break;
      }

      if (_disposed) return;
      if (!receivedTerminalEvent) {
        await _preserveInterruptedReply('连接中断，已保留收到的回复内容');
      } else if (errorMessage == null) {
        await _recoverCanonicalMessages();
      }
    } on ApiException catch (error) {
      if (!_disposed) {
        await _preserveInterruptedReply(
          error.code == 'NETWORK_ERROR'
              ? '连接中断，已保留收到的回复内容，请稍后重试'
              : error.message,
        );
      }
    } on FormatException {
      if (!_disposed) {
        await _preserveInterruptedReply('AI 教练返回了无法识别的事件，已保留收到的内容');
      }
    } finally {
      if (identical(_streamIterator, iterator)) {
        _streamIterator = null;
      }
      if (iterator != null) unawaited(iterator.cancel());
      sending = false;
      _notifyListeners();
    }
  }

  Future<void> decide(
    AgentConfirmationCard card, {
    required bool approve,
  }) async {
    if (_disposed) return;
    try {
      if (approve) {
        await _repository.approve(card);
      } else {
        await _repository.reject(card);
      }
      confirmations = confirmations
          .where((item) => item.id != card.id)
          .toList(growable: false);
    } on ApiException catch (error) {
      errorMessage = error.message;
    }
    _notifyListeners();
  }

  Future<List<AgentConversation>> listConversations({
    String status = 'active',
  }) async {
    try {
      return await _repository.listConversations(status: status);
    } on ApiException catch (error) {
      errorMessage = error.message;
      _notifyListeners();
      return const [];
    }
  }

  Future<bool> openConversation(AgentConversation conversation) async {
    if (sending || _disposed) return false;
    errorMessage = null;
    activityLabel = '正在读取历史对话';
    _notifyListeners();
    try {
      messages = await _repository.listMessages(conversation.id);
      currentConversation = conversation;
      conversationId = conversation.id;
      confirmations = const [];
      activityLabel = null;
      _notifyListeners();
      return true;
    } on ApiException catch (error) {
      activityLabel = null;
      errorMessage = error.message;
      _notifyListeners();
      return false;
    }
  }

  void startNewConversation() {
    if (sending || _disposed) return;
    currentConversation = null;
    conversationId = null;
    messages = const [];
    confirmations = const [];
    errorMessage = null;
    activityLabel = null;
    _notifyListeners();
  }

  Future<bool> renameConversation(
    AgentConversation conversation,
    String title,
  ) async {
    try {
      final updated = await _repository.updateConversation(
        conversation,
        title: title,
      );
      if (currentConversation?.id == updated.id) currentConversation = updated;
      _notifyListeners();
      return true;
    } on ApiException catch (error) {
      errorMessage = error.message;
      _notifyListeners();
      return false;
    }
  }

  Future<bool> archiveConversation(AgentConversation conversation) async {
    try {
      await _repository.updateConversation(conversation, status: 'archived');
      if (conversationId == conversation.id) startNewConversation();
      return true;
    } on ApiException catch (error) {
      errorMessage = error.message;
      _notifyListeners();
      return false;
    }
  }

  Future<bool> deleteConversation(AgentConversation conversation) async {
    try {
      await _repository.deleteConversation(conversation);
      if (conversationId == conversation.id) startNewConversation();
      return true;
    } on ApiException catch (error) {
      errorMessage = error.message;
      _notifyListeners();
      return false;
    }
  }

  Future<List<AgentMemory>> listMemories() async {
    try {
      return await _repository.listMemories();
    } on ApiException catch (error) {
      errorMessage = error.message;
      _notifyListeners();
      return const [];
    }
  }

  Future<bool> createMemory({
    required String category,
    required String content,
  }) async {
    try {
      await _repository.createMemory(category: category, content: content);
      return true;
    } on ApiException catch (error) {
      errorMessage = error.message;
      _notifyListeners();
      return false;
    }
  }

  Future<bool> updateMemory(
    AgentMemory memory, {
    required String category,
    required String content,
  }) async {
    try {
      await _repository.updateMemory(
        memory,
        category: category,
        content: content,
      );
      return true;
    } on ApiException catch (error) {
      errorMessage = error.message;
      _notifyListeners();
      return false;
    }
  }

  Future<bool> deleteMemory(AgentMemory memory) async {
    try {
      await _repository.deleteMemory(memory);
      return true;
    } on ApiException catch (error) {
      errorMessage = error.message;
      _notifyListeners();
      return false;
    }
  }

  void _enqueueAssistantDelta(String delta) {
    if (delta.isEmpty || _disposed) return;
    _assistantBuffer.addAll(delta.characters);
    _ensureTypingTimer();
  }

  void _ensureTypingTimer() {
    if (_disposed || _typingTimer != null || _assistantBuffer.isEmpty) return;
    _typingTimer = Timer.periodic(_typingInterval, (_) => _typingTick());
  }

  void _typingTick() {
    if (_disposed) {
      _stopTypingTimer();
      return;
    }
    if (_assistantBuffer.isEmpty) {
      _completeBufferDrain();
      return;
    }

    final batch = StringBuffer();
    final batchSize = _typingBatchSize(_assistantBuffer.length);
    for (var index = 0; index < batchSize; index += 1) {
      if (_assistantBuffer.isEmpty) break;
      batch.write(_assistantBuffer.removeFirst());
    }
    _appendAssistantDelta(batch.toString());
    if (_assistantBuffer.isEmpty) {
      _completeBufferDrain();
    }
  }

  int _typingBatchSize(int backlog) {
    final adaptiveSize = (backlog / 28).ceil();
    return adaptiveSize.clamp(1, _maximumTypingBatchSize);
  }

  Future<void> _drainAssistantBuffer() {
    if (_assistantBuffer.isEmpty || _disposed) return Future<void>.value();
    final existing = _bufferDrained;
    if (existing != null && !existing.isCompleted) return existing.future;

    final completer = Completer<void>();
    _bufferDrained = completer;
    _ensureTypingTimer();
    return completer.future;
  }

  void _completeBufferDrain() {
    _stopTypingTimer();
    final completer = _bufferDrained;
    _bufferDrained = null;
    if (completer != null && !completer.isCompleted) {
      completer.complete();
    }
  }

  void _stopTypingTimer() {
    _typingTimer?.cancel();
    _typingTimer = null;
  }

  void _resetTypingBuffer() {
    _stopTypingTimer();
    _assistantBuffer.clear();
    final completer = _bufferDrained;
    _bufferDrained = null;
    if (completer != null && !completer.isCompleted) {
      completer.complete();
    }
  }

  void _appendAssistantDelta(String delta) {
    if (messages.isEmpty || messages.last.role != 'assistant') return;
    final updated = messages.last.copyWith(
      content: '${messages.last.content}$delta',
    );
    messages = [...messages.sublist(0, messages.length - 1), updated];
    _notifyListeners();
  }

  void _finishAssistantMessage() {
    if (messages.isEmpty || messages.last.role != 'assistant') return;
    final updated = messages.last.copyWith(pending: false);
    messages = [...messages.sublist(0, messages.length - 1), updated];
    _notifyListeners();
  }

  Future<void> _preserveInterruptedReply(String message) async {
    await _drainAssistantBuffer();
    if (_disposed) return;
    activityLabel = null;
    _finishAssistantMessage();
    errorMessage = message;
    _notifyListeners();
  }

  String _activityForNode(String? node) => switch (node) {
    'plan_request' => '正在制定回答思路',
    'execute_branches' => '正在读取相关数据',
    'validate_safety' => '正在检查建议',
    'synthesize_response' => '正在组织回复',
    _ => '正在处理',
  };

  String _friendlyFailureMessage(Map<String, dynamic> payload) {
    final errorCode = payload['error_code'];
    if (errorCode == 'VISION_MODEL_BUSY') {
      return '视觉评估服务当前繁忙，照片已保留，可以直接重新发送';
    }
    if (errorCode == 'VISION_ASSESSMENT_INVALID') {
      return '视觉模型返回不完整，照片已保留，可以直接重新发送';
    }
    final rawMessage = payload['message'] as String?;
    if (rawMessage != null && RegExp(r'[\u3400-\u9fff]').hasMatch(rawMessage)) {
      return rawMessage;
    }
    return switch (errorCode) {
      'AgentIntentRoutingError' => '暂时无法理解这个问题，请稍后重试',
      'AgentResponseSynthesisError' ||
      'GeneralQuestionResponseError' => 'AI 教练暂时无法生成回复，请稍后重试',
      _ => 'AI 教练暂时不可用，请稍后重试',
    };
  }

  String? _friendlyResponseFailure(Map<String, dynamic> response) {
    if (response['status'] != 'failed') return null;

    final results = response['analysis_results'];
    if (results is List<dynamic>) {
      for (final result in results) {
        if (result is! Map<String, dynamic>) continue;
        final error = result['error'];
        if (error is Map<String, dynamic> &&
            error['code'] == 'VISION_MODEL_BUSY') {
          return '视觉评估服务当前繁忙，照片已保留，可以直接重新发送';
        }
        if (error is Map<String, dynamic> &&
            error['code'] == 'VISION_ASSESSMENT_INVALID') {
          return '视觉模型返回不完整，照片已保留，可以直接重新发送';
        }
      }
    }
    return '这次评估没有完成，请稍后重试';
  }

  String _friendlyImageError(ApiException error) => switch (error.code) {
    'IMAGE_PREPARATION_FAILED' ||
    'IMAGE_DIRECT_UPLOAD_FAILED' ||
    'IMAGE_PROCESSING_FAILED' => error.message,
    'IMAGE_STORAGE_UNAVAILABLE' => '图片服务暂时不可用，请稍后重试',
    'NETWORK_ERROR' => '图片上传失败，请检查网络后重试',
    _ =>
      RegExp(r'[\u3400-\u9fff]').hasMatch(error.message)
          ? error.message
          : '图片上传失败，请稍后重试',
  };

  void _readConfirmations(Map<String, dynamic> response) {
    final cards = response['confirmation_cards'];
    if (cards is! List<dynamic>) return;
    confirmations = cards
        .map(
          (item) =>
              AgentConfirmationCard.fromJson(item as Map<String, dynamic>),
        )
        .toList(growable: false);
    _notifyListeners();
  }

  Future<void> _recoverCanonicalMessages({bool ignoreErrors = false}) async {
    final id = conversationId;
    if (id == null) return;
    try {
      final localImages = <String, Uint8List>{
        for (final message in messages) ...message.localImageBytes,
      };
      final canonical = await _repository.listMessages(id);
      messages = canonical
          .map(
            (message) => message.copyWith(
              localImageBytes: {
                for (final assetId in message.imageAssetIds)
                  assetId: ?localImages[assetId],
              },
            ),
          )
          .toList(growable: false);
    } on Object {
      if (!ignoreErrors) rethrow;
    }
  }

  void _notifyListeners() {
    if (!_disposed) notifyListeners();
  }

  @override
  void dispose() {
    if (_disposed) return;
    _disposed = true;
    _resetTypingBuffer();
    final iterator = _streamIterator;
    _streamIterator = null;
    if (iterator != null) unawaited(iterator.cancel());
    super.dispose();
  }
}
