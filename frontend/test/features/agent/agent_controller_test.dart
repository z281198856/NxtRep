import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nxtrep/core/config/api_config.dart';
import 'package:nxtrep/core/media/image_upload.dart';
import 'package:nxtrep/core/network/api_client.dart';
import 'package:nxtrep/core/network/sse_event.dart';
import 'package:nxtrep/features/agent/data/agent_repository.dart';
import 'package:nxtrep/features/agent/domain/agent_models.dart';
import 'package:nxtrep/features/agent/presentation/agent_controller.dart';

void main() {
  testWidgets(
    'shows the optimistic user message before conversation creation',
    (tester) async {
      final repository = _FakeAgentRepository();
      final creation = Completer<AgentConversation>();
      repository.creation = creation.future;
      final controller = AgentController(repository);
      addTearDown(controller.dispose);
      addTearDown(repository.close);

      final sendFuture = controller.send('  今天怎么练？  ');

      expect(controller.sending, isTrue);
      expect(controller.activityLabel, '正在准备对话');
      expect(controller.messages, hasLength(2));
      expect(controller.messages.first.content, '今天怎么练？');
      expect(controller.messages.last.content, isEmpty);
      expect(controller.messages.last.pending, isTrue);

      controller.dispose();
      creation.complete(
        const AgentConversation(id: 'conversation', version: 1),
      );
      await tester.pump();
      await sendFuture;
    },
  );

  testWidgets(
    'paces chunk deltas in order and drains them before canonical recovery',
    (tester) async {
      final repository = _FakeAgentRepository();
      const reply = '你好👋，这是持续显示的回答。';
      repository.canonicalMessages = _canonicalMessages(reply);
      repository.messageStream = Stream<SseEvent>.fromIterable([
        _event('message_delta', {'delta': '你好👋，这是'}),
        _event('message_delta', {'delta': '持续显示的回答。'}),
        _event('completed', {
          'response': {'message': reply},
        }),
      ]);
      final controller = AgentController(
        repository,
        typingInterval: const Duration(milliseconds: 30),
      );
      addTearDown(controller.dispose);
      addTearDown(repository.close);

      final sendFuture = controller.send('你好');
      await tester.pump();
      await tester.pump();

      expect(controller.messages.last.content, isEmpty);
      expect(controller.messages.last.pending, isTrue);
      expect(repository.listCalls, 0);

      await tester.pump(const Duration(milliseconds: 30));
      expect(controller.messages.last.content, isNotEmpty);
      expect(reply.startsWith(controller.messages.last.content), isTrue);
      expect(controller.messages.last.content, isNot(reply));
      expect(controller.messages.last.pending, isTrue);
      expect(repository.listCalls, 0);

      await tester.pump(const Duration(seconds: 2));
      await tester.pump();
      expect(controller.messages.last.content, reply);
      expect(repository.listCalls, 1);
      await sendFuture;

      expect(controller.messages.last.content, reply);
      expect(controller.messages.last.pending, isFalse);
      expect(repository.listCalls, 1);
      expect(controller.sending, isFalse);
      expect(controller.activityLabel, isNull);
    },
  );

  testWidgets(
    'uses adaptive batches instead of rebuilding for every character',
    (tester) async {
      final repository = _FakeAgentRepository();
      final reply = List<String>.filled(400, '练').join();
      repository.canonicalMessages = _canonicalMessages(reply);
      repository.messageStream = Stream<SseEvent>.fromIterable([
        _event('message_delta', {'delta': reply}),
        _event('completed', {
          'response': {'message': reply},
        }),
      ]);
      final controller = AgentController(
        repository,
        typingInterval: const Duration(milliseconds: 30),
      );
      addTearDown(controller.dispose);
      addTearDown(repository.close);
      var notifications = 0;
      controller.addListener(() => notifications += 1);

      final sendFuture = controller.send('生成计划');
      await tester.pump();
      await tester.pump();
      final beforeFirstTick = notifications;

      await tester.pump(const Duration(milliseconds: 30));
      final firstBatchLength = controller.messages.last.content.length;
      expect(firstBatchLength, greaterThan(1));
      expect(firstBatchLength, lessThan(reply.length));
      expect(notifications, beforeFirstTick + 1);

      await tester.pump(const Duration(seconds: 6));
      await tester.pump();
      await sendFuture;
      expect(controller.messages.last.content, reply);
      expect(notifications, lessThan(reply.length ~/ 2));
    },
  );

  testWidgets(
    'keeps received text when the SSE stream ends without a terminal event',
    (tester) async {
      final repository = _FakeAgentRepository();
      const partialReply = '这是已经收到的部分回复';
      repository.messageStream = Stream<SseEvent>.value(
        _event('message_delta', {'delta': partialReply}),
      );
      final controller = AgentController(
        repository,
        typingInterval: const Duration(milliseconds: 20),
      );
      addTearDown(controller.dispose);
      addTearDown(repository.close);

      final sendFuture = controller.send('继续');
      await tester.pump();
      await tester.pump();
      await tester.pump(const Duration(seconds: 1));
      await tester.pump();
      await sendFuture;

      expect(controller.messages.last.content, partialReply);
      expect(controller.messages.last.pending, isFalse);
      expect(controller.errorMessage, contains('连接中断'));
      expect(repository.listCalls, 0);
    },
  );

  testWidgets('maps backend agent failures to a helpful Chinese message', (
    tester,
  ) async {
    final repository = _FakeAgentRepository();
    repository.messageStream = Stream<SseEvent>.value(
      _event('failed', {
        'error_code': 'AgentIntentRoutingError',
        'message': 'Agent execution failed',
      }),
    );
    final controller = AgentController(repository);
    addTearDown(controller.dispose);
    addTearDown(repository.close);

    final sendFuture = controller.send('你好');
    await tester.pump();
    await tester.pump();
    await sendFuture;

    expect(controller.errorMessage, '暂时无法理解这个问题，请稍后重试');
    expect(controller.messages.last.pending, isFalse);
  });

  testWidgets('cancels the stream and typing timer safely on dispose', (
    tester,
  ) async {
    final repository = _FakeAgentRepository();
    final controller = AgentController(
      repository,
      typingInterval: const Duration(milliseconds: 20),
    );
    addTearDown(repository.close);

    final sendFuture = controller.send('开始');
    await tester.pump();
    repository.events.add(_event('message_delta', {'delta': '尚未排空的长回复内容'}));
    await tester.pump();

    controller.dispose();
    await tester.pump();
    await sendFuture;

    expect(tester.takeException(), isNull);
  });

  testWidgets('uploads selected images and includes their asset ids in chat', (
    tester,
  ) async {
    final repository = _FakeAgentRepository();
    repository.canonicalMessages = [
      AgentMessage(
        id: 'user-message',
        role: 'user',
        content: '看看动作姿势',
        sequence: 1,
        createdAt: DateTime.utc(2026, 9, 14),
        imageAssetIds: const ['image-1'],
      ),
      AgentMessage(
        id: 'assistant-message',
        role: 'assistant',
        content: '已收到图片',
        sequence: 2,
        createdAt: DateTime.utc(2026, 9, 14),
      ),
    ];
    repository.messageStream = Stream<SseEvent>.fromIterable([
      _event('completed', {
        'response': {'message': '已收到图片'},
      }),
    ]);
    final source = Uint8List.fromList([1, 2, 3]);
    final controller = AgentController(
      repository,
      imageUploader: (bytes) async => UploadedImage(
        assetId: 'image-1',
        bytes: bytes,
        contentType: 'image/jpeg',
      ),
    );
    addTearDown(controller.dispose);
    addTearDown(repository.close);

    await controller.addImageBytes(source);
    expect(controller.attachedImages, hasLength(1));

    final sendFuture = controller.send('看看动作姿势');
    await tester.pump();
    await tester.pump();
    await sendFuture;

    expect(repository.lastImageAssetIds, ['image-1']);
    expect(controller.attachedImages, isEmpty);
    expect(controller.messages.first.localImageBytes['image-1'], source);
  });

  testWidgets('shows a local image preview while upload is still running', (
    tester,
  ) async {
    final repository = _FakeAgentRepository();
    final upload = Completer<UploadedImage>();
    final source = Uint8List.fromList([4, 5, 6]);
    final controller = AgentController(
      repository,
      imageUploader: (_) => upload.future,
    );
    addTearDown(controller.dispose);
    addTearDown(repository.close);

    final uploadFuture = controller.addImageBytes(source);
    await tester.pump();

    expect(controller.uploadingImage, isTrue);
    expect(controller.pendingImageBytes, [source]);
    expect(controller.attachedImages, isEmpty);

    upload.complete(
      UploadedImage(
        assetId: 'image-preview',
        bytes: source,
        contentType: 'image/jpeg',
      ),
    );
    await uploadFuture;

    expect(controller.uploadingImage, isFalse);
    expect(controller.pendingImageBytes, isEmpty);
    expect(controller.attachedImages.single.assetId, 'image-preview');
  });

  testWidgets('keeps uploaded image when vision service is busy', (
    tester,
  ) async {
    final repository = _FakeAgentRepository();
    repository.messageStream = Stream<SseEvent>.value(
      _event('completed', {
        'response': {
          'message': '视觉评估服务当前繁忙，请稍后重试。',
          'status': 'failed',
          'analysis_results': [
            {
              'status': 'failed',
              'error': {
                'code': 'VISION_MODEL_BUSY',
                'message': '视觉评估服务当前繁忙，请稍后重试',
                'retryable': true,
              },
            },
          ],
        },
      }),
    );
    final source = Uint8List.fromList([7, 8, 9]);
    final controller = AgentController(
      repository,
      imageUploader: (bytes) async => UploadedImage(
        assetId: 'image-retry',
        bytes: bytes,
        contentType: 'image/jpeg',
      ),
    );
    addTearDown(controller.dispose);
    addTearDown(repository.close);

    await controller.addImageBytes(source);
    final sendFuture = controller.send('分析体态');
    await tester.pump();
    await tester.pump();
    await sendFuture;

    expect(controller.attachedImages.single.assetId, 'image-retry');
    expect(controller.errorMessage, contains('照片已保留'));
  });

  testWidgets('keeps uploaded image when streamed vision result is invalid', (
    tester,
  ) async {
    final repository = _FakeAgentRepository();
    repository.messageStream = Stream<SseEvent>.value(
      _event('failed', {
        'error_code': 'VISION_ASSESSMENT_INVALID',
        'message': '视觉模型未能返回完整评估结果',
      }),
    );
    final source = Uint8List.fromList([10, 11, 12]);
    final controller = AgentController(
      repository,
      imageUploader: (bytes) async => UploadedImage(
        assetId: 'image-invalid-retry',
        bytes: bytes,
        contentType: 'image/jpeg',
      ),
    );
    addTearDown(controller.dispose);
    addTearDown(repository.close);

    await controller.addImageBytes(source);
    final sendFuture = controller.send('评价一下二头');
    await tester.pump();
    await tester.pump();
    await sendFuture;

    expect(controller.attachedImages.single.assetId, 'image-invalid-retry');
    expect(controller.errorMessage, contains('照片已保留'));
  });
}

SseEvent _event(String event, Map<String, Object> payload) =>
    SseEvent(event: event, data: jsonEncode({'event': event, ...payload}));

List<AgentMessage> _canonicalMessages(String reply) => [
  AgentMessage(
    id: 'user-message',
    role: 'user',
    content: '你好',
    sequence: 1,
    createdAt: DateTime.utc(2026, 9, 14),
  ),
  AgentMessage(
    id: 'assistant-message',
    role: 'assistant',
    content: reply,
    sequence: 2,
    createdAt: DateTime.utc(2026, 9, 14),
  ),
];

class _FakeAgentRepository extends AgentRepository {
  _FakeAgentRepository()
    : super(
        ApiClient(
          config: ApiConfig(
            baseUri: Uri.parse('https://api.example.test/api/v1'),
          ),
          accessTokenProvider: () => 'access',
          httpClient: MockClient(
            (_) async => http.Response('not used by fake repository', 500),
          ),
        ),
      );

  final StreamController<SseEvent> events = StreamController<SseEvent>();
  Future<AgentConversation> creation = Future<AgentConversation>.value(
    const AgentConversation(id: 'conversation', version: 1),
  );
  List<AgentMessage> canonicalMessages = const [];
  Stream<SseEvent>? messageStream;
  int listCalls = 0;
  List<String> lastImageAssetIds = const [];

  @override
  Future<AgentConversation> createConversation() => creation;

  @override
  Stream<SseEvent> sendMessage({
    required String conversationId,
    required String message,
    List<String> imageAssetIds = const [],
  }) {
    lastImageAssetIds = imageAssetIds;
    return messageStream ?? events.stream;
  }

  @override
  Future<List<AgentMessage>> listMessages(String conversationId) async {
    listCalls += 1;
    return canonicalMessages;
  }

  void close() {
    if (!events.isClosed) unawaited(events.close());
  }
}
