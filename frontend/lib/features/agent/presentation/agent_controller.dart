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
    Duration typingInterval = const Duration(milliseconds: 40),
    int typingBatchSize = 2,
  }) : assert(typingInterval > Duration.zero),
       assert(typingBatchSize > 0),
       _typingInterval = typingInterval,
       _typingBatchSize = typingBatchSize;

  final AgentRepository _repository;
  final ImageUploadAction? _imageUploader;
  final Duration _typingInterval;
  final int _typingBatchSize;
  final ListQueue<String> _assistantBuffer = ListQueue<String>();
  static const _replyDrainTimeout = Duration(seconds: 12);
  static const _recoveryReadTimeout = Duration(seconds: 8);
  static const _runRecoveryInterval = Duration(seconds: 12);

  Timer? _typingTimer;
  Completer<void>? _bufferDrained;
  StreamIterator<SseEvent>? _streamIterator;
  bool _disposed = false;
  int _conversationLoadGeneration = 0;
  bool _openingConversation = false;
  _AgentTurn? _lastTurn;

  String? conversationId;
  AgentConversation? currentConversation;
  List<AgentMessage> messages = const [];
  List<AgentConfirmationCard> confirmations = const [];
  List<AgentConfirmationCard> completedConfirmations = const [];
  final Map<String, int> _cardDisplayOrder = {};
  List<AgentConfirmationCard> get conversationCards {
    final cards = [...completedConfirmations, ...confirmations];
    for (final card in cards) {
      _cardDisplayOrder.putIfAbsent(card.id, () => _cardDisplayOrder.length);
    }
    cards.sort(
      (left, right) =>
          _cardDisplayOrder[left.id]!.compareTo(_cardDisplayOrder[right.id]!),
    );
    return cards;
  }

  List<Object> get conversationItems {
    final bySequence = <int, List<AgentConfirmationCard>>{};
    final sequences = messages.map((message) => message.sequence).toSet();
    final fallback = messages.isEmpty ? 0 : messages.last.sequence;
    for (final card in conversationCards) {
      final sequence = sequences.contains(card.messageSequence)
          ? card.messageSequence!
          : fallback;
      bySequence.putIfAbsent(sequence, () => []).add(card);
    }
    return [
      for (final message in messages) ...[
        message,
        ...?bySequence[message.sequence],
      ],
      if (messages.isEmpty) ...?bySequence[0],
    ];
  }

  String? statusMessage;
  final Set<String> _decidingCards = {};
  bool isDeciding(AgentConfirmationCard card) =>
      _decidingCards.contains(card.id);
  List<UploadedImage> attachedImages = const [];
  List<Uint8List> pendingImageBytes = const [];
  bool sending = false;
  bool uploadingImage = false;
  String? errorMessage;
  String? activityLabel;

  String? get lastRunId => _lastTurn?.runId;
  bool get openingConversation => _openingConversation;
  bool get canRetryLastTurn =>
      !sending &&
      !_openingConversation &&
      _lastTurn?.needsVerification == true &&
      _lastTurn?.conversationId == conversationId;

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
        _openingConversation ||
        uploadingImage ||
        _disposed) {
      return;
    }
    final outgoingText = trimmed.isEmpty ? '请分析这些图片' : trimmed;
    final outgoingImages = attachedImages;
    final turn = _AgentTurn(
      clientTurnId: const Uuid().v4(),
      message: outgoingText,
      images: List.unmodifiable(outgoingImages),
      contextHints: Map.unmodifiable({
        'occurred_at': DateTime.now().toUtc().toIso8601String(),
      }),
    );
    _lastTurn = turn;
    attachedImages = const [];
    sending = true;
    errorMessage = null;
    statusMessage = null;
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

    try {
      if (conversationId == null) {
        currentConversation = await _repository.createConversation();
        conversationId = currentConversation!.id;
      }
      if (_disposed) return;
      turn.conversationId = conversationId!;
      await _streamTurn(turn);
    } on ApiException catch (error) {
      if (!_disposed) {
        await _handleInterruptedTurn(
          turn,
          error.message,
          errorCode: error.code,
        );
      }
    } on FormatException {
      if (!_disposed) {
        await _handleInterruptedTurn(turn, 'AI 私人教练返回了无法识别的事件，已保留收到的内容');
      }
    } finally {
      sending = false;
      _notifyListeners();
    }
  }

  Future<void> retryLastTurn() async {
    final turn = _lastTurn;
    if (!canRetryLastTurn || turn == null || _disposed) return;
    sending = true;
    errorMessage = null;
    statusMessage = null;
    activityLabel = '正在核实上次结果';
    _notifyListeners();
    try {
      if (turn.runId != null) {
        await _reconcileRun(turn);
      } else {
        // Replaying the same request identity does not create a new user turn.
        _resetTypingBuffer();
        await _streamTurn(turn, replay: true);
      }
    } on ApiException catch (error) {
      if (!_disposed) {
        await _handleInterruptedTurn(
          turn,
          error.message,
          errorCode: error.code,
        );
      }
    } on FormatException {
      if (!_disposed) {
        await _handleInterruptedTurn(turn, '处理结果暂时无法识别，请稍后再次核实');
      }
    } finally {
      if (!_disposed) {
        sending = false;
        activityLabel = null;
        _notifyListeners();
      }
    }
  }

  Future<void> _streamTurn(_AgentTurn turn, {bool replay = false}) async {
    activityLabel = replay ? '正在核实上次结果' : '正在理解你的问题';
    _notifyListeners();
    final iterator = StreamIterator<SseEvent>(
      _repository.sendMessage(
        conversationId: turn.conversationId!,
        message: turn.message,
        imageAssetIds: turn.images
            .map((image) => image.assetId)
            .toList(growable: false),
        clientTurnId: turn.clientTurnId,
        contextHints: turn.contextHints,
      ),
    );
    _streamIterator = iterator;
    final recovered = Completer<AgentRun>();
    Timer? recoveryTimer;
    var receivedTerminalEvent = false;
    var streamClosed = false;
    var readingRun = false;
    var progressGeneration = 0;
    var receivedText = false;
    late void Function() armRecovery;
    Future<void> checkRun() async {
      if (_disposed ||
          streamClosed ||
          receivedTerminalEvent ||
          recovered.isCompleted) {
        return;
      }
      final runId = turn.runId;
      if (readingRun || runId == null) {
        armRecovery();
        return;
      }
      final generation = progressGeneration;
      readingRun = true;
      try {
        final run = await _boundedRecovery(_repository.getRun(runId));
        if (!_disposed &&
            !streamClosed &&
            !receivedTerminalEvent &&
            identical(_lastTurn, turn) &&
            generation == progressGeneration &&
            run.id == runId &&
            run.conversationId == turn.conversationId &&
            !run.isRunning &&
            !recovered.isCompleted) {
          recovered.complete(run);
        }
      } on Object {
        // A failed status read does not replay the user's write or settle it.
        // The existing stream timeout still handles a broken connection.
      } finally {
        readingRun = false;
        if (recoveryTimer?.isActive != true) armRecovery();
      }
    }

    armRecovery = () {
      recoveryTimer?.cancel();
      if (!_disposed &&
          !streamClosed &&
          !receivedTerminalEvent &&
          !recovered.isCompleted) {
        recoveryTimer = Timer(
          _runRecoveryInterval,
          () => unawaited(checkRun()),
        );
      }
    };
    armRecovery();
    try {
      var startedReplayText = false;
      while (!_disposed) {
        final hasNext = await Future.any<bool>([
          iterator.moveNext(),
          recovered.future.then((_) => false),
        ]);
        if (_disposed) return;
        if (recovered.isCompleted) {
          receivedTerminalEvent = true;
          await _reconcileRun(turn, knownRun: await recovered.future);
          return;
        }
        if (!hasNext) break;
        final event = iterator.current;
        final decoded = jsonDecode(event.data);
        if (decoded is! Map<String, dynamic>) continue;
        final payload = decoded;
        progressGeneration++;
        armRecovery();
        switch (payload['event'] ?? event.event) {
          case 'run_started':
            final runId = payload['run_id'];
            if (runId is String && runId.isNotEmpty) turn.runId = runId;
            activityLabel = '正在读取相关资料';
            _notifyListeners();
          case 'node_completed':
            activityLabel = receivedText
                ? '正在回复'
                : _activityForNode(payload['node'] as String?);
            _notifyListeners();
          case 'message_delta':
            if (replay && !startedReplayText) {
              _replaceAssistantContent('');
              startedReplayText = true;
            }
            final delta = payload['delta'] as String? ?? '';
            receivedText = receivedText || delta.isNotEmpty;
            activityLabel = '正在回复';
            _enqueueAssistantDelta(delta);
          case 'completed':
            receivedTerminalEvent = true;
            final response = payload['response'];
            if (response is! Map<String, dynamic>) {
              throw const ApiException(
                code: 'INVALID_SUCCESS_RESPONSE',
                message: '回复结果返回不完整，请核实上次处理结果',
              );
            }
            // The business result is available now. Typing animation and history
            // synchronization must not indefinitely hide its confirmation cards.
            _readConfirmations(response);
            activityLabel = '正在回复';
            await _drainAssistantBuffer();
            if (_disposed) return;
            activityLabel = null;
            _finishAssistantMessage();
            if (response['message'] case final String message) {
              _replaceAssistantContent(message);
            }
            final responseError = _friendlyResponseFailure(response);
            if (responseError != null) {
              errorMessage = responseError;
              if (turn.images.isNotEmpty) {
                attachedImages = turn.images;
              }
            }
            turn.needsVerification = false;
          case 'cancelled':
            receivedTerminalEvent = true;
            await _drainAssistantBuffer();
            if (_disposed) return;
            activityLabel = null;
            _finishAssistantMessage();
            errorMessage = '本次回复已取消，已保留收到的内容';
            turn.needsVerification = false;
          case 'failed':
            receivedTerminalEvent = true;
            await _drainAssistantBuffer();
            if (_disposed) return;
            activityLabel = null;
            _finishAssistantMessage();
            errorMessage = _friendlyFailureMessage(payload);
            turn.needsVerification =
                payload['error_code'] == 'AGENT_TURN_IN_PROGRESS';
            if (turn.images.isNotEmpty) {
              attachedImages = turn.images;
            }
        }
        if (receivedTerminalEvent) break;
      }

      if (_disposed) return;
      if (!receivedTerminalEvent) {
        await _handleInterruptedTurn(turn, '连接中断，已保留收到的回复内容');
      } else if (turn.runId != null && errorMessage != null) {
        await _reconcileRun(turn);
      } else if (errorMessage == null) {
        await _recoverCanonicalMessages(ignoreErrors: true);
      }
    } finally {
      streamClosed = true;
      recoveryTimer?.cancel();
      if (identical(_streamIterator, iterator)) {
        _streamIterator = null;
      }
      unawaited(iterator.cancel());
    }
  }

  Future<void> _handleInterruptedTurn(
    _AgentTurn turn,
    String message, {
    String? errorCode,
  }) async {
    turn.needsVerification =
        turn.conversationId != null && errorCode != 'AGENT_TURN_CONFLICT';
    await _preserveInterruptedReply(message);
    if (_disposed || turn.runId == null) return;
    try {
      await _reconcileRun(turn);
    } on ApiException catch (error) {
      if (!_disposed) {
        errorMessage = '$message。上次结果暂时无法核实：${error.message}';
      }
    }
  }

  Future<void> _reconcileRun(_AgentTurn turn, {AgentRun? knownRun}) async {
    final AgentRun run =
        knownRun ??
        await _boundedRecovery<AgentRun>(_repository.getRun(turn.runId!));
    if (_disposed || !identical(_lastTurn, turn)) return;
    if (run.conversationId != turn.conversationId) {
      throw const ApiException(
        code: 'INVALID_SUCCESS_RESPONSE',
        message: '处理状态与当前对话不一致，暂时无法核实结果',
      );
    }
    if (run.isRunning) {
      turn.needsVerification = true;
      errorMessage = '上一条请求仍在处理中，请稍后点击“核实上次结果”。';
      await _restoreTurnConfirmations();
      return;
    }
    _flushAssistantBuffer();
    _finishAssistantMessage();
    activityLabel = null;
    final response = run.resultPayload;
    if (run.status == 'succeeded' &&
        (response == null ||
            response['message'] is! String ||
            (response['message'] as String).trim().isEmpty ||
            !{
              'completed',
              'needs_input',
              'partial',
              'failed',
            }.contains(response['status']))) {
      throw const ApiException(
        code: 'INVALID_SUCCESS_RESPONSE',
        message: '上次处理已结束，但回复内容返回不完整，请稍后核实',
      );
    }
    if (response != null) {
      if (response['message'] case final String message) {
        _replaceAssistantContent(message);
      }
      _readConfirmations(response);
    }
    errorMessage = switch (run.status) {
      'failed' => _friendlyFailureMessage({
        'error_code': run.errorCode,
        'message': run.errorMessage,
      }),
      'cancelled' => '上次请求已取消，请核对已保存的草稿和记录。',
      _ => response == null ? null : _friendlyResponseFailure(response),
    };
    await _recoverCanonicalMessages(ignoreErrors: true);
    if (_disposed) return;
    await _restoreTurnConfirmations();
    if (_disposed) return;
    turn.needsVerification = false;
    if (run.status == 'succeeded' && errorMessage == null) {
      statusMessage = '已核实并恢复上次处理结果。';
    }
  }

  Future<void> _restoreTurnConfirmations() async {
    final restored = await _boundedRecovery(
      _repository.restoreConfirmations(conversationId!),
    );
    if (!_disposed) {
      confirmations = restored.cards;
      completedConfirmations = restored.completedCards;
    }
  }

  void _settleCard(AgentConfirmationCard card, String status) {
    confirmations = confirmations
        .where((item) => item.id != card.id)
        .toList(growable: false);
    if (status == 'succeeded') {
      completedConfirmations = {
        for (final item in completedConfirmations) item.id: item,
        card.id: card.copyWith(status: status),
      }.values.toList(growable: false);
    }
  }

  Future<void> decide(
    AgentConfirmationCard card, {
    required bool approve,
  }) async {
    if (_disposed ||
        card.status != 'pending' ||
        completedConfirmations.any((item) => item.id == card.id) ||
        !_decidingCards.add(card.id)) {
      return;
    }
    final generation = _conversationLoadGeneration;
    final decisionConversationId = conversationId;
    errorMessage = null;
    statusMessage = null;
    _notifyListeners();
    try {
      if (approve) {
        await _repository.approve(card);
      } else {
        await _repository.reject(card);
      }
      if (_disposed ||
          generation != _conversationLoadGeneration ||
          decisionConversationId != conversationId) {
        return;
      }
      _settleCard(card, approve ? 'succeeded' : 'rejected');
    } on ApiException catch (error) {
      if (_disposed ||
          generation != _conversationLoadGeneration ||
          decisionConversationId != conversationId) {
        return;
      }
      var resolved = false;
      final uncertain =
          error.code == 'NETWORK_ERROR' ||
          error.code == 'REQUEST_TIMEOUT' ||
          error.code == 'INVALID_SUCCESS_RESPONSE' ||
          (error.statusCode ?? 0) >= 500;
      if (uncertain || error.code == 'CONFIRMATION_CONFLICT') {
        try {
          final status = await _repository.confirmationStatus(card);
          if (_disposed ||
              generation != _conversationLoadGeneration ||
              decisionConversationId != conversationId) {
            return;
          }
          if (status == 'succeeded' ||
              status == 'rejected' ||
              status == 'cancelled' ||
              status == 'expired') {
            _settleCard(card, status);
            statusMessage = switch (status) {
              'succeeded' => '已核实，记录已保存。',
              'expired' => '这份草稿已过期，未执行修改。请重新提出修改，核对新草稿后确认。',
              _ => '已核实：这份草稿已结束，未执行新的修改。',
            };
            resolved = true;
          }
        } on ApiException {
          // Preserve the same card and approval key while its outcome is unknown.
        }
      }
      if (!resolved) {
        errorMessage = uncertain
            ? '暂时无法核实确认结果，请稍后重试这张卡片；不要另建一份相同记录。'
            : error.message;
      }
    } finally {
      _decidingCards.remove(card.id);
    }
    _notifyListeners();
  }

  Future<bool> reviseMealPortions(
    AgentConfirmationCard card,
    List<Map<String, Object>> changes,
  ) async {
    if (_disposed ||
        sending ||
        card.status != 'pending' ||
        completedConfirmations.any((item) => item.id == card.id)) {
      return false;
    }
    sending = true;
    errorMessage = null;
    _notifyListeners();
    try {
      final revised = await _repository.reviseMealPortions(card, changes);
      if (_disposed) return false;
      confirmations = [
        for (final item in confirmations)
          if (item.id != card.id) item,
        revised.copyWith(messageSequence: card.messageSequence),
      ];
      return true;
    } on ApiException catch (error) {
      if (!_disposed) errorMessage = error.message;
      return false;
    } finally {
      if (!_disposed) {
        sending = false;
        _notifyListeners();
      }
    }
  }

  Future<List<AgentConversation>> listConversations({
    String status = 'active',
  }) async {
    errorMessage = null;
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
    final generation = ++_conversationLoadGeneration;
    _openingConversation = true;
    errorMessage = null;
    statusMessage = null;
    activityLabel = '正在读取历史对话';
    _notifyListeners();
    try {
      final history = await _repository.listMessages(conversation.id);
      if (_disposed || generation != _conversationLoadGeneration) return false;
      messages = history;
      _lastTurn = null;
      currentConversation = conversation;
      conversationId = conversation.id;
      confirmations = const [];
      completedConfirmations = const [];
      _cardDisplayOrder.clear();
      try {
        final restored = await _repository.restoreConfirmations(
          conversation.id,
        );
        if (_disposed || generation != _conversationLoadGeneration) {
          return false;
        }
        confirmations = restored.cards;
        completedConfirmations = restored.completedCards;
        final counts = restored.resolvedCounts;
        final parts = <String>[
          if (restored.cards.isNotEmpty) '已恢复 ${restored.cards.length} 份待确认草稿',
          if ((counts['succeeded'] ?? 0) > 0) '${counts['succeeded']} 份已确认生效',
          if ((counts['rejected'] ?? 0) + (counts['cancelled'] ?? 0) > 0)
            '${(counts['rejected'] ?? 0) + (counts['cancelled'] ?? 0)} 份已取消或拒绝',
          if ((counts['expired'] ?? 0) > 0) '${counts['expired']} 份已过期',
          if ((counts['failed'] ?? 0) > 0) '${counts['failed']} 份执行失败',
        ];
        statusMessage = parts.isEmpty ? null : '${parts.join('，')}。';
      } on ApiException catch (error) {
        if (_disposed || generation != _conversationLoadGeneration) {
          return false;
        }
        errorMessage = '聊天记录已加载，但草稿状态暂时无法核实。${error.message} 请重新打开对话重试。';
      }
      activityLabel = null;
      _notifyListeners();
      return true;
    } on ApiException catch (error) {
      if (_disposed || generation != _conversationLoadGeneration) return false;
      activityLabel = null;
      errorMessage = error.message;
      _notifyListeners();
      return false;
    } finally {
      if (generation == _conversationLoadGeneration) {
        _openingConversation = false;
      }
    }
  }

  void startNewConversation() {
    if (sending || _disposed) return;
    _conversationLoadGeneration++;
    _openingConversation = false;
    currentConversation = null;
    conversationId = null;
    _lastTurn = null;
    messages = const [];
    confirmations = const [];
    completedConfirmations = const [];
    _cardDisplayOrder.clear();
    errorMessage = null;
    statusMessage = null;
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
    return _setConversationStatus(conversation, 'archived');
  }

  Future<bool> restoreConversation(AgentConversation conversation) async {
    return _setConversationStatus(conversation, 'active');
  }

  Future<bool> _setConversationStatus(
    AgentConversation conversation,
    String status,
  ) async {
    if (_disposed) return false;
    if (sending && conversationId == conversation.id) {
      errorMessage = '这段对话还在回复中，请等回复结束后再操作。';
      _notifyListeners();
      return false;
    }
    try {
      AgentConversation updated;
      try {
        updated = await _repository.updateConversation(
          conversation,
          status: status,
        );
      } on ApiException catch (error) {
        if (error.code != 'AGENT_CONVERSATION_CONFLICT') rethrow;
        // Title generation or another completed turn can advance the version.
        // Re-read once, then apply only the requested status to the same ID.
        final latest = await _repository.getConversation(conversation.id);
        updated = latest.status == status
            ? latest
            : await _repository.updateConversation(latest, status: status);
      }
      if (_disposed) return false;
      errorMessage = null;
      if (conversationId == conversation.id) {
        if (status == 'archived') {
          startNewConversation();
        } else {
          currentConversation = updated;
        }
      }
      _notifyListeners();
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
    // Keep bursts and the final buffered tail at the same display pace.
    for (var index = 0; index < _typingBatchSize; index += 1) {
      if (_assistantBuffer.isEmpty) break;
      batch.write(_assistantBuffer.removeFirst());
    }
    _appendAssistantDelta(batch.toString());
    if (_assistantBuffer.isEmpty) {
      _completeBufferDrain();
    }
  }

  Future<void> _drainAssistantBuffer() {
    if (_assistantBuffer.isEmpty || _disposed) return Future<void>.value();
    final existing = _bufferDrained;
    if (existing != null && !existing.isCompleted) return existing.future;

    final completer = Completer<void>();
    _bufferDrained = completer;
    _ensureTypingTimer();
    return completer.future.timeout(
      _replyDrainTimeout,
      onTimeout: _flushAssistantBuffer,
    );
  }

  void _flushAssistantBuffer() {
    final remaining = _assistantBuffer.join();
    _resetTypingBuffer();
    if (!_disposed && remaining.isNotEmpty) _appendAssistantDelta(remaining);
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

  void _replaceAssistantContent(String content) {
    if (messages.isEmpty || messages.last.role != 'assistant') return;
    final updated = messages.last.copyWith(content: content, pending: false);
    messages = [...messages.sublist(0, messages.length - 1), updated];
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
    final rawMessage = payload['message'];
    if (rawMessage is String &&
        RegExp(r'[\u3400-\u9fff]').hasMatch(rawMessage)) {
      return rawMessage;
    }
    return switch (errorCode) {
      'AgentIntentRoutingError' => '暂时无法理解这个问题，请稍后重试',
      'AgentResponseSynthesisError' ||
      'GeneralQuestionResponseError' => 'AI 私人教练暂时无法生成回复，请稍后重试',
      _ => 'AI 私人教练暂时不可用，请稍后重试',
    };
  }

  String? _friendlyResponseFailure(Map<String, dynamic> response) {
    if (response['status'] != 'failed' && response['status'] != 'partial') {
      return null;
    }

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
        if (error is Map<String, dynamic> &&
            error['code'] == 'TRAINING_PLAN_DRAFT_INVALID') {
          return '训练计划草稿未通过校验，请调整要求后重试';
        }
        if (error is Map<String, dynamic> &&
            error['code'] == 'NUTRITION_TARGET_DRAFT_NOT_CREATED') {
          return '饮食目标尚未保存，现有目标没有变化；可查看回复中的建议后重试';
        }
        if (error is Map<String, dynamic> &&
            error['code'] == 'TRAINING_PLAN_DRAFT_NOT_CREATED') {
          return 'AI 未能创建可确认的训练计划草稿，请稍后重试';
        }
        if (error is Map<String, dynamic>) {
          final message = error['message'];
          if (message is String &&
              RegExp(r'[\u3400-\u9fff]').hasMatch(message)) {
            return message;
          }
        }
      }
    }
    return response['status'] == 'partial' ? null : '这次请求暂时无法处理，请核对记录后重试';
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
    if (cards == null) return;
    if (cards is! List<dynamic> ||
        cards.any(
          (card) =>
              card is! Map<String, dynamic> ||
              card['confirmation_id'] is! String ||
              (card['confirmation_id'] as String).isEmpty ||
              card['operation_type'] is! String ||
              card['status'] is! String ||
              card['impact'] is! String ||
              card['version'] is! int ||
              (card['version'] as int) < 1,
        )) {
      throw const ApiException(
        code: 'INVALID_SUCCESS_RESPONSE',
        message: '回复中的草稿状态返回不完整，请核实上次处理结果',
      );
    }
    final draftsByCardId = <String, Map<String, dynamic>>{};
    final removedIds = <String>{};
    final results = response['analysis_results'];
    if (results is List<dynamic>) {
      for (final result in results) {
        if (result is! Map<String, dynamic>) continue;
        final operations = result['operation_results'];
        if (operations is! List<dynamic>) continue;
        for (final operation in operations) {
          if (operation is! Map<String, dynamic>) continue;
          final confirmation = operation['confirmation'];
          if (operation['status'] == 'cancelled' && confirmation is Map) {
            final id = confirmation['confirmation_id'];
            if (id is String) removedIds.add(id);
          }
          final draft = operation['draft'];
          if (confirmation is! Map<String, dynamic> || draft is! Map) continue;
          final cardId = confirmation['confirmation_id'];
          if (cardId is String) {
            draftsByCardId[cardId] = Map<String, dynamic>.from(draft);
          }
        }
      }
    }
    final knownAnchors = {
      for (final card in [...confirmations, ...completedConfirmations])
        card.id: card.messageSequence,
    };
    final incoming = cards
        .map((item) {
          final json = item as Map<String, dynamic>;
          return AgentConfirmationCard.fromJson(
            json,
            draft: draftsByCardId[json['confirmation_id']],
          ).copyWith(
            messageSequence:
                knownAnchors[json['confirmation_id']] ??
                (messages.isEmpty ? null : messages.last.sequence),
          );
        })
        .toList(growable: false);
    for (final card in incoming) {
      final replaced = card.after?['replaces_confirmation_id'];
      if (replaced is String) removedIds.add(replaced);
    }
    confirmations = {
      for (final card in confirmations)
        if (!removedIds.contains(card.id)) card.id: card,
      for (final card in incoming)
        if (card.status == 'pending' &&
            !completedConfirmations.any((completed) => completed.id == card.id))
          card.id: card,
    }.values.toList(growable: false);
    _notifyListeners();
  }

  Future<void> _recoverCanonicalMessages({bool ignoreErrors = false}) async {
    final id = conversationId;
    if (id == null) return;
    try {
      final localImages = <String, Uint8List>{
        for (final message in messages) ...message.localImageBytes,
      };
      final canonical = await _boundedRecovery(_repository.listMessages(id));
      if (_disposed || conversationId != id) return;
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

  Future<T> _boundedRecovery<T>(Future<T> read) => read.timeout(
    _recoveryReadTimeout,
    onTimeout: () => throw const ApiException(
      code: 'REQUEST_TIMEOUT',
      message: '暂时无法核实上次结果，请稍后再试；不要重复记录。',
    ),
  );

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

class _AgentTurn {
  _AgentTurn({
    required this.clientTurnId,
    required this.message,
    required this.images,
    required this.contextHints,
  });

  final String clientTurnId;
  final String message;
  final List<UploadedImage> images;
  final Map<String, Object> contextHints;
  String? conversationId;
  String? runId;
  bool needsVerification = true;
}
