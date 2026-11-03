import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:nxtrep/core/config/api_config.dart';
import 'package:nxtrep/core/network/api_client.dart';
import 'package:nxtrep/core/storage/refresh_token_store.dart';
import 'package:nxtrep/core/theme/app_theme.dart';
import 'package:nxtrep/features/agent/data/proactive_repository.dart';
import 'package:nxtrep/features/agent/presentation/proactive_controller.dart';
import 'package:nxtrep/features/auth/data/auth_repository.dart';
import 'package:nxtrep/features/auth/domain/session_tokens.dart';
import 'package:nxtrep/features/exercises/data/exercise_repository.dart';
import 'package:nxtrep/features/training/data/training_repository.dart';
import 'package:nxtrep/features/training/presentation/today_page.dart';
import 'package:nxtrep/features/training/presentation/training_controller.dart';

void main() {
  final binding = IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  testWidgets(
    'plan and self training: adjustable sets, rest, and next exercise',
    (tester) async {
      final tokens = SessionTokens(_MemoryStore());
      final api = ApiClient(
        config: ApiConfig(),
        accessTokenProvider: () => tokens.accessToken,
      );
      final auth = AuthRepository(apiClient: api, tokens: tokens);
      await auth.login(
        username: const String.fromEnvironment('E2E_USERNAME'),
        password: const String.fromEnvironment('E2E_PASSWORD'),
      );
      final repository = TrainingRepository(api);
      final training = TrainingController(repository);
      final proactive = ProactiveController(ProactiveRepository(api));
      addTearDown(() async {
        await auth.logout();
        training.dispose();
        proactive.dispose();
        api.close();
      });
      await tester.pumpWidget(
        MaterialApp(
          theme: AppTheme.light(),
          home: TodayPage(
            username: '训练页面临时验收',
            controller: training,
            proactiveController: proactive,
            exerciseRepository: ExerciseRepository(api),
            onOpenNutrition: () {},
            onOpenPlan: () {},
            onOpenProgress: () {},
            onOpenAgent: () {},
            onOpenExerciseLibrary: () {},
            onDiscussNotice: (_) {},
          ),
        ),
      );
      await _waitFor(tester, find.text('按计划训练'));
      await tester.tap(find.text('按计划训练'));
      await _waitFor(tester, find.text('训练前状态'));
      await tester.tap(find.text('开始训练'));
      await _waitFor(tester, find.text('0/4 组'));
      expect(find.text('计划训练'), findsOneWidget);
      expect(find.text('临时添加动作'), findsOneWidget);

      await tester.tap(find.text('0/4 组'));
      await _waitFor(tester, find.text('调整目标组数'));
      await tester.enterText(find.byType(TextFormField), '5');
      await tester.tap(find.text('保存'));
      await _waitFor(tester, find.text('0/5 组'));
      await tester.tap(find.text('休息时长'));
      await _waitFor(tester, find.text('组间休息'));
      await tester.enterText(find.byType(TextFormField), '75');
      await tester.tap(find.text('保存'));
      await _waitFor(tester, find.text('01:15'));
      await tester.tap(find.text('完成下一组'));
      await _waitFor(tester, find.text('完成这一组'));
      await tester.enterText(find.byType(TextFormField).first, '55');
      await tester.enterText(find.byType(TextFormField).last, '8');
      await tester.tap(find.text('完成这一组'));
      await _waitFor(tester, find.text('1/5 组'));
      expect(find.text('组间休息'), findsOneWidget);
      final firstRemaining = training.activeWorkout!.restTimer!.remainingAt(
        DateTime.now(),
      );
      await tester.pump(const Duration(seconds: 3));
      expect(
        training.activeWorkout!.restTimer!.remainingAt(DateTime.now()),
        lessThan(firstRemaining),
      );
      await binding.convertFlutterSurfaceToImage();
      await tester.pump();
      await binding.takeScreenshot('plan-rest');

      final savedId = training.activeWorkout!.id;
      await tester.pageBack();
      await _waitFor(tester, find.text('继续训练'));
      await tester.tap(find.text('继续训练'));
      await _waitFor(tester, find.text('1/5 组'));
      expect(training.activeWorkout!.id, savedId);
      expect(
        (await repository.getActiveWorkout())!.exercises.single.restSeconds,
        75,
      );
      await tester.tap(find.byTooltip('暂停训练'));
      await _waitFor(tester, find.byTooltip('继续训练'));
      final paused = training.activeWorkout!;
      final remaining = paused.restTimer!.remainingAt(paused.pausedAt!);
      await tester.pump(const Duration(seconds: 2));
      expect(
        training.activeWorkout!.restTimer!.remainingAt(paused.pausedAt!),
        remaining,
      );
      await tester.tap(find.byTooltip('继续训练'));
      await _waitFor(tester, find.byTooltip('暂停训练'));

      await tester.tap(find.text('结束'));
      await _waitFor(tester, find.text('保存并完成训练'));
      await tester.tap(find.text('保存并完成训练'));
      await _waitFor(tester, find.text('训练完成'));
      await tester.tap(find.text('完成'));
      await _waitFor(tester, find.text('自主训练'));
      await tester.tap(find.text('自主训练'));
      await _waitFor(tester, find.text('训练前状态'));
      await tester.tap(find.text('开始训练'));
      await _waitFor(tester, find.text('添加第一个动作'));
      expect(training.activeWorkout!.isPlanBased, isFalse);
      await tester.tap(find.text('添加第一个动作'));
      await _waitFor(tester, find.text('搜索动作名称、器械或肌群'));
      await tester.enterText(find.byType(TextField), '史密斯上斜推胸');
      final inclineOption = find.widgetWithText(ListTile, '史密斯上斜推胸');
      await _waitFor(tester, inclineOption);
      await tester.tap(inclineOption);
      await _waitFor(tester, find.text('0/3 组'));
      expect(find.text('下一个动作'), findsOneWidget);
      expect(find.text('临时添加动作'), findsNothing);
      expect(training.activeWorkout!.exercises.single.sets, isEmpty);
      await binding.takeScreenshot('self-training');
      await tester.tap(find.text('下一个动作'));
      await _waitFor(tester, find.text('搜索动作名称、器械或肌群'));
      await tester.enterText(find.byType(TextField), '杠铃卧推');
      final benchOption = find.widgetWithText(ListTile, '杠铃卧推');
      await _waitFor(tester, benchOption);
      await tester.tap(benchOption);
      await _waitFor(tester, find.text('0/3 组').last);
      expect(training.activeWorkout!.exercises.length, 2);
      expect(training.activeWorkout!.completedSetCount, 0);
      expect(tester.takeException(), isNull);
    },
  );
}

Future<void> _waitFor(WidgetTester tester, Finder finder) async {
  for (var attempt = 0; attempt < 60; attempt++) {
    await tester.pump(const Duration(milliseconds: 250));
    if (finder.evaluate().isNotEmpty && !tester.binding.hasScheduledFrame) {
      return;
    }
  }
  expect(finder, findsWidgets);
}

class _MemoryStore implements RefreshTokenStore {
  String? _value;
  @override
  Future<String?> read() async => _value;
  @override
  Future<void> write(String token) async {
    _value = token;
  }

  @override
  Future<void> delete() async {
    _value = null;
  }
}
