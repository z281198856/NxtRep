import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:nxtrep/app/nxtrep_app.dart';
import 'package:nxtrep/core/config/api_config.dart';
import 'package:nxtrep/core/network/api_client.dart';
import 'package:nxtrep/core/storage/refresh_token_store.dart';
import 'package:nxtrep/core/widgets/app_widgets.dart';
import 'package:nxtrep/features/agent/presentation/agent_page.dart';
import 'package:nxtrep/features/auth/data/auth_repository.dart';
import 'package:nxtrep/features/auth/domain/session_tokens.dart';
import 'package:nxtrep/features/auth/presentation/session_controller.dart';
import 'package:nxtrep/features/onboarding/data/onboarding_repository.dart';
import 'package:nxtrep/features/training/presentation/workout_history_page.dart';

void main() {
  final binding = IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  binding.framePolicy = LiveTestWidgetsFlutterBindingFramePolicy.onlyPumps;
  testWidgets(
    'correct and void one workout set with approval and historical recovery',
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
      final history =
          (await api.request('GET', '/workouts') as Map)['list'] as List;
      final chosen = history.first as Map;
      final id = chosen['id'];
      final original = await api.request('GET', '/workouts/$id') as Map;
      final exercise = (original['exercises'] as List).first as Map;
      final sets = exercise['sets'] as List;
      final target = sets.singleWhere((s) => s['set_index'] == 2) as Map;
      final plan = await api.request('GET', '/training/plans/active');
      final memories = await api.request('GET', '/memories');
      final summary = await api.request('GET', '/workouts/$id/summary') as Map;
      final subject = '${chosen['date']}那次训练中，${exercise['name_snapshot']}第2组';
      await tester.tap(find.text('AI私人教练').last);
      await _waitFor(tester, find.byTooltip('发送'));
      await _send(tester, '请把$subject的实际重量更正为40公斤、次数更正为8次，其他组和训练计划保持原样，先给草稿。');
      final controller = tester
          .widget<AgentPage>(find.byType(AgentPage))
          .controller;
      final card = controller.confirmations.single;
      expect(card.operationType, 'workout_set_update');
      expect(card.after!['set_id'], target['id']);
      expect(find.text('更正训练组记录'), findsOneWidget);
      expect(await api.request('GET', '/workouts/$id'), original);
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
      final corrected = await api.request('GET', '/workouts/$id') as Map;
      final correctedSets =
          (corrected['exercises'] as List).first['sets'] as List;
      final updated =
          correctedSets.singleWhere((s) => s['id'] == target['id']) as Map;
      expect(num.parse(updated['weight_kg'].toString()), 40);
      expect(updated['reps'], 8);
      expect(
        correctedSets.where((s) => s['id'] != target['id']).toList(),
        sets.where((s) => s['id'] != target['id']).toList(),
      );
      await _send(tester, '把$subject作废，是误记，保留其他训练组和修订历史，先给草稿。');
      debugPrint(
        'Void response: ${controller.messages.last.content}; cards: ${controller.confirmations.length}',
      );
      expect(controller.confirmations.single.operationType, 'workout_set_void');
      expect(await api.request('GET', '/workouts/$id'), corrected);
      await _approve(tester, '确认作废');
      final finalWorkout = await api.request('GET', '/workouts/$id') as Map;
      final remaining =
          (finalWorkout['exercises'] as List).first['sets'] as List;
      expect(remaining.any((s) => s['id'] == target['id']), isFalse);
      expect(remaining, sets.where((s) => s['id'] != target['id']).toList());
      final finalSummary =
          await api.request('GET', '/workouts/$id/summary') as Map;
      expect(
        finalSummary['completed_sets'],
        (summary['completed_sets'] as int) - 1,
      );
      expect(
        num.parse(finalSummary['total_volume_kg'].toString()),
        num.parse(summary['total_volume_kg'].toString()) -
            num.parse(target['weight_kg'].toString()) * (target['reps'] as int),
      );
      expect(
        (await api.request('GET', '/workouts/$id/revisions') as List).length,
        2,
      );
      expect(await api.request('GET', '/training/plans/active'), plan);
      expect(await api.request('GET', '/memories'), memories);
      FocusManager.instance.primaryFocus?.unfocus();
      await tester.pumpAndSettle();
      await tester.tap(find.text('计划').last);
      await _waitFor(tester, find.text('训练计划'));
      await tester.scrollUntilVisible(
        find.text('训练历史'),
        500,
        scrollable: find.byType(Scrollable).first,
        maxScrolls: 20,
      );
      final historyButton = find.descendant(
        of: find.widgetWithText(SectionTitle, '训练历史'),
        matching: find.byType(TextButton),
      );
      await Scrollable.ensureVisible(
        tester.element(historyButton),
        alignment: 0.5,
      );
      await tester.pumpAndSettle();
      await tester.tap(historyButton);
      await _waitFor(tester, find.byType(WorkoutHistoryPage));
      await _waitFor(tester, find.text('训练已完成'));
      await tester.tap(find.text('训练已完成').first);
      await _waitFor(tester, find.byType(WorkoutHistoryDetailPage));
      final detail = tester.widget<WorkoutHistoryDetailPage>(
        find.byType(WorkoutHistoryDetailPage),
      );
      expect(detail.workout.id, id);
      expect(detail.historyItem.completedSets, finalSummary['completed_sets']);
      expect(
        detail.historyItem.totalVolumeKg,
        num.parse(finalSummary['total_volume_kg'].toString()),
      );
      expect(
        detail.workout.exercises.first.sets.any((s) => s.id == target['id']),
        isFalse,
      );
      debugPrint(
        'Acceptance: correction card restored and approved, one mistaken set voided, workout history updated, revisions retained, plan and memory unchanged',
      );
      expect(tester.takeException(), isNull);
    },
  );
}

Future<void> _send(WidgetTester tester, String text) async {
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
  expect(
    controller.sending,
    isTrue,
    reason: 'The test must actually submit the new message',
  );
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
