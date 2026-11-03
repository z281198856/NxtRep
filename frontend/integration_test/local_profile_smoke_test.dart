import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:nxtrep/app/nxtrep_app.dart';
import 'package:nxtrep/core/config/api_config.dart';
import 'package:nxtrep/core/network/api_client.dart';
import 'package:nxtrep/core/storage/refresh_token_store.dart';
import 'package:nxtrep/features/agent/presentation/agent_page.dart';
import 'package:nxtrep/features/auth/data/auth_repository.dart';
import 'package:nxtrep/features/auth/domain/session_tokens.dart';
import 'package:nxtrep/features/auth/presentation/session_controller.dart';
import 'package:nxtrep/features/onboarding/data/onboarding_repository.dart';

void main() {
  final binding = IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  binding.framePolicy = LiveTestWidgetsFlutterBindingFramePolicy.onlyPumps;
  testWidgets('profile update waits for approval and restores from history', (
    tester,
  ) async {
    final tokens = SessionTokens(_MemoryStore());
    final api = ApiClient(
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
    await tester.enterText(
      find.byType(TextFormField).at(0),
      const String.fromEnvironment('E2E_USERNAME'),
    );
    await tester.enterText(
      find.byType(TextFormField).at(1),
      const String.fromEnvironment('E2E_PASSWORD'),
    );
    await tester.tap(find.text('登录'));
    await _waitFor(tester, find.byType(NavigationBar));
    final original = await api.request('GET', '/profile') as Map;
    final memories = await api.request('GET', '/memories') as Map;
    await tester.tap(find.text('AI私人教练').last);
    await _waitFor(tester, find.byTooltip('发送'));
    await _send(
      tester,
      '请把个人资料中的身高改为176厘米，每周训练天数改为5天，单次训练时长改为30分钟，其他资料不变；先给草稿，不要修改已有计划或长期记忆。',
    );
    final controller = tester
        .widget<AgentPage>(find.byType(AgentPage))
        .controller;
    final card = controller.confirmations.single;
    expect(card.operationType, 'profile_update');
    expect(find.text('修改个人资料'), findsOneWidget);
    expect(find.textContaining('身高：'), findsOneWidget);
    expect(await api.request('GET', '/profile'), original);
    final conversationId = controller.conversationId!;
    final conversation = (await controller.listConversations()).singleWhere(
      (c) => c.id == conversationId,
    );
    FocusManager.instance.primaryFocus?.unfocus();
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('新对话'));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('历史与记忆'));
    await _waitFor(tester, find.text('AI 私人教练管理'));
    final title = conversation.title ?? '训练咨询';
    await _waitFor(tester, find.text(title));
    await tester.tap(find.text(title).first);
    await _waitFor(tester, find.text('确认修改'));
    expect(controller.confirmations.single.id, card.id);
    final button = find.widgetWithText(FilledButton, '确认修改');
    await Scrollable.ensureVisible(tester.element(button), alignment: 0.5);
    await tester.pumpAndSettle();
    await tester.tap(button);
    for (var i = 0; i < 100 && controller.isDeciding(card); i++) {
      await tester.pump(const Duration(milliseconds: 200));
    }
    expect(controller.errorMessage, isNull);
    expect(controller.confirmations, isEmpty);
    final updated = await api.request('GET', '/profile') as Map;
    expect(num.parse(updated['height_cm'].toString()), 176);
    expect(updated['weekly_training_days'], 5);
    expect(updated['session_duration_minutes'], 30);
    expect(updated['version'], (original['version'] as int) + 1);
    expect(updated['display_name'], original['display_name']);
    expect(updated['weight_kg'], original['weight_kg']);
    expect(
      (await api.request('GET', '/memories') as Map)['list'],
      memories['list'],
    );
    await tester.tap(find.text('我的').last);
    await _waitFor(tester, find.text('个人资料'));
    await tester.tap(find.text('个人资料'));
    await _waitFor(tester, find.text('保存个人资料'));
    final values = tester
        .widgetList<TextFormField>(find.byType(TextFormField))
        .map((f) => f.controller?.text)
        .toList();
    expect(values.map((value) => num.tryParse(value ?? '')), contains(176));
    expect(values, contains('30'));
    await tester.pageBack();
    await _waitFor(tester, find.text('训练偏好'));
    await tester.tap(find.text('训练偏好'));
    await _waitFor(tester, find.text('保存训练偏好'));
    expect(
      tester
          .widget<ChoiceChip>(find.widgetWithText(ChoiceChip, '5 次'))
          .selected,
      isTrue,
    );
    debugPrint(
      'Acceptance: profile card restored and approved in App; profile page shows new values; memory unchanged',
    );
    expect(tester.takeException(), isNull);
  });
}

Future<void> _send(WidgetTester tester, String text) async {
  await tester.enterText(find.byType(TextField).last, text);
  await tester.pumpAndSettle();
  await tester.tap(find.byTooltip('发送'));
  final controller = tester
      .widget<AgentPage>(find.byType(AgentPage))
      .controller;
  for (var i = 0; i < 600; i++) {
    await tester.pump(const Duration(milliseconds: 500));
    if (!controller.sending) {
      expect(controller.errorMessage, isNull);
      await tester.pumpAndSettle();
      return;
    }
  }
  fail('Agent did not finish within acceptance timeout');
}

Future<void> _waitFor(WidgetTester tester, Finder finder) async {
  for (var i = 0; i < 100; i++) {
    await tester.pump(const Duration(milliseconds: 500));
    if (finder.evaluate().isNotEmpty) return;
  }
  expect(finder, findsWidgets);
}

class _MemoryStore implements RefreshTokenStore {
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
