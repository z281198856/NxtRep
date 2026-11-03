import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:nxtrep/app/nxtrep_app.dart';
import 'package:nxtrep/core/config/api_config.dart';
import 'package:nxtrep/core/network/api_client.dart';
import 'package:nxtrep/core/storage/refresh_token_store.dart';
import 'package:nxtrep/features/auth/data/auth_repository.dart';
import 'package:nxtrep/features/auth/domain/session_tokens.dart';
import 'package:nxtrep/features/auth/presentation/session_controller.dart';
import 'package:nxtrep/features/onboarding/data/onboarding_repository.dart';
import 'package:nxtrep/features/nutrition/presentation/nutrition_page.dart';

const _username = String.fromEnvironment('E2E_USERNAME');
const _password = String.fromEnvironment('E2E_PASSWORD');

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('local backend: meal write and primary tabs work', (
    tester,
  ) async {
    expect(_username.isNotEmpty && _password.isNotEmpty, isTrue);

    final tokens = SessionTokens(_MemoryRefreshTokenStore());
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

    await tester.tap(find.text('饮食').last);
    await _waitFor(tester, find.text('饮食记录'));
    await _scrollNutritionTo(tester, find.text('拍照记一餐'));
    await tester.tap(find.text('拍照记一餐'));
    await _waitFor(tester, find.text('相册'));
    expect(find.text('拍照'), findsOneWidget);
    await tester.pageBack();
    await tester.pump(const Duration(milliseconds: 500));

    await _scrollNutritionTo(tester, find.text('手动填写'));
    await tester.tap(find.text('手动填写'));
    await _waitFor(tester, find.text('记录饮食'));

    final mealName = 'E2E测试餐${DateTime.now().millisecondsSinceEpoch}';
    await tester.enterText(find.byType(TextFormField).at(0), mealName);
    await tester.enterText(find.byType(TextFormField).at(2), '240');
    await tester.enterText(find.byType(TextFormField).at(3), '20');
    await tester.enterText(find.byType(TextFormField).at(4), '25');
    await tester.enterText(find.byType(TextFormField).at(5), '6');
    await tester.pump(const Duration(milliseconds: 300));
    await tester.ensureVisible(find.text('保存记录'));
    await tester.tap(find.text('保存记录'));
    await _waitFor(tester, find.text('饮食记录'));
    await _scrollNutritionTo(tester, find.text(mealName), delta: -220);
    await _waitFor(tester, find.text(mealName), attempts: 80);

    await tester.tap(find.text('进展').last);
    await _waitFor(tester, find.text('围度估算体脂'));
    expect(find.text('身体进度'), findsOneWidget);

    await tester.tap(find.text('我的').last);
    await _waitFor(tester, find.text('E2E Test'));
    expect(find.text('个人资料'), findsOneWidget);
  });
}

Future<void> _scrollNutritionTo(
  WidgetTester tester,
  Finder finder, {
  double delta = 220,
}) async {
  await tester.scrollUntilVisible(
    finder,
    delta,
    scrollable: find
        .descendant(
          of: find.byType(NutritionPage),
          matching: find.byType(Scrollable),
        )
        .first,
    maxScrolls: 30,
  );
  await tester.pumpAndSettle();
}

Future<void> _waitFor(
  WidgetTester tester,
  Finder finder, {
  int attempts = 40,
}) async {
  for (var attempt = 0; attempt < attempts; attempt++) {
    await tester.pump(const Duration(milliseconds: 500));
    if (finder.evaluate().isNotEmpty) return;
  }
  expect(finder, findsWidgets);
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
