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
import 'package:nxtrep/features/nutrition/presentation/nutrition_page.dart';

void main() {
  final binding = IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  binding.framePolicy = LiveTestWidgetsFlutterBindingFramePolicy.onlyPumps;
  testWidgets(
    'saved meal correction and deletion require approval and refresh nutrition page',
    (tester) async {
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
      const day = String.fromEnvironment('E2E_DATE');
      final entries = await api.request(
        'GET',
        '/nutrition/entries',
        query: {'date': day},
      ) as List;
      final original = entries.singleWhere(
        (e) => (e['items'] as List).any((f) => f['name'] == '验收熟米饭'),
      ) as Map;
      final other = entries.singleWhere(
        (e) => (e['items'] as List).any((f) => f['name'] == '验收面条'),
      ) as Map;
      final id = original['id'];
      final memories = await api.request('GET', '/memories');
      final targets = await api.request('GET', '/nutrition/targets');
      final catalog = await api.request(
        'GET',
        '/foods/search',
        query: {'keyword': '验收熟米饭'},
      );
      final initialSummary = await api.request(
        'GET',
        '/nutrition/daily-summary',
        query: {'date': day},
      ) as Map;
      final initialKcal = num.parse(
        initialSummary['consumed']['kcal'].toString(),
      );
      await tester.tap(find.text('AI私人教练').last);
      await _waitFor(tester, find.byTooltip('发送'));
      await _send(
        tester,
        '请把$day已经保存的午餐中验收熟米饭从200克更正为100克，鸡蛋和其他餐食不变，沿用原营养依据，先给草稿。',
      );
      final controller = tester
          .widget<AgentPage>(find.byType(AgentPage))
          .controller;
      expect(
        controller.confirmations,
        hasLength(1),
        reason: controller.messages.last.content,
      );
      final card = controller.confirmations.single;
      expect(card.operationType, 'nutrition_entry_update');
      expect(card.after!['entry_id'], id);
      expect(find.text('更正已保存饮食'), findsOneWidget);
      expect(await api.request('GET', '/nutrition/entries/$id'), original);
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
      await _waitFor(tester, find.text('确认更正'));
      expect(controller.confirmations.single.id, card.id);
      await _approve(tester, '确认更正');
      final corrected =
          await api.request('GET', '/nutrition/entries/$id') as Map;
      expect(num.parse(corrected['items'][0]['amount_g'].toString()), 100);
      expect(corrected['items'][1], original['items'][1]);
      expect(num.parse(corrected['totals']['kcal'].toString()), 280);
      await _showNutrition(tester);
      final nutrition = tester
          .widget<NutritionPage>(find.byType(NutritionPage))
          .controller;
      expect(
        nutrition.entries.singleWhere((e) => e.id == id).items.first.amountG,
        100,
      );
      expect(nutrition.summary!.consumed.kcal, initialKcal - 130);
      await tester.scrollUntilVisible(
        find.text('验收熟米饭、验收鸡蛋'),
        450,
        scrollable: find.byType(Scrollable).first,
        maxScrolls: 20,
      );
      expect(find.text('验收熟米饭、验收鸡蛋'), findsOneWidget);
      await tester.tap(find.text('AI私人教练').last);
      await _send(tester, '请删除$day午餐中含验收熟米饭的那条已保存记录，这一餐是误记，其他餐食和食品库不变，先给草稿。');
      expect(
        controller.confirmations,
        hasLength(1),
        reason: controller.messages.last.content,
      );
      expect(
        controller.confirmations.single.operationType,
        'nutrition_entry_delete',
      );
      expect(controller.confirmations.single.after!['entry_id'], id);
      expect(await api.request('GET', '/nutrition/entries/$id'), corrected);
      await _approve(tester, '确认删除');
      final remaining = await api.request(
        'GET',
        '/nutrition/entries',
        query: {'date': day},
      ) as List;
      expect(remaining.any((e) => e['id'] == id), isFalse);
      expect(
        await api.request('GET', '/nutrition/entries/${other['id']}'),
        other,
      );
      expect(await api.request('GET', '/memories'), memories);
      expect(await api.request('GET', '/nutrition/targets'), targets);
      expect(
        await api.request('GET', '/foods/search', query: {'keyword': '验收熟米饭'}),
        catalog,
      );
      await _showNutrition(tester);
      expect(nutrition.entries.any((e) => e.id == id), isFalse);
      expect(nutrition.summary!.consumed.kcal, initialKcal - 410);
      expect(nutrition.weeklySummary!.totalEntries, remaining.length);
      await tester.scrollUntilVisible(
        find.text('验收面条'),
        450,
        scrollable: find.byType(Scrollable).first,
        maxScrolls: 20,
      );
      expect(find.text('验收面条'), findsOneWidget);
      expect(find.text('验收熟米饭、验收鸡蛋'), findsNothing);
      debugPrint(
        'Acceptance: saved meal card restored and approved, original basis and other food retained, mistaken meal deleted, nutrition page and weekly stats refreshed, catalog targets memory unchanged',
      );
      expect(tester.takeException(), isNull);
    },
  );
}

Future<void> _showNutrition(WidgetTester tester) async {
  FocusManager.instance.primaryFocus?.unfocus();
  await tester.pumpAndSettle();
  await tester.tap(find.text('饮食').last);
  await _waitFor(tester, find.byType(NutritionPage));
  final controller = tester
      .widget<NutritionPage>(find.byType(NutritionPage))
      .controller;
  for (var i = 0; i < 100; i++) {
    await tester.pump(const Duration(milliseconds: 300));
    if (!controller.loading) {
      expect(controller.errorMessage, isNull);
      return;
    }
  }
  fail('Nutrition page did not refresh');
}

Future<void> _send(WidgetTester tester, String text) async {
  await _waitFor(tester, find.byTooltip('发送'));
  await tester.ensureVisible(find.byType(TextField).last);
  await tester.tap(find.byType(TextField).last);
  await tester.pump();
  await tester.enterText(find.byType(TextField).last, text);
  await tester.pumpAndSettle();
  expect(
    tester.widget<TextField>(find.byType(TextField).last).controller!.text,
    text,
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
      await tester.pumpAndSettle();
      return;
    }
  }
  fail('Agent did not finish within acceptance timeout');
}

Future<void> _approve(WidgetTester tester, String label) async {
  final controller = tester
      .widget<AgentPage>(find.byType(AgentPage))
      .controller;
  final card = controller.confirmations.single;
  FocusManager.instance.primaryFocus?.unfocus();
  await tester.pumpAndSettle();
  final button = find.widgetWithText(FilledButton, label);
  await Scrollable.ensureVisible(tester.element(button), alignment: 0.5);
  await tester.pumpAndSettle();
  await tester.tap(button);
  for (var i = 0; i < 100 && controller.isDeciding(card); i++) {
    await tester.pump(const Duration(milliseconds: 200));
  }
  expect(controller.errorMessage, isNull);
  expect(controller.confirmations, isEmpty);
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
