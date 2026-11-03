import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:uuid/uuid.dart';
import 'package:nxtrep/app/nxtrep_app.dart';
import 'package:nxtrep/core/config/api_config.dart';
import 'package:nxtrep/core/network/api_client.dart';
import 'package:nxtrep/core/network/api_exception.dart';
import 'package:nxtrep/core/storage/refresh_token_store.dart';
import 'package:nxtrep/features/agent/presentation/agent_page.dart';
import 'package:nxtrep/features/agent/presentation/agent_controller.dart';
import 'package:nxtrep/features/agent/domain/agent_models.dart';
import 'package:nxtrep/features/auth/data/auth_repository.dart';
import 'package:nxtrep/features/auth/domain/session_tokens.dart';
import 'package:nxtrep/features/auth/presentation/session_controller.dart';
import 'package:nxtrep/features/onboarding/data/onboarding_repository.dart';

const _username = String.fromEnvironment('E2E_USERNAME');
const _password = String.fromEnvironment('E2E_PASSWORD');

void main() {
  final binding = IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  binding.framePolicy = LiveTestWidgetsFlutterBindingFramePolicy.onlyPumps;
  testWidgets('custom food approval and autonomous memory use separate stores', (
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
    await tester.enterText(find.byType(TextFormField).at(0), _username);
    await tester.enterText(find.byType(TextFormField).at(1), _password);
    await tester.tap(find.text('登录'));
    await _waitFor(tester, find.byType(NavigationBar));
    await tester.tap(find.text('AI私人教练').last);
    await _waitFor(tester, find.byTooltip('发送'));
    await _send(tester, '帮我在食品库添加自定义食品麦当劳的双层吉士汉堡和一个香芋派');
    final controller = tester
        .widget<AgentPage>(find.byType(AgentPage))
        .controller;
    expect(controller.confirmations.length, 2);
    expect(
      controller.confirmations.every((c) => c.operationType == 'food_create'),
      isTrue,
    );
    final originalIds = controller.confirmations.map((c) => c.id).toSet();
    final conversationId = controller.conversationId!;
    final conversations = await controller.listConversations();
    final conversation = conversations.singleWhere(
      (c) => c.id == conversationId,
    );
    await tester.tap(find.byTooltip('新对话'));
    await tester.pumpAndSettle();
    await _reopenHistory(tester, conversation.title ?? '训练咨询');
    await tester.pumpAndSettle();
    expect(controller.confirmations.map((c) => c.id).toSet(), originalIds);
    expect(controller.statusMessage, contains('已恢复 2 份'));
    debugPrint(
      'Acceptance: leaving and reopening restores the same two pending cards',
    );
    final card = controller.confirmations.first;
    final name = (card.after!['food'] as Map)['name'] as String;
    final before = await api.request(
      'GET',
      '/nutrition/entries',
      query: {'date': const String.fromEnvironment('E2E_DATE')},
    );
    FocusManager.instance.primaryFocus?.unfocus();
    await tester.pumpAndSettle();
    final approve = find.widgetWithText(FilledButton, '确认添加').first;
    await Scrollable.ensureVisible(tester.element(approve), alignment: 0.5);
    await tester.pumpAndSettle();
    await tester.tap(approve);
    for (var i = 0; i < 100 && controller.isDeciding(card); i++) {
      await tester.pump(const Duration(milliseconds: 500));
    }
    expect(controller.errorMessage, isNull);
    expect(controller.confirmations.any((item) => item.id == card.id), isFalse);
    expect(controller.confirmations.single.status, 'pending');
    final search = await api.request(
      'GET',
      '/foods/search',
      query: {'keyword': name},
    ) as Map;
    expect(
      (search['list'] as List).any((f) => (f as Map)['name'] == name),
      isTrue,
    );
    final after = await api.request(
      'GET',
      '/nutrition/entries',
      query: {'date': const String.fromEnvironment('E2E_DATE')},
    );
    expect((after as List).length, (before as List).length);
    await _reopenHistory(tester, conversation.title ?? '训练咨询');
    expect(controller.confirmations.length, 1);
    expect(controller.confirmations.single.id, isNot(card.id));
    expect(controller.statusMessage, contains('1 份已确认生效'));
    // Recreate the whole widget tree, including its repository and AgentController.
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pumpAndSettle();
    final restartedSession = SessionController(
      authRepository: auth,
      onboardingRepository: OnboardingRepository(api),
    );
    await tester.pumpWidget(NxtRepApp(sessionController: restartedSession));
    await _waitFor(tester, find.byType(NavigationBar));
    await tester.tap(find.text('AI私人教练').last);
    await _waitFor(tester, find.byTooltip('发送'));
    final restarted = tester
        .widget<AgentPage>(find.byType(AgentPage))
        .controller;
    await _reopenHistory(tester, conversation.title ?? '训练咨询');
    await tester.pumpAndSettle();
    expect(restarted.confirmations.length, 1);
    expect(restarted.confirmations.single.id, isNot(card.id));
    expect(restarted.statusMessage, contains('1 份已确认生效'));
    debugPrint(
      'Acceptance: fresh App controllers recover pending and succeeded states',
    );
    debugPrint(
      'Acceptance: catalog card approved in App; meal count unchanged',
    );
    await _send(tester, '我不吃香菜');
    final stable = await api.request('GET', '/memories') as Map;
    final memories = stable['list'] as List;
    expect(
      memories.any((m) => (m as Map)['content'].toString().contains('香菜')),
      isTrue,
    );
    expect(
      memories.any((m) => (m as Map)['content'].toString().contains('汉堡')),
      isFalse,
    );
    await _send(tester, '我今天不吃葱，明天可以吃');
    final temporary = await api.request('GET', '/memories') as Map;
    expect((temporary['list'] as List).length, memories.length);
    debugPrint(
      'Acceptance: stable preference saved autonomously; temporary state not saved',
    );
    if (const bool.fromEnvironment('E2E_FOOD_CHANGES')) {
      final matches = (search['list'] as List).cast<Map>();
      final saved = matches.firstWhere((f) => f['name'] == name);
      final foodId = saved['id'] as String;
      final original = await api.request('GET', '/foods/$foodId') as Map;
      final meal = await api.request(
        'POST',
        '/nutrition/entries',
        idempotencyKey: const Uuid().v4(),
        body: {
          'meal_type': 'lunch',
          'eaten_at': DateTime.now().toUtc().toIso8601String(),
          'items': [
            {'food_version_id': original['food_version_id'], 'amount_g': 100},
          ],
        },
      ) as Map;
      final oldTotals = meal['totals'];
      await _send(
        tester,
        '把食品库里我刚添加的$name热量改成每${original['basis_amount_g']}克420千卡，'
        '蛋白质、碳水、脂肪和其他字段都不变，先出草稿。',
      );
      final edit = restarted.confirmations.singleWhere(
        (c) => c.operationType == 'food_update',
      );
      expect(num.parse((edit.after!['food'] as Map)['kcal'].toString()), 420);
      final pending = await api.request('GET', '/foods/$foodId') as Map;
      expect(pending['kcal'], original['kcal']);
      await _approve(tester, '确认修改', restarted, edit);
      final updated = await api.request('GET', '/foods/$foodId') as Map;
      expect(num.parse(updated['kcal'].toString()), 420);
      expect(updated['protein_g'], original['protein_g']);
      expect(updated['carbs_g'], original['carbs_g']);
      expect(updated['fat_g'], original['fat_g']);
      await _reopenHistory(tester, conversation.title ?? '训练咨询');
      expect(restarted.confirmations.any((c) => c.id == edit.id), isFalse);
      await _send(tester, '从食品库删除我刚修改的$name，只删除食品条目，历史午餐保留。');
      final deletion = restarted.confirmations.singleWhere(
        (c) => c.operationType == 'food_delete',
      );
      expect((await api.request('GET', '/foods/$foodId') as Map)['name'], name);
      await _approve(tester, '确认删除', restarted, deletion);
      await expectLater(
        api.request('GET', '/foods/$foodId'),
        throwsA(isA<ApiException>()),
      );
      final entries = await api.request(
        'GET',
        '/nutrition/entries',
        query: {'date': const String.fromEnvironment('E2E_DATE')},
      ) as List;
      final oldMeal = entries.cast<Map>().singleWhere(
        (e) => e['id'] == meal['id'],
      );
      expect(oldMeal['totals'], oldTotals);
      final remainingMemories = await api.request('GET', '/memories') as Map;
      expect((remainingMemories['list'] as List).length, memories.length);
      debugPrint(
        'Acceptance: food edit and delete approved in App; old meal nutrition and memory unchanged',
      );
    }
    expect(tester.takeException(), isNull);
  });
}

Future<void> _reopenHistory(WidgetTester tester, String title) async {
  FocusManager.instance.primaryFocus?.unfocus();
  await tester.pumpAndSettle();
  await tester.tap(find.byTooltip('历史与记忆'));
  await _waitFor(tester, find.text('AI 私人教练管理'));
  await _waitFor(tester, find.text(title));
  await tester.tap(find.text(title).first);
  await _waitFor(tester, find.byTooltip('发送'));
  await tester.pumpAndSettle();
}

Future<void> _approve(
  WidgetTester tester,
  String label,
  AgentController controller,
  AgentConfirmationCard card,
) async {
  FocusManager.instance.primaryFocus?.unfocus();
  await tester.pumpAndSettle();
  final button = find.widgetWithText(FilledButton, label);
  await Scrollable.ensureVisible(tester.element(button), alignment: 0.5);
  await tester.pumpAndSettle();
  await tester.tap(button);
  for (var i = 0; i < 100 && controller.isDeciding(card); i++) {
    await tester.pump(const Duration(milliseconds: 500));
  }
  expect(controller.errorMessage, isNull);
  expect(controller.confirmations.any((c) => c.id == card.id), isFalse);
}

Future<void> _send(WidgetTester tester, String message) async {
  await tester.ensureVisible(find.byType(TextField).last);
  await tester.tap(find.byType(TextField).last);
  await tester.pump();
  await tester.enterText(find.byType(TextField).last, message);
  await tester.pumpAndSettle();
  expect(
    tester.widget<TextField>(find.byType(TextField).last).controller!.text,
    message,
  );
  expect(
    tester
        .widget<IconButton>(
          find.widgetWithIcon(IconButton, Icons.arrow_upward_rounded),
        )
        .onPressed,
    isNotNull,
  );
  await tester.tap(find.byTooltip('发送'));
  final controller = tester
      .widget<AgentPage>(find.byType(AgentPage))
      .controller;
  expect(controller.sending, isTrue);
  for (var i = 0; i < 600; i++) {
    await tester.pump(const Duration(milliseconds: 500));
    if (!controller.sending) {
      expect(controller.errorMessage, isNull);
      await tester.pump();
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
