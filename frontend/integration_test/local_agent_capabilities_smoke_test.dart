import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:nxtrep/app/nxtrep_app.dart';
import 'package:nxtrep/core/config/api_config.dart';
import 'package:nxtrep/core/network/api_client.dart';
import 'package:nxtrep/core/network/api_exception.dart';
import 'package:nxtrep/core/network/sse_event.dart';
import 'package:nxtrep/core/storage/refresh_token_store.dart';
import 'package:nxtrep/features/auth/data/auth_repository.dart';
import 'package:nxtrep/features/agent/presentation/agent_page.dart';
import 'package:nxtrep/features/auth/domain/session_tokens.dart';
import 'package:nxtrep/features/auth/presentation/session_controller.dart';
import 'package:nxtrep/features/onboarding/data/onboarding_repository.dart';

const _username = String.fromEnvironment('E2E_USERNAME');
const _password = String.fromEnvironment('E2E_PASSWORD');
const _date = String.fromEnvironment('E2E_DATE');
const _sourceDate = String.fromEnvironment('E2E_SOURCE_DATE');
const _targetDate = String.fromEnvironment('E2E_TARGET_DATE');
const _mealMessage = String.fromEnvironment(
  'E2E_MEAL_MESSAGE',
  defaultValue: '我今天的午餐是麦当劳的两个双层吉士汉堡，请生成待确认草稿。',
);

void main() {
  final binding = IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  binding.framePolicy = LiveTestWidgetsFlutterBindingFramePolicy.onlyPumps;
  testWidgets('real backend: query records then approve text meal in App', (
    tester,
  ) async {
    expect(_username.isNotEmpty && _password.isNotEmpty, isTrue);
    final tokens = SessionTokens(_MemoryRefreshTokenStore());
    final api = _DiagnosticApiClient(
      config: ApiConfig(),
      accessTokenProvider: () => tokens.accessToken,
    );
    final auth = AuthRepository(apiClient: api, tokens: tokens);
    api.tokenRefresher = auth.refreshSession;
    final session = SessionController(
      authRepository: auth,
      onboardingRepository: OnboardingRepository(api),
    );
    addTearDown(api.close);
    await tester.pumpWidget(NxtRepApp(sessionController: session));
    await _waitFor(tester, find.text('欢迎回来'));
    await tester.enterText(find.byType(TextFormField).at(0), _username);
    await tester.enterText(find.byType(TextFormField).at(1), _password);
    await tester.tap(find.text('登录'));
    await _waitFor(tester, find.byType(NavigationBar));
    debugPrintSynchronously('Acceptance: disposable account reached home');
    await tester.tap(find.text('AI私人教练').last);
    await _waitFor(tester, find.byTooltip('发送'));
    await tester.enterText(
      find.byType(TextField).last,
      '请查我今天实际记录的热量和蛋白质，别用计划目标代替。',
    );
    await tester.pump();
    await tester.tap(find.byTooltip('发送'));
    await _waitFor(
      tester,
      find.textContaining('500', findRichText: true),
      attempts: 600,
    );
    await _waitForIdle(tester);
    debugPrintSynchronously('Acceptance: actual daily nutrition displayed');
    expect(find.text('回答'), findsNothing);
    expect(find.text('分析'), findsNothing);
    await _waitFor(tester, find.byTooltip('发送'));
    await tester.tap(find.byType(TextField).last);
    await tester.pump();
    await tester.enterText(find.byType(TextField).last, _mealMessage);
    await tester.pump();
    expect(
      tester.widget<TextField>(find.byType(TextField).last).controller!.text,
      _mealMessage,
    );
    await tester.tap(find.byTooltip('发送'));
    expect(
      tester.widget<AgentPage>(find.byType(AgentPage)).controller.sending,
      isTrue,
    );
    debugPrintSynchronously('Acceptance: text meal message dispatched');
    await _waitFor(tester, find.text('确认保存'), attempts: 600);
    await _waitForIdle(tester);
    expect(find.textContaining('合计约', findRichText: true), findsWidgets);
    debugPrintSynchronously(
      'Acceptance: text meal confirmation preview displayed',
    );
    final agentController = tester
        .widget<AgentPage>(find.byType(AgentPage))
        .controller;
    final originalCard = agentController.confirmations.single;
    final originalTotals =
        (originalCard.after!['preview'] as Map)['totals'] as Map;
    final originalKcal = double.parse(originalTotals['kcal'].toString());
    await tester.ensureVisible(find.text('调整份量'));
    await tester.tap(find.text('调整份量'));
    await tester.pumpAndSettle();
    final portionFields = find.byType(TextFormField);
    for (var index = 0; index < portionFields.evaluate().length; index++) {
      final field = tester.widget<TextFormField>(portionFields.at(index));
      final grams = double.parse(field.controller!.text);
      await tester.enterText(
        portionFields.at(index),
        (grams / 2).toStringAsFixed(3),
      );
    }
    await tester.tap(find.text('重新计算草稿'));
    await tester.pumpAndSettle();
    await _waitForIdle(tester);
    await tester.pump(const Duration(milliseconds: 500));
    final revised = agentController.confirmations.single;
    expect(revised.id, isNot(originalCard.id));
    final revisedKcal = double.parse(
      ((revised.after!['preview'] as Map)['totals'] as Map)['kcal'].toString(),
    );
    expect(revisedKcal, closeTo(originalKcal / 2, 0.1));
    debugPrintSynchronously(
      'Acceptance: portion editor replaced old card and halved nutrients',
    );
    await tester.ensureVisible(find.text('确认保存'));
    await tester.tap(find.text('确认保存'));
    for (var attempt = 0; attempt < 80; attempt++) {
      await tester.pump(const Duration(milliseconds: 500));
      if (find.text('确认保存').evaluate().isEmpty) break;
    }
    expect(find.text('确认保存'), findsNothing);
    final response = await api.get(
      '/nutrition/entries',
      query: {'date': _date},
    );
    expect(response, isA<List>());
    expect((response as List).length, 2);
    expect(
      response.whereType<Map>().where((entry) => entry['meal_type'] == 'lunch'),
      hasLength(1),
    );
    final lunch = response.whereType<Map>().singleWhere(
      (entry) => entry['meal_type'] == 'lunch',
    );
    final savedKcal = double.parse((lunch['totals'] as Map)['kcal'].toString());
    expect(savedKcal, closeTo(revisedKcal, 0.1));
    expect(
      savedKcal,
      lessThan(600),
      reason: 'Two portions must not be multiplied twice',
    );
    debugPrintSynchronously('Acceptance: approved meal persisted exactly once');
    await _sendFollowUp(tester, '先给晚餐草稿：100克熟米饭，先不要保存到正式记录。');
    await _waitFor(tester, find.text('确认保存'), attempts: 600);
    await _waitForIdle(tester);
    final cancellable = agentController.confirmations.single;
    await _sendFollowUp(tester, '碳水应该不超过六十克');
    expect(agentController.confirmations.single.id, cancellable.id);
    expect(agentController.messages.last.content, contains('碳水'));
    expect(agentController.messages.last.content, isNot(contains('长期记忆修改')));
    debugPrintSynchronously(
      'Acceptance: nutrient feedback read the meal and preserved its pending card',
    );
    await _sendFollowUp(tester, '这份草稿还没保存对吗？请用两句话解释。');
    expect(agentController.confirmations.single.id, cancellable.id);
    // Follow-up replies scroll to the tail; the original card stays in its timeline position.
    await tester.scrollUntilVisible(
      find.text('确认保存'),
      -220,
      scrollable: find
          .descendant(
            of: find.byType(AgentPage),
            matching: find.byType(Scrollable),
          )
          .first,
      maxScrolls: 40,
    );
    await tester.pumpAndSettle();
    expect(find.text('确认保存'), findsOneWidget);
    debugPrintSynchronously(
      'Acceptance: ordinary follow-up preserved pending card',
    );
    await _sendFollowUp(tester, '取消刚才这份晚餐草稿。');
    expect(agentController.confirmations, isEmpty);
    expect(find.text('确认保存'), findsNothing);
    final cancelled = await api.get('/confirmations/${cancellable.id}');
    expect((cancelled as Map)['status'], 'cancelled');
    expect(
      (await api.get(
        '/nutrition/entries',
        query: {'date': _date},
      ) as List).length,
      2,
    );
    debugPrintSynchronously(
      'Acceptance: chat cancellation changed no saved meals',
    );
    final history = await api.get('/workouts', query: {'status': 'completed'});
    final oldHistory = (history as Map)['list'] as List;
    final workoutId = (oldHistory.first as Map)['id'] as String;
    final originalWorkout = await api.get('/workouts/$workoutId');
    await _sendFollowUp(
      tester,
      '把$_sourceDate尚未完成的训练用顺延方式移到$_targetDate，先生成待确认草稿。',
    );
    await _waitFor(tester, find.text('确认更改'), attempts: 600);
    await _waitForIdle(tester);
    final originalScheduleCard = agentController.confirmations.single;
    final changedDate = DateTime.parse(_targetDate)
        .add(const Duration(days: 1))
        .toIso8601String()
        .substring(0, 10);
    await _sendFollowUp(tester, '刚才的改期草稿改到$changedDate，原训练不变，先不要执行。');
    final scheduleCard = agentController.confirmations.single;
    expect(scheduleCard.id, isNot(originalScheduleCard.id));
    expect(
      scheduleCard.after!['replaces_confirmation_id'],
      originalScheduleCard.id,
    );
    final oldState = await api.get('/confirmations/${originalScheduleCard.id}');
    expect((oldState as Map)['status'], 'rejected');
    debugPrintSynchronously(
      'Acceptance: chat reschedule revision invalidated only old card',
    );
    final sourceEventId =
        (((scheduleCard.draft!['before_events'] as List).first) as Map)['id'];
    final beforeCalendar = await api.get(
      '/calendar',
      query: {'start_date': _sourceDate, 'end_date': changedDate},
    );
    expect(
      (beforeCalendar as List).whereType<Map>().singleWhere(
        (e) => e['id'] == sourceEventId,
      )['scheduled_date'],
      _sourceDate,
    );
    await tester.ensureVisible(find.text('确认更改'));
    await tester.tap(find.text('确认更改'));
    for (var i = 0; i < 100; i++) {
      await tester.pump(const Duration(milliseconds: 500));
      if (find.text('确认更改').evaluate().isEmpty) break;
    }
    expect(find.text('确认更改'), findsNothing);
    final afterCalendar = await api.get(
      '/calendar',
      query: {'start_date': _sourceDate, 'end_date': changedDate},
    );
    expect(
      (afterCalendar as List).whereType<Map>().singleWhere(
        (e) => e['id'] == sourceEventId,
      )['scheduled_date'],
      changedDate,
    );
    debugPrintSynchronously(
      'Acceptance: schedule changed only after App confirmation',
    );
    final progressionRequest = agentController.send(
      '按最近一次已经完成的训练，生成下次保守递增草稿，等我确认后生效。',
    );
    await _waitFor(tester, find.text('确认更改'), attempts: 600);
    await _waitForIdle(tester);
    expect(
      agentController.confirmations.single.operationType,
      'training_progression_apply',
    );
    await progressionRequest;
    final progressionId = agentController.confirmations.single.id;
    await tester.ensureVisible(find.text('确认更改'));
    await tester.tap(find.text('确认更改'));
    for (var i = 0; i < 100; i++) {
      await tester.pump(const Duration(milliseconds: 500));
      if (find.text('确认更改').evaluate().isEmpty) break;
    }
    expect(find.text('确认更改'), findsNothing);
    final progression = await api.get('/confirmations/$progressionId');
    expect((progression as Map)['status'], 'succeeded');
    expect(await api.get('/workouts/$workoutId'), originalWorkout);
    debugPrintSynchronously(
      'Acceptance: progression confirmed and historical workout unchanged',
    );
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pump(const Duration(milliseconds: 200));
  });
}

Future<void> _sendFollowUp(WidgetTester tester, String message) async {
  await tester.pumpAndSettle();
  await tester.tap(find.byType(TextField).last);
  await tester.pumpAndSettle();
  await tester.enterText(find.byType(TextField).last, message);
  await tester.pumpAndSettle();
  final button = tester.widget<IconButton>(
    find.widgetWithIcon(IconButton, Icons.arrow_upward_rounded),
  );
  expect(button.onPressed, isNotNull);
  await tester.tap(find.byTooltip('发送'));
  expect(
    tester.widget<AgentPage>(find.byType(AgentPage)).controller.sending,
    isTrue,
    reason: 'Follow-up must actually be sent before checking the result',
  );
  await _waitForIdle(tester);
}

Future<void> _waitFor(
  WidgetTester tester,
  Finder finder, {
  int attempts = 80,
}) async {
  for (var attempt = 0; attempt < attempts; attempt++) {
    await tester.pump(const Duration(milliseconds: 500));
    if (finder.evaluate().isNotEmpty) return;
    if (find.byType(AgentPage).evaluate().isNotEmpty) {
      final error = tester
          .widget<AgentPage>(find.byType(AgentPage))
          .controller
          .errorMessage;
      if (error != null) fail('Agent UI: $error');
    }
  }
  expect(finder, findsWidgets);
}

Future<void> _waitForIdle(WidgetTester tester) async {
  for (var attempt = 0; attempt < 600; attempt++) {
    await tester.pump(const Duration(milliseconds: 500));
    final controller = tester
        .widget<AgentPage>(find.byType(AgentPage))
        .controller;
    if (!controller.sending) {
      expect(controller.errorMessage, isNull);
      await tester.pump();
      return;
    }
  }
  fail('Agent did not finish within acceptance timeout');
}

class _MemoryRefreshTokenStore implements RefreshTokenStore {
  String? _token;
  @override
  Future<String?> read() async => _token;
  @override
  Future<void> write(String token) async {
    _token = token;
  }

  @override
  Future<void> delete() async {
    _token = null;
  }
}

class _DiagnosticApiClient extends ApiClient {
  _DiagnosticApiClient({
    required super.config,
    required super.accessTokenProvider,
  });

  @override
  Future<Object?> request(
    String method,
    String path, {
    Object? body,
    bool authenticated = true,
    Map<String, String>? query,
    String? idempotencyKey,
    String? localDraftKey,
    Duration? timeout,
    bool refreshAuthentication = true,
  }) async {
    final clock = Stopwatch()..start();
    try {
      return await super.request(
        method,
        path,
        body: body,
        authenticated: authenticated,
        query: query,
        idempotencyKey: idempotencyKey,
        localDraftKey: localDraftKey,
        timeout: timeout,
        refreshAuthentication: refreshAuthentication,
      );
    } on ApiException catch (error) {
      debugPrintSynchronously(
        'Acceptance HTTP: $method $path ${error.code} '
        'cause=${error.details.runtimeType}, elapsed=${clock.elapsedMilliseconds}ms',
      );
      rethrow;
    }
  }

  @override
  Stream<SseEvent> postSse(
    String path, {
    required Object body,
    Map<String, String>? query,
    String? idempotencyKey,
  }) async* {
    try {
      yield* super.postSse(
        path,
        body: body,
        query: query,
        idempotencyKey: idempotencyKey,
      );
    } on ApiException catch (error) {
      // Only categories; never headers, credentials or request bodies.
      debugPrintSynchronously(
        'Acceptance SSE: ${error.code}, cause=${error.details.runtimeType}',
      );
      rethrow;
    }
  }
}
